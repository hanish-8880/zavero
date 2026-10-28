"""Quick answers about the screen: "what is this?", "what does this error mean?", "ee button enti?".

One Muse Spark call with the screenshot (mouse pointer marked) instead of the step-by-step agent,
so the answer comes in a few seconds. The model can also point at what it is talking about.
"""
import base64
import io
import re

from PIL import Image, ImageDraw

from zavero import config
from zavero.driver import Shot, crop_png
from zavero.reminders import extract_json

# A question about what is on screen (not a request to do something).
QUESTION = [
    r"\bwhat (is|are|does|do) (this|that|these|it|here)\b", r"\bwhat'?s (this|that|here)\b", r"\bexplain\b",
    r"\bwhat (does|do) .{1,40} mean\b", r"\bmeaning of\b", r"\bwhy (is|did|does|am|can'?t|isn'?t)\b",
    r"\bwhat happened\b", r"\bwhat is the error\b", r"\bwhat should i do\b", r"\bis (this|it) safe\b",
    r"\benti\b", r"\bentidi\b", r"\bem(i|iti) idi\b", r"ఏంటి", r"ఏమిటి", r"ఎందుకు", r"అర్థం",
    r"\bkya hai\b", r"\bkya hota\b", r"\bkyu(n|on)?\b", r"\bmatlab\b", r"क्या है", r"क्यों", r"मतलब",
]
# A picture on screen the user wants explained: Zavero enlarges it and draws numbered marks on it.
DIAGRAM = [r"diagram", r"\bchart", r"\bgraph", r"\bfigure", r"flow ?chart", r"\bpicture", r"\bimage\b",
           r"\bdrawing", r"\bmap\b", r"\bequation", r"\bformula", r"\bslide\b", r"\bboard\b",
           r"డయాగ్రామ్", r"చిత్రం", r"బొమ్మ", r"आरेख", r"चित्र", r"डायग्राम", r"\bbomma\b", r"\bchitra"]
EXPLAIN = [r"\bexplain", r"\bdraw\b", r"\bunderstand", r"\bdoubt", r"\bwhat\b", r"\bmean", r"\bshow\b",
           r"\benti\b", r"\bardam", r"\bartham", r"vivarinch", r"ఏంటి", r"అర్థం", r"వివరించ",
           r"\bkya\b", r"samjha", r"samajh", r"क्या", r"समझा", r"समझ"]
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


SYSTEM_DRAW = (
    "You are Zavero, a patient teacher for a beginner in India. The user has a doubt about a diagram, chart, "
    "slide or picture on their screen (often a paused YouTube video). Find it (the red circle is their mouse "
    "pointer, usually on or near it). You will draw numbered marks on an enlarged copy of it. "
    "Reply with ONLY one JSON object:\n"
    '{"answer": str, "region": {"x": int, "y": int, "w": int, "h": int}, '
    '"marks": [{"x": int, "y": int, "label": str, "detail": str}]}\n'
    "- region: box around the whole diagram in screenshot pixels, with a little margin. Not the whole screen.\n"
    "- marks: 2 to 6 key parts, in the order a teacher would explain them. x, y = centre of that part, in "
    "screenshot pixels, exactly on it. label: 1-4 words. detail: one short simple sentence on what it means "
    "and how it connects to the next part.\n"
    "- answer: one short sentence: what the whole diagram shows.\n"
    "- If there is no diagram, return region null and marks [] and answer the question in 'answer'.\n"
    "- Language of answer, label and detail: {lang}. Keep technical words as on screen, explained simply."
)


