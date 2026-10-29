"""SAM 3.1 precision: snap Zavero's pen strokes onto the real shapes in a diagram.

Muse Spark plans each stroke ("trace the blue tube, roughly here"). SAM 3.1 returns the exact
outline of every "blue tube" in the image; we pick the one nearest to Spark's rough points and
draw along its middle (paths) or around it (circles). SAM understands looks ("blue tube",
"pink box", "arrow") much better than subject words ("aorta"), so Spark gives a `look` for each step.
"""
import base64
import io
import math
import re
from concurrent.futures import ThreadPoolExecutor

from meta_sam_parser import SegmentationMask, decode_mask_to_raster
from PIL import Image

from zavero import config

_RECORD = re.compile(r"<\|box;([^|]*)\|><\|mask;([^|]*)\|>")


def _fields(body: str) -> dict:
    return dict(kv.split("=", 1) for kv in body.split(";") if "=" in kv)


def segment(img: Image.Image, prompt: str) -> list[dict]:
    """Every match of `prompt` in img: [{"box": (x1, y1, x2, y2), "pts": [(x, y), ...] mask pixels (sampled)}]."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=90)
    resp = config.client().responses.create(
        model=config.MODEL_SAM,
        input=[{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()},
        ]}],
    )
    out = []
    for box_body, mask_body in _RECORD.findall(resp.output_text or ""):
        b, m = _fields(box_body), _fields(mask_body)
        x1, y1, x2, y2 = (int(b[k]) for k in ("x1", "y1", "x2", "y2"))
        mh, mw, payload = m["data"].split(",", 2)
        mw, mh = int(mw), int(mh)
        raster = decode_mask_to_raster(SegmentationMask(
            "lossless" if payload.startswith("~") else "one_bit", payload, mw, mh))
        sx, sy = (x2 - x1 + 1) / mw, (y2 - y1 + 1) / mh  # the mask raster covers exactly the box
        step = max(1, int(math.sqrt(mw * mh / 1500)))  # ~1500 sample points is plenty
        pts = [(x1 + (mx + 0.5) * sx, y1 + (my + 0.5) * sy)
               for my in range(0, mh, step) for mx in range(0, mw, step) if raster[my * mw + mx]]
        if pts:
            out.append({"box": (x1, y1, x2, y2), "pts": pts})
    return out


def _nearest(objs: list[dict], guess: list[tuple[float, float]]) -> dict | None:
    """The match closest to Spark's rough points (average distance to its nearest mask pixels)."""
    def score(o):
        sample = o["pts"][:: max(1, len(o["pts"]) // 300)]
        return sum(min(math.dist(g, p) for p in sample) for g in guess) / len(guess)
    return min(objs, key=score) if objs else None


def centerline(pts: list[tuple[float, float]], n: int = 8) -> list[tuple[float, float]]:
    """Points along the middle of a long shape: slice it along its main direction, take each slice's centre."""
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    sxx = sum((p[0] - cx) ** 2 for p in pts)
    syy = sum((p[1] - cy) ** 2 for p in pts)
    sxy = sum((p[0] - cx) * (p[1] - cy) for p in pts)
    ang = 0.5 * math.atan2(2 * sxy, sxx - syy)  # main axis (PCA)
    ux, uy = math.cos(ang), math.sin(ang)
    proj = [((p[0] - cx) * ux + (p[1] - cy) * uy, p) for p in pts]
    lo, hi = min(t for t, _ in proj), max(t for t, _ in proj)
    bins: list[list] = [[] for _ in range(n)]
    for t, p in proj:
        bins[min(n - 1, int((t - lo) / (hi - lo + 1e-9) * n))].append(p)
    return [(sum(p[0] for p in b) / len(b), sum(p[1] for p in b) / len(b)) for b in bins if b]


def snap(steps: list[dict], img: Image.Image) -> int:
    """Move each step's points (0..1 fractions of img) onto SAM's exact shape. Returns how many snapped."""
    w, h = img.size
    looks = sorted({s["look"] for s in steps if s.get("look")})
    with ThreadPoolExecutor(max_workers=6) as ex:
        found = dict(zip(looks, ex.map(lambda q: _safe_segment(img, q), looks)))
    snapped = 0
    for s in steps:
        objs = found.get(s.get("look"), [])
        guess = [(fx * w, fy * h) for fx, fy in s["pts"]]
        if not objs or s["shape"] not in ("circle", "path", "arrow"):
            continue  # lines, polygons and text are drawn where Spark put them
        o = _nearest(objs, guess)
        x1, y1, x2, y2 = o["box"]
        if s["shape"] == "circle":
            cx = sum(p[0] for p in o["pts"]) / len(o["pts"])
            cy = sum(p[1] for p in o["pts"]) / len(o["pts"])
            s["pts"] = [(cx / w, cy / h)]
            s["fr"] = min(0.45, 0.55 * max(x2 - x1, y2 - y1) / w)
        else:  # path or arrow: draw along the middle of the real shape, in Spark's direction
            line = centerline(o["pts"], n=8 if s["shape"] == "path" else 3)
            if len(line) < 2:
                continue
            if _length(line) < 0.5 * _length(guess):
                continue  # SAM found only a small piece (e.g. one branch tip): Spark's longer stroke is better
            if math.dist(guess[0], line[-1]) < math.dist(guess[0], line[0]):
                line.reverse()  # keep Spark's direction of flow
            s["pts"] = [(x / w, y / h) for x, y in line]
        snapped += 1
    return snapped


def _length(line: list[tuple[float, float]]) -> float:
    return sum(math.dist(a, b) for a, b in zip(line, line[1:]))


def _safe_segment(img: Image.Image, prompt: str) -> list[dict]:
    try:
        return segment(img, prompt)
    except Exception as e:  # noqa: BLE001 - SAM is an enhancer; Spark's points still work without it
        print(f"[highlight] SAM failed for {prompt!r}: {e}")
        return []
