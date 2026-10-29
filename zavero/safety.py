"""Risky-action rules. Zavero asks before risky steps and never types secrets."""
import re

# brain.py tells the model to start its note with this when the click is a final, consequential one.
MODEL_FLAG = "approval needed"
# A clicked label that starts or ends with one of these is a final action ("Pay Now", "Proceed to Pay").
# Navigation like "Quick Pay" or "Bill Payment" menus only open a page, so they don't count.
FINAL_START = ["pay", "make payment", "submit", "confirm", "send", "delete", "remove", "buy", "place order",
               "checkout", "transfer", "purchase", "install", "uninstall", "log out", "logout", "sign out",
               # publishing to other people (LinkedIn "Post", X "Tweet", "Reply all", "Go live"...)
               "post", "publish", "share", "tweet", "reply all", "upload", "go live", "schedule",
               "pettu", "post chey", "post karo", "daalo"]
# "Start a post" only opens the editor, so a plain "post" ending is not in this list.
FINAL_END = ["to pay", "to payment", "and pay", "pay now", "submit", "confirm", "send", "delete", "place order",
             "buy now", "checkout", "publish", "post now", "share now", "tweet", "upload"]
_VERB = r"(?:click|clicking|press|pressing|tap|tapping|select|selecting|choose|choosing|hit|hitting)"
_STOP = r"(?=\s+(?:to|so|for|and|which|that|then|in|on|at)\b|[,.;:!?(]|$)"
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


def target_labels(model_text: str) -> list[str]:
    """The on-screen labels the step will click: quoted ones first, else the words after 'click'."""
    quoted = re.findall(r'["“]([^"”]{1,40})["”]|\*\*([^*]{1,40})\*\*', model_text)
    labels = [a or b for a, b in quoted]
    if not labels:
        labels = re.findall(rf"{_VERB}\s+(?:on\s+)?(?:the\s+)?(.{{1,50}}?){_STOP}", model_text, re.I)
    clean = []
    for lab in labels:
        lab = re.sub(r"\b(button|link|tab|option|icon|menu)\b", " ", lab.lower())
        clean.append(" ".join(re.sub(r"[^\w\s₹]", " ", lab).split()))
    return [c for c in clean if c]


def risky_reason(model_text: str, actions) -> str | None:
    """Return why this step needs the user's OK, or None if it looks safe.

    Only the button being pressed counts, not the goal: while paying a bill, clicking "New tab"
    or "Quick Pay" is fine, but "Pay Now" / "Proceed to Pay" / "Submit" must be approved."""
    if MODEL_FLAG in model_text.lower():
        return "this is a final step"
    for lab in target_labels(model_text):
        if any(lab == w or lab.startswith(w + " ") for w in FINAL_START) or any(lab.endswith(w) for w in FINAL_END):
            return f'"{lab}" step'
    return None


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
