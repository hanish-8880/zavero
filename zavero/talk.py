"""Quick answers about the screen: "what is this?", "what does this error mean?", "ee button enti?".

One Muse Spark call with the screenshot (mouse pointer marked) instead of the step-by-step agent,
so the answer comes in a few seconds. The model can also point at what it is talking about.
"""
import base64
import io
import re

from PIL import Image, ImageDraw

from zavero import config, highlight
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
    "pointer, usually on or near it). You will teach it step by step by drawing on an enlarged copy, like a "
    "teacher with coloured pens. Reply with ONLY one JSON object:\n"
    '{"answer": str, "region": {"x": int, "y": int, "w": int, "h": int}, "steps": [{"shape": "circle" | '
    '"path" | "arrow", "color": "red" | "blue" | "green" | "orange" | "purple", "points": [[x, y], ...], '
    '"look": str, "label": str, "detail": str}]}\n'
    "- look: 1-3 plain English words for how the thing you draw on LOOKS in the picture (colour + shape), "
    "e.g. 'blue tube', 'red tube', 'pink box', 'arrow', 'circle', 'yellow box'. Never a subject word.\n"
    "- region: box around the whole diagram in screenshot pixels, with a little margin. Not the whole screen.\n"
    "- steps: 2 to 6, in the order a teacher would explain. circle = ring around one part (points = [centre]). "
    "path = trace along a line, vessel, pipe, wire or route (points = 2 to 8 points exactly along it, in the "
    "direction things flow). arrow = show movement from one part to another (points = [from, to]). "
    "For flow inside a tube, vessel, pipe or wire, use path (traced along it), not arrow. "
    "All points in screenshot pixels.\n"
    "- Use colours with meaning, like a textbook: heart and blood: blue = blood without oxygen, red = blood "
    "with oxygen; circuits: red = +, blue = -. Name the colour in the detail, e.g. 'This blue vessel brings ...'.\n"
    "- label: 1-4 words. detail: one short simple sentence on what it is and where it goes next.\n"
    "- answer: one short sentence: what the whole diagram shows.\n"
    "- If there is no diagram, return region null and steps [] and answer the question in 'answer'.\n"
    "- Language of answer, label and detail: {lang}. Keep technical words as on screen, explained simply."
)
SHAPES = ("circle", "path", "arrow")
COLORS = ("red", "blue", "green", "orange", "purple")


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


def _pairs(points) -> list[tuple[float, float]]:
    """[[x, y], ...] or [{"x":, "y":}, ...] -> [(x, y), ...], dropping anything malformed."""
    out = []
    for p in points or []:
        if isinstance(p, dict):
            p = (p.get("x"), p.get("y"))
        if isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(v, (int, float)) for v in p):
            out.append((float(p[0]), float(p[1])))
    return out


def clean_drawing(data: dict, shot: Shot) -> dict:
    """Keep a sensible region and valid steps; step points become 0..1 fractions of the region.

    Each step: {"shape", "color", "label", "detail", "pts": [(fx, fy), ...], "fr": circle radius / region width}."""
    r = data.get("region")
    ok = isinstance(r, dict) and all(isinstance(r.get(k), (int, float)) for k in "xywh")
    if ok:
        x, y = max(0, r["x"]), max(0, r["y"])
        w, h = min(r["w"], shot.width - x), min(r["h"], shot.height - y)
        ok = w >= 40 and h >= 40
    steps = []
    if ok:
        for s in data.get("steps") or []:
            pts = [(min(max((px - x) / w, 0.0), 1.0), min(max((py - y) / h, 0.0), 1.0)) for px, py in _pairs(s.get("points"))]
            shape = s.get("shape") if s.get("shape") in SHAPES else "circle"
            if not pts:
                continue
            if shape != "circle" and len(pts) < 2:
                shape = "circle"
            steps.append({"shape": shape, "color": s.get("color") if s.get("color") in COLORS else "red",
                          "look": str(s.get("look", ""))[:30].lower(),
                          "label": str(s.get("label", ""))[:40], "detail": str(s.get("detail", "")),
                          "pts": pts if shape != "circle" else pts[:1], "fr": 0.07})
    data["region"] = {"x": x, "y": y, "w": w, "h": h} if ok and steps else None
    data["steps"] = steps[:6] if data["region"] else []
    return data


SYSTEM_PLACE = (
    "This image is an enlarged diagram. For each numbered drawing step below, give its exact position in THIS "
    "image's pixels. circle: points = [centre of the part], r = radius that just encloses it. path: 2 to 8 "
    "points exactly on the line / vessel / route, in the direction things flow. arrow: points = [from, to] on "
    "the two parts. Reply with ONLY JSON: "
    '{"steps": [{"n": int, "points": [[x, y], ...], "r": int}]}'
)


def region_image(shot: Shot, data: dict) -> Image.Image:
    """Sharp crop of just the diagram, at most 1280 px."""
    r = data["region"]
    img = Image.open(io.BytesIO(crop_png(shot, r["x"], r["y"], r["w"], r["h"]))).convert("RGB")
    img.thumbnail((config.SCREENSHOT_WIDTH, config.SCREENSHOT_WIDTH))
    return img


def refine_steps(img: Image.Image, data: dict) -> dict:
    """Fallback precise pass (when SAM finds nothing): Spark places every stroke on the enlarged crop."""
    steps = data["steps"]
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    todo = "\n".join(f"{i}. {s['shape']} ({s['color']}): {s['label']} - {s['detail']}" for i, s in enumerate(steps, 1))
    resp = config.client().responses.create(
        model=config.MODEL_SPARK, reasoning=config.REASONING, instructions=SYSTEM_PLACE,
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": todo},
            {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()},
        ]}],
    )
    for p in extract_json(resp.output_text).get("steps", []):
        n = p.get("n")
        if not (isinstance(n, int) and 1 <= n <= len(steps)):
            continue
        s = steps[n - 1]
        pts = [(px / img.width, py / img.height) for px, py in _pairs(p.get("points"))
               if 0 <= px <= img.width and 0 <= py <= img.height]
        if s["shape"] == "circle" and pts:
            s["pts"] = pts[:1]
            if isinstance(p.get("r"), (int, float)) and 4 <= p["r"] <= img.width / 2:
                s["fr"] = p["r"] / img.width
        elif s["shape"] != "circle" and len(pts) >= 2:
            s["pts"] = pts
    return data


def answer(question: str, shot: Shot, mouse: tuple[int, int], user_lang: str = "en", draw: bool = False) -> dict:
    """Ask Muse Spark. Returns {"answer", "point" (screenshot px or None)}; with draw=True also
    {"region": box in screenshot px or None, "steps": [{shape, color, label, detail, pts, fr}]}."""
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
        return {"answer": (resp.output_text or "").strip(), "point": None, "region": None, "steps": []}
    pt = data.get("point")
    data["point"] = pt if _inside(pt, shot) else None  # models sometimes point off-screen
    if not draw:
        return {**data, "region": None, "steps": []}
    data = clean_drawing(data, shot)
    if data["region"] and shot.full is not None:
        try:
            img = region_image(shot, data)
            data["snapped"] = highlight.snap(data["steps"], img)  # SAM 3.1: exact shapes
            if not data["snapped"]:
                data = refine_steps(img, data)
        except Exception as e:  # noqa: BLE001 - first-pass strokes are still good enough to show
            print(f"[talk] precise placement failed: {e}")
    return data
