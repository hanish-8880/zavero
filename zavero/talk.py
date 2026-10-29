"""Quick answers about the screen: "what is this?", "what does this error mean?", "ee button enti?".

One Muse Spark call with the screenshot (mouse pointer marked) instead of the step-by-step agent,
so the answer comes in a few seconds. The model can also point at what it is talking about.
"""
import base64
import io
import math
import re

from PIL import Image, ImageDraw

from zavero import config, highlight
from zavero.narrator import SEED, STYLE
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
# Code / app errors: explain them and, in VS Code, jump to the broken line.
ERROR = [r"\berror", r"\beror", r"\btraceback", r"\bexception", r"\bbug\b", r"\bcrash", r"\bfail(ed|ing|s)?\b",
         r"not working", r"\bwrong\b", r"\bpani cheyyatledu", r"\bkaam nahi", r"ఎర్రర్", r"एरर", r"गलती"]
# A picture on screen the user wants explained: Zavero enlarges it and draws numbered marks on it.
DIAGRAM = [r"diagram", r"\bchart", r"\bgraph", r"\bfigure", r"flow ?chart", r"\bpicture", r"\bimage\b",
           r"\bdrawing", r"\bmap\b", r"\bequation", r"\bformula", r"\bslide\b", r"\bboard\b",
           r"డయాగ్రామ్", r"చిత్రం", r"బొమ్మ", r"आरेख", r"चित्र", r"डायग्राम", r"\bbomma\b", r"\bchitra"]
# "Draw it for me": always the drawing board (never open Paint), on the diagram or on a blank whiteboard.
DRAW_ASK = [r"\bdraw", r"\bsketch", r"\bgee(yi|yu|si|sthu|stha)", r"గీ(యి|సి|యండి|స్తా)", r"బొమ్మ (వేయి|వేసి|గీ)",
            r"\bbomma (veyi|vesi|gee)", r"bana ?(ke|kar|o) ?(dikha|samjha|batao)", r"बना ?(के|कर) ?(दिखा|समझा)",
            r"खींच", r"\bkheench"]
EXPLAIN = [r"\bexplain", r"\bdraw\b", r"\bunderstand", r"\bdoubt", r"\bwhat\b", r"\bmean", r"\bshow\b",
           r"\benti\b", r"\bardam", r"\bartham", r"vivarinch", r"ఏంటి", r"అర్థం", r"వివరించ",
           r"\bkya\b", r"samjha", r"samajh", r"क्या", r"समझा", r"समझ"]
# These turn a question into a task ("how do I pay" -> guide them through it).
TASK = [r"\bhow (do|can|to)\b", r"\bopen\b", r"\bela\b", r"\bkaise\b", r"\bkaro\b", r"\bchey", r"कैसे", r"ఎలా"]

SYSTEM = (
    "You are Zavero, a patient helper for a beginner computer user in India. The user asked a question about "
    "their screen. The red circle marks their mouse pointer: 'this' or 'here' usually means the thing under or "
    "next to it. Reply with ONLY one JSON object:\n"
    '{"answer": str, "point": {"x": int, "y": int} | null, "label": str}\n'
    "- answer: max 3 short, simple sentences. Say what it is, what it does / what the error means, and what "
    "they can do next. No jargon; explain any technical word in plain words. If it looks like a scam, phishing "
    "or a risky download, say so clearly. Keep on-screen labels in English in **bold**.\n"
    "- point: screenshot pixel centre of the thing you are talking about, or null.\n"
    "- label: 1-3 words naming the thing you point at (its on-screen English text if it has one), or \"\".\n"
    "- Language of answer: {lang}."
)
SYSTEM_ERROR = (
    "You are Zavero, a patient coding teacher for a beginner in India. The user has an error on their screen "
    "(terminal traceback, red underline, Problems panel, browser console, or an app's error box). Read it "
    "carefully. Reply with ONLY one JSON object:\n"
    '{"answer": str, "point": {"x": int, "y": int} | null, "goto": {"file": str, "line": int} | null}\n'
    "- answer: max 4 short, simple sentences: what the error means in plain words, the likely cause, and the "
    "exact fix (put small code in `backticks`). Explain any technical word.\n"
    "- goto: ONLY if the error names a file and line from the user's own project and a code editor like "
    "VS Code is open: file = just the file name as written (e.g. 'main.py'), line = the line number. "
    "For library files deep inside site-packages / node_modules, use the user's own file further up the "
    "traceback. Else null.\n"
    "- point: screenshot pixel centre of the error message on screen, or null.\n"
    "- Language of answer: {lang}. Keep code, file names and error names in English."
)
SYSTEM_LINE = (
    "You are Zavero, a patient coding teacher. The editor now shows {file} at line {line}, where this error "
    "happens: {error}\nReply with ONLY one JSON object: "
    '{"answer": str, "point": {"x": int, "y": int} | null}\n'
    "- point: screenshot pixel centre of line {line}'s code in the editor (the highlighted line).\n"
    "- answer: max 3 short, simple sentences: what is wrong on THIS line and exactly how to change it "
    "(show the fixed code in `backticks`). Language: {lang}. Keep code in English."
)
LANG_NAME = {"te": "Telugu (Telugu script)", "hi": "Hindi (Devanagari)", "en": "simple English"}


