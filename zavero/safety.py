"""Risky-action rules. Zavero asks before risky steps and never types secrets."""
import re

RISKY_WORDS = [
    "pay", "payment", "submit", "confirm", "send", "delete", "remove", "purchase",
    "buy", "transfer", "logout", "log out", "sign out", "install", "uninstall",
    "checkout", "place order",
]
# Meta's API attaches this to every computer action. In do mode, the user's "do it" covers it
# unless the step is risky (decided with the developer, Oct 27).
GENERIC_CHECK = "computer_action_requires_confirmation"

SECRET_WORDS =["password", "otp", "pin", "cvv", "aadhaar", "aadhar", "pan number", "card number"]


def _get(action, name, default=None):
    return action.get(name, default) if isinstance(action, dict) else getattr(action, name, default)


def _typed(actions) -> list[str]:
    return [_get(a, "text", "") or "" for a in actions if _get(a, "type") == "type"]


def _has_word(text: str, words: list[str]) -> str | None:
    for w in words:
        if re.search(rf"\b{re.escape(w)}\b", text):
            return w
    return None


def risky_reason(model_text: str, actions) -> str | None:
    """Return why this step needs the user's OK, or None if it looks safe."""
    text = " ".join([model_text, *_typed(actions)]).lower()
    word = _has_word(text, RISKY_WORDS)
    return f'"{word}" step' if word else None


def secret_reason(model_text: str, actions) -> str | None:
    """Return why Zavero must not type this itself (password, OTP, card, Aadhaar...)."""
    typed = _typed(actions)
    if not typed:
        return None
    word = _has_word(model_text.lower(), SECRET_WORDS)
    if word:
        return f"it needs your {word}"
    for t in typed:
        digits = re.sub(r"[\s-]", "", t)
        if re.fullmatch(r"\d{12}", digits):
            return "it looks like an Aadhaar number"
        if re.fullmatch(r"\d{13,19}", digits):
            return "it looks like a card number"
        if re.fullmatch(r"[A-Za-z]{5}\d{4}[A-Za-z]", t.strip()):
            return "it looks like a PAN number"
    return None
