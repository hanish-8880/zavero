"""Urgent Gmail: spot an urgent email, brief it in a bubble, draft a reply, send only after a spoken yes.

Official Gmail API only. One-time setup (credentials.json + login): see scripts/gmail_login.py.
Nothing is ever sent without the user saying yes to the exact draft shown in the bubble.
"""
import base64
import json
import threading
import time
from email.mime.text import MIMEText
from email.utils import parseaddr

from zavero import actionlog, config
from zavero.phrases import lang
from zavero.reminders import extract_json

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",  # read new mail
    "https://www.googleapis.com/auth/gmail.compose",   # create drafts and send them
]
CREDS = config.ROOT / "credentials.json"   # OAuth client from Google Cloud (gitignored)
TOKEN = config.ROOT / "token.json"         # saved login (gitignored)
SEEN = config.ROOT / "data" / "gmail_seen.json"
POLL_S = 60
QUERY = "is:unread newer_than:2d -category:promotions -category:social -category:forums"

LANG_NAME = {"te": "Telugu (Telugu script)", "hi": "Hindi (Devanagari)", "en": "simple English"}

SYSTEM = (
    "You help a beginner computer user in India with their email. Read the email and reply with ONLY one "
    "JSON object:\n"
    '{"urgent": true | false, "why": str, "brief": str, "reply": str}\n'
    "- urgent: true only if the user should act today: a payment or bill due soon, a deadline today or "
    "tomorrow, a person waiting for an answer (family, boss, teacher, client), an interview or meeting soon, "
    "a security alert about their account. Newsletters, ads, receipts, OTP codes and automatic notifications "
    "are NOT urgent.\n"
    "- why: a few English words.\n"
    "- brief: 1-2 very short, simple sentences in {lang}: who wrote and what they need. Keep names, "
    "amounts and dates exact.\n"
    "- reply: a short polite reply in the same language as the email, 2-4 sentences, ready to send. "
    "Never promise money, never share passwords, OTPs or account numbers, never invent facts. "
    "If you don't know an answer, say the user will check and reply soon. No subject line, no placeholders."
)


class NotConnected(Exception):
    """Gmail is not set up yet (no credentials.json / token.json)."""


def service(interactive: bool = False):
    """Gmail API client. interactive=True opens the browser to log in (first time only)."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES) if TOKEN.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    if not creds or not creds.valid:
        if not interactive:
            raise NotConnected("Gmail is not connected. Run: python scripts/gmail_login.py")
        if not CREDS.exists():
            raise NotConnected(f"Missing {CREDS.name}. See scripts/gmail_login.py for the steps.")
        creds = InstalledAppFlow.from_client_secrets_file(str(CREDS), SCOPES).run_local_server(port=0)
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


# --- reading -------------------------------------------------------------------
def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def body_text(payload: dict, limit: int = 3000) -> str:
    """Plain-text body of a Gmail message payload (first text/plain part)."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return _b64(payload["body"]["data"])[:limit]
    for part in payload.get("parts", []) or []:
        text = body_text(part, limit)
        if text:
            return text
    return ""


def headers(payload: dict) -> dict:
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