SYSTEM_DRAW = (
    "You are Zavero, a patient teacher for a beginner in India. The user wants you to explain something by "
    "drawing, step by step, like a teacher with coloured pens. Choose ONE mode:\n"
    "A) annotate: a diagram, chart, slide or picture on their screen (often a paused YouTube video) is what "
    "they ask about (the red circle is their mouse pointer, usually on or near it). Draw on an enlarged copy.\n"
    "B) sketch: they want a NEW drawing ('draw me a triangle', 'draw another one', 'show me how it works'), or "
    "nothing on screen fits. Draw from scratch on a blank whiteboard 1000 wide x 700 tall.\n"
    "Reply with ONLY one JSON object:\n"
    '{"answer": str, "mode": "annotate" | "sketch", "region": {"x": int, "y": int, "w": int, "h": int} | null, '
    '"steps": [{"shape": "circle" | "ellipse" | "path" | "arrow" | "line" | "polygon" | "rect" | "text", '
    '"color": "red" | "blue" | "green" | "orange" | "purple", "points": [[x, y], ...], "r": int, '
    '"fill": bool, "text": str, "look": str, "label": str, "detail": str}]}\n'
    "- Draw like a clear 2D textbook diagram, not just lines: every object or part is a CLOSED shape "
    "(polygon / rect / circle / ellipse) with fill true, so it shows as a soft coloured area with an outline; "
    "lines and arrows only connect parts or show flow; label each part with a short text step next to it.\n"
    "- annotate (marks are drawn right on top of their diagram): give EACH part you explain its own circle "
    "(fill false, centre on the part, r just big enough to enclose it: a resistor, a battery, a valve, a room); "
    "trace wires, pipes and flow with path in the direction things move; use arrow for cause -> effect "
    "between two parts. Explain every important part, one step each.\n"
    "- annotate: region = box around the diagram in screenshot pixels (little margin, not the whole screen); "
    "points in screenshot pixels. look = 1-3 plain English words for how the thing LOOKS (colour + shape), "
    "e.g. 'blue tube', 'pink box', 'arrow'. Never a subject word.\n"
    "- sketch: region null, look empty; points in whiteboard units (x 0-1000, y 0-700). Make clean, correct, "
    "well-proportioned figures that fill the board with margin 60 (e.g. a right triangle with a, b, c labels "
    "and a small square in the right-angle corner). Build the figure up stroke by stroke.\n"
    "- shapes: circle = ring (points = [centre], r = radius). path = trace along a line / vessel / route in the "
    "direction things flow (2-8 points, gets an arrowhead). arrow = movement from one part to another "
    "([from, to]). line = plain line or curve, no arrowhead (2-8 points). polygon = closed shape through its "
    "corners. rect = [top-left, bottom-right]. ellipse = oval inside [top-left, bottom-right]. text = write `text` (a few characters like 'a', 'c = 5', "
    "'90°') with its centre at points[0]. For flow inside a tube or wire use path, not arrow.\n"
    "- steps: 2-8 for annotate, 4-12 for sketch (shapes first, then their labels), in teaching order.\n"
    "- Use colours with meaning (blood: blue = without oxygen, red = with oxygen; circuits: red +, blue -; "
    "maths: one colour per side or idea). Name the colour in the detail, e.g. 'This blue side a ...'.\n"
    "- label: 1-4 words. detail: one short simple sentence: what this stroke shows and how it connects to the next.\n"
    "- answer: one short sentence: what the whole drawing shows.\n"
    "- Language of answer, label and detail: {lang}. Keep maths symbols and technical words as usual."
)
SHAPES = ("circle", "ellipse", "path", "arrow", "line", "polygon", "rect", "text")
CLOSED = ("circle", "ellipse", "polygon")  # shapes that can be filled
BOARD_W, BOARD_H = 1000, 700  # whiteboard units for sketches
COLORS = ("red", "blue", "green", "orange", "purple")


