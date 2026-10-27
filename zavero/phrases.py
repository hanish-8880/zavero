"""Instant friendly phrases (no API call) in the user's language."""
import re

PHRASES = {
    "welcome": {
        "en": "Hi! I'm **Zavero** 👋\nHold **Right Ctrl** and tell me what you want to do.",
        "te": "నమస్తే! నేను **Zavero** 👋\n**Right Ctrl** పట్టుకుని మీకు ఏం కావాలో చెప్పండి.",
        "hi": "नमस्ते! मैं **Zavero** हूँ 👋\n**Right Ctrl** दबाकर रखिए और बताइए क्या करना है।",
    },
    "looking": {
        "en": "Let me look at your screen…",
        "te": "మీ స్క్రీన్ చూస్తున్నాను…",
        "hi": "आपकी स्क्रीन देख रहा हूँ…",
    },
    "great": {
        "en": "Super! 👍",
        "te": "బాగుంది! 👍",
        "hi": "बहुत बढ़िया! 👍",
    },
    "oops": {
        "en": "Oops, not there 🙂 Click the **yellow circle**.",
        "te": "అక్కడ కాదు 🙂 **పసుపు రంగు వృత్తం** మీద క్లిక్ చేయండి.",
        "hi": "वहाँ नहीं 🙂 **पीले गोले** पर क्लिक कीजिए।",
    },
    "stopped": {
        "en": "Okay, I stopped. Call me anytime! 🙂",
        "te": "సరే, ఆపేశాను. ఎప్పుడైనా పిలవండి! 🙂",
        "hi": "ठीक है, रुक गया। जब चाहें बुलाइए! 🙂",
    },
    "heard_nothing": {
        "en": "I couldn't hear you. Please speak a little louder 🙂",
        "te": "నాకు వినిపించలేదు. కొంచెం గట్టిగా మాట్లాడండి 🙂",
        "hi": "मुझे सुनाई नहीं दिया। थोड़ा ज़ोर से बोलिए 🙂",
    },
}


def lang(text: str) -> str:
    """'te' for Telugu script, 'hi' for Devanagari, else 'en' (also covers Hinglish)."""
    if re.search(r"[ఀ-౿]", text or ""):
        return "te"
    if re.search(r"[ऀ-ॿ]", text or ""):
        return "hi"
    return "en"


def phrase(key: str, user_text: str = "") -> str:
    """A phrase in the same language as the user's last words."""
    return PHRASES[key][lang(user_text)]
