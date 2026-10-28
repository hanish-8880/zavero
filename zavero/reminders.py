"""Reminders and important dates: "remind me at 5 pm to pay the bill", "Nov 12 amma birthday".

Muse Spark turns the spoken sentence into a time + repeat + bubble texts in the user's language.
Reminders are kept in data/reminders.json (local only). main.py checks for due ones every few seconds.
"""
import json
import re
import threading
import uuid
from datetime import datetime, timedelta

from zavero import config

# Any of these (as a substring) means the user is talking about a reminder, not a screen task.
TRIGGERS = [
    "remind", "reminder", "alarm", "don't forget", "dont forget", "birthday", "anniversary",
    "gurthu", "gurtu", "గుర్తు", "రిమైండ్", "పుట్టినరోజు", "పుట్టిన రోజు", "puttina roju", "pelli roju", "పెళ్లి రోజు",
    "yaad", "याद", "रिमाइंड", "जन्मदिन", "janamdin", "janmdin", "salgirah", "सालगिरह",
]

FILE = config.ROOT / "data" / "reminders.json"
TIME_FMT = "%Y-%m-%dT%H:%M"

SYSTEM = (
    "You turn what a user said into a reminder for Zavero, a friendly helper for beginner computer users in India. "
    "Reply with ONLY one JSON object, no other text:\n"
    '{"action": "add" | "list" | "none", "title": str, "when": "YYYY-MM-DDTHH:MM", '
    '"repeat": "none" | "daily" | "weekly" | "yearly", "confirm": str, "alert": str}\n'
    "Rules:\n"
    "- action add: a new reminder or an important date. list: the user asks what reminders they have. "
    "none: you cannot tell what or when.\n"
    "- when: local time, always in the future. A time with no date = the next time it happens. "
    "A date with no time = 09:00 that day. 'in 10 minutes' = now + 10 minutes. "
    "morning 09:00, afternoon 14:00, evening 18:00, night 21:00.\n"
    "- Birthdays and anniversaries repeat yearly. 'every day' = daily, 'every Monday' = weekly.\n"
    "- title: 2 to 6 words, what to remember.\n"
    "- confirm: one short friendly sentence saying you will remind them and when "
    "(say the day and time in words, e.g. 'today at 5 PM').\n"
    "- alert: the short message to show at that time, starting with ⏰ (🎂 for a birthday). "
    "For a birthday or anniversary, say whose it is today.\n"
    "- Language of confirm and alert: same as the user. Telugu words in any script -> Telugu script. "
    "Devanagari Hindi -> Devanagari. Hinglish -> simple romanized Hinglish. English -> simple English. "
    "Very simple words, max 2 short sentences each."
)


def is_reminder(text: str) -> bool:
    """True if the user is asking for a reminder or telling an important date."""
    t = (text or "").lower()
    return any(w in t for w in TRIGGERS)


def _json(text: str) -> dict:
    """First {...} object in the model reply."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError(f"no JSON in reply: {text!r}")
    return json.loads(m.group(0))


def parse(text: str, now: datetime | None = None) -> dict:
    """Ask Muse Spark what the user wants. Returns the JSON dict described in SYSTEM."""
    now = now or datetime.now()
    prompt = f"Now: {now:%A %Y-%m-%d %H:%M} (local time)\nUser said: {text}"
    resp = config.client().responses.create(model=config.MODEL_SPARK, instructions=SYSTEM, input=prompt)
    data = _json(resp.output_text)
    if data.get("action") == "add":
        datetime.strptime(data["when"], TIME_FMT)  # raises if the model got the format wrong
    return data


def next_time(when: datetime, repeat: str, now: datetime) -> datetime | None:
    """The next time a repeating reminder fires after `now` (None if it does not repeat)."""
    if repeat == "daily":
        step = lambda d: d + timedelta(days=1)  # noqa: E731
    elif repeat == "weekly":
        step = lambda d: d + timedelta(days=7)  # noqa: E731
    elif repeat == "yearly":
        def step(d: datetime) -> datetime:
            try:
                return d.replace(year=d.year + 1)
            except ValueError:  # Feb 29 -> Feb 28 in normal years
                return d.replace(year=d.year + 1, day=28)
    else:
        return None
    while when <= now:
        when = step(when)
    return when


class Reminders:
    """The saved reminders. Safe to use from the voice thread and the Qt timer at the same time."""

    def __init__(self, path=FILE) -> None:
        self.path = path
        self._lock = threading.Lock()
        try:
            self.items: list[dict] = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            self.items = []

    def _save(self) -> None:
        self.path.parent.mkdir(exist_ok=True)
        self.path.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, title: str, when: str, repeat: str = "none", alert: str = "") -> dict:
        item = {"id": uuid.uuid4().hex[:8], "title": title, "when": when, "repeat": repeat or "none",
                "alert": alert or f"⏰ {title}"}
        with self._lock:
            self.items.append(item)
            self._save()
        return item

    def due(self, now: datetime | None = None) -> list[dict]:
        """Reminders whose time has come. One-time ones are removed; repeating ones move to the next time."""
        now = now or datetime.now()
        fired = []
        with self._lock:
            keep = []
            for it in self.items:
                when = datetime.strptime(it["when"], TIME_FMT)
                if when > now:
                    keep.append(it)
                    continue
                fired.append({**it, "late_min": int((now - when).total_seconds() // 60)})
                nxt = next_time(when, it.get("repeat", "none"), now)
                if nxt:
                    keep.append({**it, "when": nxt.strftime(TIME_FMT)})
            if fired:
                self.items = keep
                self._save()
        return fired

    def upcoming(self, n: int = 5) -> list[dict]:
        with self._lock:
            return sorted(self.items, key=lambda it: it["when"])[:n]


def pretty(when: str) -> str:
    """'2026-11-12T09:00' -> 'Thu 12 Nov, 9:00 AM'."""
    d = datetime.strptime(when, TIME_FMT)
    return d.strftime("%a %d %b, %I:%M %p").replace(" 0", " ")