SYSTEM_3D = (
    "You are Zavero, a patient teacher for a beginner in India. Explain the user's topic with a small 3D model "
    "built from simple shapes, revealed step by step like a teacher building it on the table.\n"
    "Reply with ONLY one JSON object:\n"
    '{"title": str, "answer": str, "parts": [{"shape": "sphere" | "box" | "cylinder" | "cone" | "torus" | "tube", '
    '"pos": [x, y, z], "size": [a, b, c], "rotation": [rx, ry, rz], "points": [[x, y, z], ...], '
    '"color": "#rrggbb", "label": str, "detail": str, "step": int, "cut": bool, "opacity": number}]}\n'
    "- Units: the model fits inside -3..3 on every axis, centred at 0, y is up. rotation in degrees.\n"
    "- size: sphere [radius], box [width, height, depth], cylinder [radius, height], cone [radius, height], "
    "torus [ring radius, tube radius]; tube = a pipe along 2-10 points (vessels, wires, roots), size [radius].\n"
    "- Build a recognisable, well-proportioned model (6-20 parts): bigger shapes first, then details. Overlap "
    "shapes to form one object (e.g. ventricles = two spheres, arteries = tubes leaving the top).\n"
    "- cut: true for an outer shell that should be shown half-open so the inside is visible (Earth's crust, "
    "a cell membrane, heart wall). opacity 0.25-1 (default 1) for see-through shells.\n"
    "- Realistic, meaningful colours (oxygen-rich blood red, oxygen-poor blue, core orange...).\n"
    "- step: 1..8, teaching order; parts of one idea share a step. label: 1-4 words on the part (only on the "
    "main part of each step). detail: one short simple sentence for that step: what it is and what it does.\n"
    "- answer: one short sentence about the whole model. Language of title, answer, label, detail: {lang}."
)
SHAPES_3D = ("sphere", "box", "cylinder", "cone", "torus", "tube")
_NAMED = {"red": "#e53935", "blue": "#1e66f5", "green": "#1f9d55", "orange": "#f59e0b", "purple": "#8e44ad",
          "pink": "#ec4899", "yellow": "#facc15", "brown": "#8d5524", "grey": "#94a3b8", "gray": "#94a3b8",
          "white": "#f8fafc", "black": "#1f2937"}


def _nums(v, n: int, lo: float, hi: float, default: float) -> list[float]:
    out = []
    for i in range(n):
        try:
            x = float(v[i])
        except (TypeError, ValueError, IndexError, KeyError):
            x = default
        out.append(min(max(x, lo), hi) if math.isfinite(x) else default)
    return out


