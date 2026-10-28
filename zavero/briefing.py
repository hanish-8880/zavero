"""'What matters today?': one short, friendly briefing instead of 100 notifications.

Gathers due/upcoming reminders and unread Gmail (if connected), and Muse Spark picks the
three things that matter, in the user's language. Also runs once by itself each morning.
"""
import json
from datetime import date, datetime, timedelta

from zavero import config, reminders

TRIGGERS = [
    "what matters", "what's important", "whats important", "what is important", "what needs my attention",
    "my day", "briefing", "what did i miss", "anything important", "good morning",
    "ivala emi", "ఈరోజు ఏం", "ఈరోజు ఏమి", "ఈ రోజు ఏమి", "emi undi", "ముఖ్యమైన",
    "aaj kya", "आज क्या", "kya zaroori", "क्या ज़रूरी", "क्या जरूरी", "zaroori kya",
]

STATE = config.ROOT / "data" / "state.json"

SYSTEM = (
    "You are Zavero, a warm helper for a beginner computer user in India. Write their briefing for a small "
    "chat bubble. Pick only what really matters (at most 3 points): things due today, people waiting for an "
    "answer, deadlines, bills. Skip ads, newsletters and anything that can wait; if you skipped some, say "
    "in a few words that the rest can wait. If nothing matters, say so happily.\n"
    "Speak to the user directly ('you'). Greet for the actual time of day.\n"
    "Format: one short greeting line, then up to 3 lines starting with '• ', then one short line telling "
    "them to hold **Right Ctrl** if they want help with these. If nothing matters, write only one or two "
    "cheerful lines (no bullets, no help line). Do not offer anything else. "
    "Put names, times and amounts in **bold**. Very simple words.\n"
    "Language: {lang}."
)
LANG_NAME = {"te": "Telugu (Telugu script)", "hi": "Hindi (Devanagari)", "en": "simple English"}


def is_briefing(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in TRIGGERS)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def save_state(**kv) -> None:
    state = {**load_state(), **kv}
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def gather(store: reminders.Reminders, gmail=None, now: datetime | None = None) -> str:
    """Plain-text facts for the model: today's reminders and unread important-looking mail."""
    now = now or datetime.now()
    end = (now + timedelta(days=1)).replace(hour=23, minute=59)
    lines = [f"Now: {now:%A %d %B %Y, %I:%M %p}"]
    soon = [it for it in store.upcoming(20) if datetime.strptime(it["when"], reminders.TIME_FMT) <= end]
    lines.append("Reminders today/tomorrow:" if soon else "Reminders today/tomorrow: none")
    lines += [f"- {reminders.pretty(it['when'])}: {it['title']}" for it in soon]
    if gmail is None:
        lines.append("Email: not connected")
        return "\n".join(lines)
    from zavero.messaging.gmail import QUERY, headers

    res = gmail.users().messages().list(userId="me", q=QUERY.replace("newer_than:2d", "newer_than:1d"),
                                        maxResults=8).execute()
    ids = [m["id"] for m in res.get("messages", [])]
    lines.append(f"Unread emails (last 24h): {len(ids)}")
    for mid in ids:
        m = gmail.users().messages().get(userId="me", id=mid, format="metadata",
                                         metadataHeaders=["From", "Subject"]).execute()
        h = headers(m["payload"])
        lines.append(f"- From {h.get('from', '?')} | {h.get('subject', '')} | {m.get('snippet', '')[:160]}")
    return "\n".join(lines)


def write(facts: str, user_lang: str = "en") -> str:
    """Muse Spark turns the facts into the bubble text."""
    resp = config.client().responses.create(
        model=config.MODEL_SPARK,
        instructions=SYSTEM.replace("{lang}", LANG_NAME.get(user_lang, LANG_NAME["en"])),
        input=facts,
    )
    return (resp.output_text or "").strip()


def due_this_morning(now: datetime | None = None) -> bool:
    """True once per day, after 5 AM: time for the automatic morning briefing."""
    now = now or datetime.now()
    return now.hour >= 5 and load_state().get("last_brief") != date.today().isoformat()
