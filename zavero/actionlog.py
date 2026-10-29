"""Append-only log of everything Zavero does: logs/actions.jsonl."""
import json
import threading
import time

from zavero import config

_PATH = config.LOG_DIR / "actions.jsonl"
_lock = threading.Lock()


def log(event: str, **data) -> None:
    """Write one event with a timestamp."""
    config.LOG_DIR.mkdir(exist_ok=True)
    row = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event, **data}
    with _lock, _PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


FEEDBACK = config.LOG_DIR / "feedback.jsonl"
VERSION = "0.9-hackathon"
# Only words clearly about Zavero itself: "ee site lo problem undi" is a request for help, not a bug report.
FEEDBACK_WORDS = r"report (a )?bug|bug report|send feedback|give feedback|feedback (ivvali|ista|dena|deni)|" \
                 r"zavero (lo|mein|me|ki|ko|is|has)\b.{0,20}(problem|bug|dikkat|samasya|issue)|" \
                 r"zavero (not working|is broken)|జవేరో.{0,15}సమస్య|ज़वेरो.{0,15}(दिक्कत|समस्या)"


def feedback(words: str) -> None:
    """Save a voice bug report with the last 20 actions (never a screenshot) for the developer."""
    config.LOG_DIR.mkdir(exist_ok=True)
    row = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "version": VERSION, "words": words, "recent": recent(20)}
    with _lock, FEEDBACK.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def recent(n: int = 5) -> list[dict]:
    """Last n events (for showing in the overlay / demo)."""
    if not _PATH.exists():
        return []
    lines = _PATH.read_text(encoding="utf-8").splitlines()[-n:]
    return [json.loads(line) for line in lines]
