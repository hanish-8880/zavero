import base64
from email import message_from_bytes

from zavero.messaging.gmail import body_text, reply_raw


def b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


MSG = {
    "threadId": "t1",
    "payload": {
        "mimeType": "multipart/alternative",
        "headers": [
            {"name": "From", "value": "Ravi <ravi@example.com>"},
            {"name": "Subject", "value": "Bill due today"},
            {"name": "Message-ID", "value": "<abc@example.com>"},
        ],
        "parts": [
            {"mimeType": "text/plain", "body": {"data": b64("Please pay ₹1,250 by 6 PM.")}},
            {"mimeType": "text/html", "body": {"data": b64("<p>html</p>")}},
        ],
    },
}


def test_body_text():
    assert body_text(MSG["payload"]) == "Please pay ₹1,250 by 6 PM."


def test_reply_is_threaded():
    body = reply_raw(MSG, "Okay, I will pay today.")
    assert body["message"]["threadId"] == "t1"
    mime = message_from_bytes(base64.urlsafe_b64decode(body["message"]["raw"]))
    assert mime["To"] == "Ravi <ravi@example.com>"
    assert mime["Subject"] == "Re: Bill due today"
    assert mime["In-Reply-To"] == "<abc@example.com>"
    assert mime.get_payload(decode=True).decode() == "Okay, I will pay today."
