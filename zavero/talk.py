"""Quick answers about the screen: "what is this?", "what does this error mean?", "ee button enti?".

One Muse Spark call with the screenshot (mouse pointer marked) instead of the step-by-step agent,
so the answer comes in a few seconds. The model can also point at what it is talking about.
"""
import base64
import io
import re

from PIL import Image, ImageDraw

from zavero import config
from zavero.driver import Shot
from zavero.reminders import extract_json

# A question about what is on screen (not a request to do something).
QUESTION = [
    r"\bwhat (is|are|does|do) (this|that|these|it|here)\b", r"\bwhat'?s (this|that|here)\b", r"\bexplain\b",
    r"\bwhat (does|do) .{1,40} mean\b", r"\bmeaning of\b", r"\bwhy (is|did|does|am|can'?t|isn'?t)\b",
    r"\bwhat happened\b", r"\bwhat is the error\b", r"\bwhat should i do\b", r"\bis (this|it) safe\b",
    r"\benti\b", r"\bentidi\b", r"\bem(i|iti) idi\b", r"ఏంటి", r"ఏమిటి", r"ఎందుకు", r"అర్థం",
    r"\bkya hai\b", r"\bkya hota\b", r"\bkyu(n|on)?\b", r"\bmatlab\b", r"क्या है", r"क्यों", r"मतलब",
]
# These turn a question into a task ("how do I pay" -> guide them through it).
TASK = [r"\bhow (do|can|to)\b", r"\bopen\b", r"\bela\b", r"\bkaise\b", r"\bkaro\b", r"\bchey", r"कैसे", r"ఎలా"]

SYSTEM = (
    "You are Zavero, a patient helper for a beginner computer user in India. The user asked a question about "
    "their screen. The red circle marks their mouse pointer: 'this' or 'here' usually means the thing under or "
    "next to it. Reply with ONLY one JSON object:\n"
    '{"answer": str, "point": {"x": int, "y": int} | null}\n'
    "- answer: max 3 short, simple sentences. Say what it is, what it does / what the error means, and what "
    "they can do next. No jargon; explain any technical word in plain words. If it looks like a scam, phishing "
    "or a risky download, say so clearly. Keep on-screen labels in English in **bold**.\n"
    "- point: screenshot pixel centre of the thing you are talking about, or null.\n"
    "- Language of answer: {lang}."
)
LANG_NAME = {"te": "Telugu (Telugu script)", "hi": "Hindi (Devanagari)", "en": "simple English"}


def is_question(text: str) -> bool:
    t = (text or "").lower()
    return any(re.search(p, t) for p in QUESTION) and not any(re.search(p, t) for p in TASK)


def mark_pointer(shot: Shot, mouse_x: int, mouse_y: int) -> str:
    """Screenshot data URL with a red circle where the mouse pointer is (real screen px in)."""
    raw = base64.b64decode(shot.data_url.split(",", 1)[1])
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    x, y = (mouse_x - shot.left) / shot.scale, (mouse_y - shot.top) / shot.scale
    ImageDraw.Draw(img).ellipse((x - 14, y - 14, x + 14, y + 14), outline=(255, 0, 0), width=3)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def answer(question: str, shot: Shot, mouse: tuple[int, int], user_lang: str = "en") -> dict:
    """Ask Muse Spark. Returns {"answer": str, "point": {"x", "y"} in screenshot px, or None}."""
    resp = config.client().responses.create(
        model=config.MODEL_SPARK, reasoning=config.REASONING,
        instructions=SYSTEM.replace("{lang}", LANG_NAME.get(user_lang, LANG_NAME["en"])),
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": question},
            {"type": "input_image", "image_url": mark_pointer(shot, *mouse)},
        ]}],
    )
    try:
        data = extract_json(resp.output_text)
    except ValueError:  # plain text answer: still useful
        return {"answer": (resp.output_text or "").strip(), "point": None}
    pt = data.get("point")
    ok = (isinstance(pt, dict) and isinstance(pt.get("x"), (int, float)) and isinstance(pt.get("y"), (int, float))
          and 0 <= pt["x"] < shot.width and 0 <= pt["y"] < shot.height)  # models sometimes point off-screen
    data["point"] = pt if ok else None
    return data