def reply_raw(to_msg: dict, text: str) -> dict:
    """Gmail API body for a reply draft in the same thread."""
    h = headers(to_msg["payload"])
    mime = MIMEText(text, "plain", "utf-8")
    mime["To"] = h.get("reply-to") or h.get("from", "")
    subject = h.get("subject", "")
    mime["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    if h.get("message-id"):
        mime["In-Reply-To"] = h["message-id"]
        mime["References"] = (h.get("references", "") + " " + h["message-id"]).strip()
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    return {"message": {"raw": raw, "threadId": to_msg["threadId"]}}


def analyze(msg: dict, user_lang: str = "en") -> dict:
    """Ask Muse Spark if the email is urgent, for a brief in the user's language and a reply draft."""
    h = headers(msg["payload"])
    email = (f"From: {h.get('from', '')}\nSubject: {h.get('subject', '')}\n\n"
             f"{body_text(msg['payload']) or msg.get('snippet', '')}")
    resp = config.client().responses.create(
        model=config.MODEL_SPARK,
        instructions=SYSTEM.replace("{lang}", LANG_NAME.get(user_lang, LANG_NAME["en"])),
        input=email,
    )
    return extract_json(resp.output_text)


# --- the watcher ---------------------------------------------------------------
class GmailWatcher:
    """Polls Gmail; on an urgent email (and when the user is free) runs brief -> draft -> approve -> send."""

    def __init__(self, orch, ui) -> None:
        self.orch, self.ui = orch, ui
        self._queue: list[tuple[dict, dict]] = []
        try:
            self.seen: set[str] = set(json.loads(SEEN.read_text(encoding="utf-8")))
            self._first = False
        except (FileNotFoundError, ValueError):
            self.seen, self._first = set(), True  # first run: don't alarm about old mail

    def start(self) -> bool:
        """Start in the background. False if Gmail isn't connected yet."""
        try:
            self.gmail = service()
        except Exception as e:  # noqa: BLE001
            print(f"[gmail] {e}", flush=True)
            return False
        threading.Thread(target=self._loop, daemon=True).start()
        print("[gmail] connected, watching for urgent mail", flush=True)
        return True

    def _save_seen(self) -> None:
        SEEN.parent.mkdir(exist_ok=True)
        SEEN.write_text(json.dumps(sorted(self.seen)[-500:]), encoding="utf-8")

    def _loop(self) -> None:
        while True:
            try:
                self.check()
                if self._queue and self.orch.idle:
                    msg, info = self._queue.pop(0)
                    self.handle(msg, info)
            except Exception as e:  # noqa: BLE001 - network blips must not kill the watcher
                print(f"[gmail] {type(e).__name__}: {e}", flush=True)
                actionlog.log("gmail_error", error=str(e))
            time.sleep(POLL_S if not self._queue else 5)

    def check(self) -> None:
        """Look at new unread mail and queue the urgent ones."""
        res = self.gmail.users().messages().list(userId="me", q=QUERY, maxResults=10).execute()
        ids = [m["id"] for m in res.get("messages", [])]
        new = [i for i in ids if i not in self.seen]
        self.seen.update(new)
        if new:
            self._save_seen()
        if self._first:
            self._first = False
            return
        for mid in new:
            msg = self.gmail.users().messages().get(userId="me", id=mid, format="full").execute()
            info = analyze(msg, lang(self.orch.user_text))
            h = headers(msg["payload"])
            actionlog.log("email_checked", sender=h.get("from", ""), subject=h.get("subject", ""),
                          urgent=bool(info.get("urgent")), why=info.get("why", ""))
            if info.get("urgent"):
                self._queue.append((msg, info))

    def handle(self, msg: dict, info: dict) -> None:
        """Brief -> 'write a reply?' -> draft -> 'send?' -> send. Every step waits for a spoken yes."""
        ui, orch = self.ui, self.orch
        h = headers(msg["payload"])
        name = parseaddr(h.get("from", ""))[0] or parseaddr(h.get("from", ""))[1]
        L = lang(orch.user_text)
        ask_reply = {"te": "రిప్లై రాయమంటారా?", "hi": "जवाब लिखूँ?", "en": "Shall I write a reply?"}[L]
        yes_no = {"te": "(Right Ctrl పట్టుకుని **అవును / వద్దు** అనండి)",
                  "hi": "(Right Ctrl दबाकर **हाँ / नहीं** बोलिए)",
                  "en": "(hold Right Ctrl and say **yes / no**)"}[L]
        ui.set_mode.emit("Urgent email")
        ui.attention.emit()
        if not orch.ask(f"📩 **{name}**\n{info.get('brief', h.get('subject', ''))}\n\n{ask_reply} {yes_no}"):
            ui.hide_text.emit()
            return
        draft = self.gmail.users().drafts().create(userId="me", body=reply_raw(msg, info.get("reply", ""))).execute()
        actionlog.log("email_draft", to=h.get("from", ""), subject=h.get("subject", ""), draft_id=draft["id"])
        ask_send = {"te": "ఇది పంపమంటారా?", "hi": "यह भेज दूँ?", "en": "Send this?"}[L]
        ui.set_mode.emit("Reply draft")
        if not orch.ask(f"✉️ {info.get('reply', '')}\n\n**{ask_send}** {yes_no}", timeout=180):
            kept = {"te": "సరే, డ్రాఫ్ట్‌ని Gmail లో ఉంచాను.", "hi": "ठीक है, ड्राफ्ट Gmail में रख दिया है।",
                    "en": "Okay, I kept it in your Gmail **Drafts**."}[L]
            orch.ui.show_text.emit(kept, "done")
            return
        self.gmail.users().drafts().send(userId="me", body={"id": draft["id"]}).execute()
        actionlog.log("email_sent", to=h.get("from", ""), subject=h.get("subject", ""), draft_id=draft["id"])
        sent = {"te": "పంపేశాను ✅", "hi": "भेज दिया ✅", "en": "Sent ✅"}[L]
        ui.show_text.emit(f"{sent} → {name}", "done")
