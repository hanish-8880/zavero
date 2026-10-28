"""Connect Zavero to your Gmail (one time).

1. Go to https://console.cloud.google.com/ -> create a project (any name, e.g. "zavero").
2. APIs & Services -> Library -> search "Gmail API" -> Enable.
3. APIs & Services -> OAuth consent screen -> External -> fill app name + your email -> Save.
   Under "Test users" add your own Gmail address.
4. APIs & Services -> Credentials -> Create credentials -> OAuth client ID -> "Desktop app" -> Create
   -> Download JSON. Save it in the repo root as credentials.json (it is gitignored).
5. Run:  python scripts/gmail_login.py
   A browser opens: pick your account -> "Continue" (Google warns the app is unverified; that's
   expected for your own test app) -> allow. token.json is saved, and Zavero watches Gmail from now on.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zavero.messaging.gmail import service  # noqa: E402

gmail = service(interactive=True)
profile = gmail.users().getProfile(userId="me").execute()
print(f"Connected to {profile['emailAddress']} ({profile['messagesTotal']} emails). Restart Zavero.")