def clean_scene(data: dict) -> dict:
    """Validate the 3D scene: known shapes, every number clamped, colours as #rrggbb, steps renumbered 1..N.
    Returns {"title", "answer", "parts", "steps": [{"n", "label", "detail"}]}."""
    parts = []
    for p in (data.get("parts") or [])[:24]:
        if not isinstance(p, dict):
            continue
        shape = p.get("shape") if p.get("shape") in SHAPES_3D else "sphere"
        color = str(p.get("color") or "").strip().lower()
        color = color if re.fullmatch(r"#[0-9a-f]{6}", color) else _NAMED.get(color, "#e57373")
        pts = [_nums(q, 3, -4, 4, 0) for q in (p.get("points") or [])[:10] if isinstance(q, (list, tuple))]
        if shape == "tube" and len(pts) < 2:
            shape = "cylinder"
        try:
            step = max(1, min(int(p.get("step", 1)), 8))
        except (TypeError, ValueError):
            step = 1
        try:
            opacity = min(max(float(p.get("opacity", 1)), 0.2), 1.0)
        except (TypeError, ValueError):
            opacity = 1.0
        parts.append({"shape": shape, "pos": _nums(p.get("pos"), 3, -4, 4, 0),
                      "size": _nums(p.get("size"), 3, 0.02, 4, 0.5), "rotation": _nums(p.get("rotation"), 3, -360, 360, 0),
                      "points": pts if shape == "tube" else [], "color": color, "opacity": opacity,
                      "label": str(p.get("label") or "")[:40], "detail": str(p.get("detail") or "")[:240],
                      "step": step, "cut": bool(p.get("cut"))})
    order = sorted({p["step"] for p in parts})
    renum = {s: i + 1 for i, s in enumerate(order)}  # no gaps: 1, 2, 3...
    steps = []
    for p in parts:
        p["step"] = renum[p["step"]]
    for n in range(1, len(order) + 1):
        main = next((p for p in parts if p["step"] == n and p["label"]), None) or next(p for p in parts if p["step"] == n)
        steps.append({"n": n, "label": main["label"], "detail": main["detail"]})
    return {"title": str(data.get("title") or "")[:60], "answer": str(data.get("answer") or "").strip(),
            "parts": parts, "steps": steps}


def answer_3d(question: str, user_lang: str = "en") -> dict:
    """Ask Muse Spark for a 3D teaching model of the topic (no screenshot needed)."""
    resp = config.client().responses.create(
        model=config.MODEL_SPARK, reasoning=config.REASONING,
        instructions=SYSTEM_3D.replace("{lang}", LANG_NAME.get(user_lang, LANG_NAME["en"])), input=question)
    scene = clean_scene(extract_json(resp.output_text))
    if not scene["parts"]:
        raise ValueError("empty 3D scene")
    return scene


SYSTEM_CIRCLE = (
    "You are Zavero, a patient teacher for a beginner in India. While asking, the user drew a loop with their "
    "mouse around one part of their screen (the red loop in the first image; the second image is a sharp "
    "close-up of what is inside it). {context}They want THAT part explained. Reply with ONLY JSON: "
    '{"answer": str, "label": str}\n'
    "- answer: max 4 short, simple sentences: what the circled part is, what it does / means, and how it "
    "connects to the rest of the diagram or screen. No jargon. If their words ask something specific, answer that.\n"
    "- label: 1-4 words naming the circled part.\n- Language: {lang}. Keep on-screen labels in English in **bold**."
)
MIN_LOOP = 30  # real px: smaller wiggles are not a circle


