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


def recent(n: int = 5) -> list[dict]:
    """Last n events (for showing in the overlay / demo)."""
    if not _PATH.exists():
        return []
    lines = _PATH.read_text(encoding="utf-8").splitlines()[-n:]
    return [json.loads(line) for line in lines]