def _has(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def is_diagram(text: str) -> bool:
    """'explain this diagram', 'ee diagram enti?', 'ye chart samjhao' -> enlarge + draw."""
    t = (text or "").lower()
    return _has(DIAGRAM, t) and _has(EXPLAIN, t) and not re.search(r"\b(open|create|make|banana|chey)", t)


def is_question(text: str) -> bool:
    t = (text or "").lower()
    return is_diagram(t) or (_has(QUESTION, t) and not _has(TASK, t))


def mark_pointer(shot: Shot, mouse_x: int, mouse_y: int) -> str:
    """Screenshot data URL with a red circle where the mouse pointer is (real screen px in)."""
    raw = base64.b64decode(shot.data_url.split(",", 1)[1])
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    x, y = (mouse_x - shot.left) / shot.scale, (mouse_y - shot.top) / shot.scale
    ImageDraw.Draw(img).ellipse((x - 14, y - 14, x + 14, y + 14), outline=(255, 0, 0), width=3)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _inside(pt, shot: Shot) -> bool:
    return (isinstance(pt, dict) and isinstance(pt.get("x"), (int, float)) and isinstance(pt.get("y"), (int, float))
            and 0 <= pt["x"] < shot.width and 0 <= pt["y"] < shot.height)


def clean_drawing(data: dict, shot: Shot) -> dict:
    """Keep a sensible region and only the marks inside it; marks become 0..1 fractions of the region."""
    r = data.get("region")
    ok = isinstance(r, dict) and all(isinstance(r.get(k), (int, float)) for k in "xywh")
    if ok:
        x, y = max(0, r["x"]), max(0, r["y"])
        w, h = min(r["w"], shot.width - x), min(r["h"], shot.height - y)
        ok = w >= 40 and h >= 40
    marks = []
    if ok:
        for m in data.get("marks") or []:
            if _inside(m, shot) and x <= m["x"] <= x + w and y <= m["y"] <= y + h:
                marks.append({"fx": (m["x"] - x) / w, "fy": (m["y"] - y) / h,
                              "label": str(m.get("label", ""))[:40], "detail": str(m.get("detail", ""))})
    data["region"] = {"x": x, "y": y, "w": w, "h": h} if ok and marks else None
    data["marks"] = marks[:6] if data["region"] else []
    return data


SYSTEM_PLACE = (
    "This image is an enlarged diagram. For each numbered part below, give the pixel centre of that part "
    "in THIS image, exactly on it (on the box, label or object itself). Reply with ONLY JSON: "
    '{"marks": [{"n": int, "x": int, "y": int}]}'
)


def refine_marks(shot: Shot, data: dict) -> dict:
    """Second, precise pass: place the marks on a sharp, enlarged crop of just the diagram."""
    r, marks = data["region"], data["marks"]
    img = Image.open(io.BytesIO(crop_png(shot, r["x"], r["y"], r["w"], r["h"]))).convert("RGB")
    img.thumbnail((config.SCREENSHOT_WIDTH, config.SCREENSHOT_WIDTH))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    parts = "\n".join(f"{i}. {m['label']} ({m['detail']})" for i, m in enumerate(marks, 1))
    resp = config.client().responses.create(
        model=config.MODEL_SPARK, reasoning=config.REASONING, instructions=SYSTEM_PLACE,
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": parts},
            {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()},
        ]}],
    )
    for p in extract_json(resp.output_text).get("marks", []):
        n, x, y = p.get("n"), p.get("x"), p.get("y")
        if isinstance(n, int) and 1 <= n <= len(marks) and isinstance(x, (int, float)) and isinstance(y, (int, float)) \
                and 0 <= x <= img.width and 0 <= y <= img.height:
            marks[n - 1].update(fx=x / img.width, fy=y / img.height)
    return data


def answer(question: str, shot: Shot, mouse: tuple[int, int], user_lang: str = "en", draw: bool = False) -> dict:
    """Ask Muse Spark. Returns {"answer", "point" (screenshot px or None)}; with draw=True also
    {"region": box in screenshot px or None, "marks": [{fx, fy, label, detail}]}."""
    system = SYSTEM_DRAW if draw else SYSTEM
    resp = config.client().responses.create(
        model=config.MODEL_SPARK, reasoning=config.REASONING,
        instructions=system.replace("{lang}", LANG_NAME.get(user_lang, LANG_NAME["en"])),
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": question},
            {"type": "input_image", "image_url": mark_pointer(shot, *mouse)},
        ]}],
    )
    try:
        data = extract_json(resp.output_text)
    except ValueError:  # plain text answer: still useful
        return {"answer": (resp.output_text or "").strip(), "point": None, "region": None, "marks": []}
    pt = data.get("point")
    data["point"] = pt if _inside(pt, shot) else None  # models sometimes point off-screen
    if not draw:
        return {**data, "region": None, "marks": []}
    data = clean_drawing(data, shot)
    if data["region"] and shot.full is not None:
        try:
            data = refine_marks(shot, data)
        except Exception as e:  # noqa: BLE001 - first-pass marks are still good enough to show
            print(f"[talk] refine failed: {e}")
    return data
