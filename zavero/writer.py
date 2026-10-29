"""Writes posts for social sites: "post this on LinkedIn", "linkedin lo post chey", "X pe post karo".

Zavero writes the post (Muse Spark, with the screen as context), shows it in the bubble, and only after a
spoken yes opens the site in do mode, pastes it and stops before the final Post button (safety.py asks).
"""
import re
from pathlib import Path

from zavero import config
from zavero.driver import Shot
from zavero.reminders import extract_json

PLATFORMS = {
    "linkedin": (r"linked ?in|లింక్డ్ ?ఇన్|लिंक्ड ?इन", "https://www.linkedin.com/feed/", "Start a post"),
    "x": (r"\btwitter\b|\btweet\b|\bx\b|ట్విట్టర్|ट्विटर", "https://x.com/compose/post", "What is happening?!"),
    "facebook": (r"face ?book|ఫేస్ ?బుక్|फेसबुक", "https://www.facebook.com/", "What's on your mind?"),
}
POST_WORDS = r"\bpost|\btweet|\bshare|\bpettu|\bdaalo|\bdal do|పోస్ట్|పెట్టు|पोस्ट|डालो|शेयर"
SHOT_WORDS = r"screenshot|this screen|my screen|this image|this photo|స్క్రీన్|ఫోటో|स्क्रीन|फोटो"
SHOTS_DIR = Path.home() / "Zavero" / "shots"

STYLE = {
    "linkedin": "LinkedIn post: a strong first hook line, 3-5 short paragraphs, warm and professional, "
                "end with exactly 3 relevant hashtags, at most 2 emoji. Under 1200 characters.",
    "x": "X (Twitter) post: one punchy post, at most 280 characters including 1-2 hashtags.",
    "facebook": "Facebook post: friendly and personal, 2-4 short paragraphs, at most 3 emoji.",
}
SYSTEM = (
    "You write social media posts for a person in India who is not used to writing them. Use what they asked "
    "for and what is on their screen (the screenshot) as the content. Never invent facts, numbers, names or "
    "achievements that are not in the request or the screenshot. Never include phone numbers, addresses, "
    "passwords or ID numbers.\n{style}\n"
    "Language: {lang}. Reply with ONLY JSON: {{\"post\": str, \"summary\": str}} where summary is one short "
    "sentence in the user's language saying what the post is about."
)
LANG_NAME = {"te": "Telugu (Telugu script)", "hi": "Hindi (Devanagari)", "en": "English"}


def platform_of(text: str) -> str | None:
    """Which site the user wants to post on, if this is a posting request."""
    t = text.lower()
    if not re.search(POST_WORDS, t) or re.search(r"\bhow\b|\bela\b|\bkaise\b|ఎలా|कैसे", t):
        return None  # "how do I post on LinkedIn?" is a guide task, not a request to write one
    for name, (pattern, _, _) in PLATFORMS.items():
        if re.search(pattern, t):
            return name
    return None


def wants_screenshot(text: str) -> bool:
    return bool(re.search(SHOT_WORDS, text.lower()))


def post_language(text: str) -> str:
    """Posts are in English unless the user asks for Telugu / Hindi ("Telugu lo", "Hindi mein")."""
    t = text.lower()
    if re.search(r"telugu|తెలుగు", t):
        return "te"
    if re.search(r"hindi|हिंदी|हिन्दी", t):
        return "hi"
    return "en"


def compose_post(request: str, shot: Shot, platform: str, lang: str) -> dict:
    """{"post", "summary"} written by Muse Spark."""
    system = SYSTEM.format(style=STYLE[platform], lang=LANG_NAME.get(lang, "English"))
    resp = config.client().responses.create(
        model=config.MODEL_SPARK, reasoning=config.REASONING, instructions=system,
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": request},
            {"type": "input_image", "image_url": shot.data_url},
        ]}],
    )
    data = extract_json(resp.output_text)
    post = str(data.get("post") or "").strip()
    if not post:
        raise ValueError("empty post")
    if platform == "x":
        post = post[:280]
    return {"post": post, "summary": str(data.get("summary") or "").strip()}


def save_screenshot(shot: Shot) -> Path | None:
    """Keep the screen picture so it can be attached to the post (only when the user asks)."""
    if shot.full is None:
        return None
    from datetime import datetime

    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SHOTS_DIR / f"screen_{datetime.now():%Y%m%d_%H%M%S}.png"
    shot.full.save(path)
    return path


def post_task(platform: str, image: Path | None) -> str:
    """The do-mode task that puts the (already copied) post on the site, stopping before Post."""
    _, url, opener = PLATFORMS[platform]
    steps = [f"Open {url} in the web browser (the user is already signed in).",
             f'Click "{opener}" to open the post editor.',
             "Click inside the text box and press Ctrl+V: the post text is already copied, do not type it."]
    if image:
        steps.append(f'Click the photo/media button and attach the image file "{image}" '
                     "(type the full path into the file name box of the Open dialog, then press Enter).")
    steps.append('STOP before clicking "Post" / "Publish". Finish with a short message that the post is ready '
                 "and they can read it and click Post themselves.")
    return " ".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