def circled_region(points: list[tuple[float, float]]) -> tuple[int, int, int, int] | None:
    """If the mouse path is a loop around something, its bounding box (x, y, w, h) in the same px; else None.
    A loop: big enough, ends near where it started (or crosses itself), and encloses real area."""
    if len(points) < 8:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    if w < MIN_LOOP or h < MIN_LOOP:
        return None
    diag = math.hypot(w, h)
    length = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
    closed = math.dist(points[0], points[-1]) < 0.45 * diag or any(
        math.dist(points[-1], q) < 0.12 * diag for q in points[: len(points) // 2])
    area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2
    if not closed or length < 2.2 * max(w, h) or area < 0.3 * w * h:
        return None
    return round(min(xs)), round(min(ys)), round(w), round(h)


def mark_loop(shot: Shot, loop: list[tuple[float, float]]) -> str:
    """Screenshot data URL with the user's loop drawn in red (loop in screenshot px)."""
    raw = base64.b64decode(shot.data_url.split(",", 1)[1])
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    ImageDraw.Draw(img).line(loop + loop[:1], fill=(255, 0, 0), width=4, joint="curve")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def answer_circle(question: str, shot: Shot, loop: list[tuple[float, float]], context: str = "",
                  user_lang: str = "en") -> dict:
    """Explain the part the user circled. loop in screenshot px. Returns {"answer", "label"}."""
    xs, ys = [p[0] for p in loop], [p[1] for p in loop]
    pad = 18
    x0, y0 = max(0, min(xs) - pad), max(0, min(ys) - pad)
    w, h = min(shot.width - x0, max(xs) - min(xs) + 2 * pad), min(shot.height - y0, max(ys) - min(ys) + 2 * pad)
    content = [{"type": "input_text", "text": question or "What is this part?"},
               {"type": "input_image", "image_url": mark_loop(shot, loop)}]
    if shot.full is not None:  # sharp close-up of the inside of the loop
        img = Image.open(io.BytesIO(crop_png(shot, x0, y0, w, h))).convert("RGB")
        k = min(3.0, 900 / max(img.width, img.height))
        if k > 1.05:
            img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        content.append({"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()})
    ctx = f"Context - what is being explained on screen: {context}\n" if context else ""
    resp = config.client().responses.create(
        model=config.MODEL_SPARK, reasoning=config.REASONING,
        instructions=SYSTEM_CIRCLE.replace("{context}", ctx).replace("{lang}", LANG_NAME.get(user_lang, LANG_NAME["en"])),
        input=[{"role": "user", "content": content}])
    try:
        data = extract_json(resp.output_text)
    except ValueError:
        data = {"answer": (resp.output_text or "").strip(), "label": ""}
    return {"answer": str(data.get("answer") or "").strip(), "label": str(data.get("label") or "")[:30]}


def _has(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def is_diagram(text: str) -> bool:
    """'explain this diagram', 'draw me a triangle', 'ye chart samjhao' -> the drawing board."""
    t = (text or "").lower()
    if re.search(r"\b(paint|canva|photoshop)\b", t):  # they want that app, not Chai's board
        return False
    if _has(DRAW_ASK, t):
        return True
    return _has(DIAGRAM, t) and _has(EXPLAIN, t) and not re.search(r"\b(open|create|make|banana|chey)", t)


THREE_D = [r"\b3 ?d\b", r"\bthree ?d\b", r"త్రీ ?డీ", r"3 ?డీ", r"3 ?डी", r"थ्री ?डी", r"\bin 3 ?dimension",
           r"\brotat(e|ing)\b.{0,30}\b(model|show|see)", r"\binside (of|a|an|the)\b"]


def is_3d(text: str) -> bool:
    """'heart ni 3D lo explain chey', 'show me the earth in 3D', 'inside of an engine' -> the 3D board."""
    t = (text or "").lower()
    if re.search(r"\b(blender|paint ?3d|open|install|download|print)\b", t):  # an app / a task, not Chai's board
        return False
    return _has(THREE_D, t)


def is_error(text: str) -> bool:
    """'ee error enti?', 'why is my code failing', 'fix this error' -> explain + jump to the line."""
    t = (text or "").lower()
    return _has(ERROR, t) and not re.search(r"\b(open|create|make|banana)\b", t)


def is_question(text: str) -> bool:
    t = (text or "").lower()
    return is_diagram(t) or is_error(t) or (_has(QUESTION, t) and not _has(TASK, t))


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


def _step(s: dict, pts: list[tuple[float, float]], fr: float, fill_default: bool = False) -> dict | None:
    """One drawing step with points as 0..1 fractions; None if it can't be drawn."""
    shape = s.get("shape") if s.get("shape") in SHAPES else "circle"
    if not pts:
        return None
    if shape == "text" and not str(s.get("text") or "").strip():
        return None
    if shape == "rect" and len(pts) >= 2:  # two corners -> four
        (x1, y1), (x2, y2) = pts[0], pts[1]
        shape, pts = "polygon", [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    if shape in ("path", "arrow", "line", "polygon", "ellipse") and len(pts) < 2:
        shape = "circle"
    if shape == "ellipse":
        pts = pts[:2]
    if shape in ("circle", "text"):
        pts = pts[:1]
    return {"shape": shape, "color": s.get("color") if s.get("color") in COLORS else "red",
            "look": str(s.get("look", ""))[:30].lower(), "text": str(s.get("text") or "")[:20],
            "label": str(s.get("label", ""))[:40], "detail": str(s.get("detail", "")), "pts": pts, "fr": fr,
            "fill": shape in CLOSED and bool(s.get("fill", fill_default))}


def clean_drawing(data: dict, shot: Shot) -> dict:
    """Validate the drawing. Step points become 0..1 fractions of the region (annotate) or of the
    whiteboard (sketch). Each step: {"shape", "color", "look", "text", "label", "detail", "pts", "fr"}.
    Sets data["sketch"] True for a blank-whiteboard drawing."""
    def frac(v: float) -> float:
        return min(max(v, 0.0), 1.0)

    steps = []
    r = data.get("region")
    if data.get("mode") == "sketch" or not isinstance(r, dict):
        for s in data.get("steps") or []:
            pts = [(frac(px / BOARD_W), frac(py / BOARD_H)) for px, py in _pairs(s.get("points"))]
            rad = s.get("r") if isinstance(s.get("r"), (int, float)) and s["r"] > 0 else 70
            st = _step(s, pts, min(0.45, rad / BOARD_W), fill_default=True)  # sketches: filled 2D shapes
            if st:
                st["look"] = ""
                steps.append(st)
        data["region"], data["sketch"], data["steps"] = None, bool(steps), steps[:12]
        return data

    ok = all(isinstance(r.get(k), (int, float)) for k in "xywh")
    if ok:
        x, y = max(0, r["x"]), max(0, r["y"])
        w, h = min(r["w"], shot.width - x), min(r["h"], shot.height - y)
        ok = w >= 40 and h >= 40
    if ok:
        for s in data.get("steps") or []:
            pts = [(frac((px - x) / w), frac((py - y) / h)) for px, py in _pairs(s.get("points"))]
            st = _step(s, pts, 0.07)
            if st:
                steps.append(st)
    data["region"] = {"x": x, "y": y, "w": w, "h": h} if ok and steps else None
    data["sketch"] = False
    data["steps"] = steps[:8] if data["region"] else []
    return data


def whiteboard_png() -> bytes:
    """A blank whiteboard with a faint grid, for sketches."""
    img = Image.new("RGB", (BOARD_W, BOARD_H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for gx in range(0, BOARD_W, 50):
        d.line((gx, 0, gx, BOARD_H), fill=(238, 242, 247))
    for gy in range(0, BOARD_H, 50):
        d.line((0, gy, BOARD_W, gy), fill=(238, 242, 247))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


SYSTEM_PLACE = (
    "This image is an enlarged diagram. For each numbered drawing step below, give its exact position in THIS "
    "image's pixels. circle: points = [centre of the part], r = radius that just encloses it. path: 2 to 8 "
    "points exactly on the line / vessel / route, in the direction things flow. arrow: points = [from, to] on "
    "the two parts. Reply with ONLY JSON: "
    '{"steps": [{"n": int, "points": [[x, y], ...], "r": int}]}'
)


SYSTEM_ZOOM = (
    "This image is a zoomed-in part of a computer screen. Find the EXACT centre of: {what}. Reply with ONLY "
    'JSON {"found": bool, "x": int, "y": int}: x, y in THIS image\'s pixels; found false if it is not here.'
)
ZOOM_NEAR = (300, 190)  # model px around the guess: a sharp close look (~450x285 real px at 1080p)
ZOOM_WIDE = (640, 380)  # when the thing is not in the close look: a wider look first, then close again


def refine_point(shot: Shot, pt: dict, what: str) -> dict:
    """Second look for precise pointing (first guesses are often 100-300 px off): a sharp, enlarged piece of
    the screen around the guess; if the thing is not in it, a wider piece, then a close look at what that
    found. Returns the better point (screenshot px), or the first guess."""
    if shot.full is None or not pt or not what.strip():
        return pt
    near = _zoom(shot, pt, what, *ZOOM_NEAR)
    if near:
        return near
    wide = _zoom(shot, pt, what, *ZOOM_WIDE)
    if not wide:
        return pt
    return _zoom(shot, wide, what, *ZOOM_NEAR) or wide


def _zoom(shot: Shot, pt: dict, what: str, zw: int, zh: int) -> dict | None:
    """Exact centre of `what` inside a zw x zh (model px) piece around pt, or None if it isn't there."""
    zw, zh = min(zw, shot.width), min(zh, shot.height)
    x0 = min(max(pt["x"] - zw / 2, 0), max(0, shot.width - zw))
    y0 = min(max(pt["y"] - zh / 2, 0), max(0, shot.height - zh))
    img = Image.open(io.BytesIO(crop_png(shot, x0, y0, zw, zh))).convert("RGB")
    k = min(2.0, 1280 / img.width)  # enlarge so small icons and text are clear, at most 1280 px wide
    if k > 1.05:
        img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    try:
        resp = config.client().responses.create(
            model=config.MODEL_SPARK, reasoning=config.REASONING,
            instructions=SYSTEM_ZOOM.replace("{what}", what[:200]),
            input=[{"role": "user", "content": [
                {"type": "input_text", "text": f"Where exactly is: {what[:200]}"},
                {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()},
            ]}],
        )
        data = extract_json(resp.output_text)
    except Exception as e:  # noqa: BLE001 - the first guess is still shown
        print(f"[talk] zoom refine failed: {e}")
        return None
    if not data.get("found") or not all(isinstance(data.get(v), (int, float)) for v in "xy"):
        return None
    if not (0 <= data["x"] < img.width and 0 <= data["y"] < img.height):
        return None
    per_px = img.width / zw  # image px per model px
    return {"x": round(x0 + data["x"] / per_px), "y": round(y0 + data["y"] / per_px)}


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


def _goto(g) -> dict | None:
    """A safe {"file", "line"} to open in the editor, or None."""
    if not isinstance(g, dict) or not isinstance(g.get("line"), int) or g["line"] < 1:
        return None
    name = str(g.get("file") or "").replace("\\", "/").split("/")[-1].strip()
    return {"file": name, "line": g["line"]} if re.fullmatch(r"[\w.\-]{1,80}", name) else None


def explain_line(shot: Shot, file: str, line: int, error: str, user_lang: str = "en") -> dict:
    """After jumping to the line: point at it and say exactly what to change."""
    system = (SYSTEM_LINE.replace("{file}", file).replace("{line}", str(line)).replace("{error}", error)
              .replace("{lang}", LANG_NAME.get(user_lang, LANG_NAME["en"])))
    resp = config.client().responses.create(
        model=config.MODEL_SPARK, reasoning=config.REASONING, instructions=system,
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": f"Explain line {line} of {file}."},
            {"type": "input_image", "image_url": shot.data_url},
        ]}],
    )
    data = extract_json(resp.output_text)
    data["point"] = data.get("point") if _inside(data.get("point"), shot) else None
    return data


def answer(question: str, shot: Shot, mouse: tuple[int, int], user_lang: str = "en", draw: bool = False,
           error: bool = False) -> dict:
    """Ask Muse Spark. Returns {"answer", "point" (screenshot px or None), "goto" (error mode: file + line
    to open, or None)}; with draw=True also {"region": box in screenshot px or None, "steps": [...]}."""
    system = SYSTEM_DRAW if draw else SYSTEM_ERROR if error else SYSTEM
    resp = config.client().responses.create(
        model=config.MODEL_SPARK, reasoning=config.REASONING,
        instructions=system.replace("{lang}", LANG_NAME.get(user_lang, LANG_NAME["en"])) + "\n" + STYLE
        + ("" if draw else " " + SEED),
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": question},
            {"type": "input_image", "image_url": mark_pointer(shot, *mouse)},
        ]}],
    )
    try:
        data = extract_json(resp.output_text)
    except ValueError:  # plain text answer: still useful
        return {"answer": (resp.output_text or "").strip(), "point": None, "goto": None, "region": None, "steps": [], "sketch": False}
    pt = data.get("point")
    data["point"] = pt if _inside(pt, shot) else None  # models sometimes point off-screen
    data["label"] = str(data.get("label") or "").strip()[:30]
    data["goto"] = _goto(data.get("goto")) if error else None
    if not draw:
        if data["point"]:  # zoom in and check, so the arrow lands exactly on it
            data["point"] = refine_point(shot, data["point"], data["label"] or question.split("The user now says:")[-1])
        return {**data, "region": None, "steps": [], "sketch": False}
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
