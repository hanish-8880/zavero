"""Instant friendly phrases (no API call) in the user's language."""
import random
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
    "remind_fail": {
        "en": "I didn't get the time 🙂 Try: \"remind me **at 5 PM** to pay the bill\".",
        "te": "సమయం అర్థం కాలేదు 🙂 ఇలా చెప్పండి: \"**సాయంత్రం 5 కి** బిల్ కట్టాలని గుర్తు చేయి\".",
        "hi": "समय समझ नहीं आया 🙂 ऐसे बोलिए: \"**शाम 5 बजे** बिल भरना याद दिलाना\"।",
    },
    "no_reminders": {
        "en": "You have no reminders yet 🙂",
        "te": "ఇంకా ఏ రిమైండర్లు లేవు 🙂",
        "hi": "अभी कोई रिमाइंडर नहीं है 🙂",
    },
    "api_down": {
        "en": "I can't reach the internet right now 📶 Please check your connection and try again.",
        "te": "ఇప్పుడు ఇంటర్నెట్ అందడం లేదు 📶 కనెక్షన్ చూసి మళ్ళీ ప్రయత్నించండి.",
        "hi": "अभी इंटरनेट नहीं मिल रहा 📶 कनेक्शन देखकर फिर से कोशिश कीजिए।",
    },
    "no_credits": {
        "en": "I'm out of AI credits for now 😅 Please ask the person who set me up to add more.",
        "te": "నా AI క్రెడిట్లు అయిపోయాయి 😅 నన్ను సెటప్ చేసినవాళ్ళని ఇంకా జోడించమని అడగండి.",
        "hi": "मेरे AI क्रेडिट खत्म हो गए 😅 जिन्होंने मुझे सेट किया, उनसे और जोड़ने को कहिए।",
    },
    "slow": {
        "en": "That took too long ⏳ Please try again in a moment.",
        "te": "చాలా సమయం పట్టింది ⏳ కొంచెం సేపటి తర్వాత మళ్ళీ ప్రయత్నించండి.",
        "hi": "बहुत देर लग गई ⏳ थोड़ी देर बाद फिर से कोशिश कीजिए।",
    },
    "went_wrong": {
        "en": "Sorry, something went wrong 🙏 Please try again.",
        "te": "క్షమించండి, ఏదో తప్పు జరిగింది 🙏 మళ్ళీ ప్రయత్నించండి.",
        "hi": "माफ़ कीजिए, कुछ गड़बड़ हो गई 🙏 फिर से कोशिश कीजिए।",
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


POINT_LABELS = {
    "en": ["right here!", "this one!", "click this!"],
    "te": ["ఇక్కడే!", "ఇది!", "ఇది నొక్కండి!"],
    "hi": ["यहाँ!", "ये वाला!", "इसे दबाइए!"],
}


def point_label(label: str, user_text: str = "") -> str:
    """The chip next to Chai's target: the thing's name, or a friendly 'right here!' in their language."""
    return label.strip() or random.choice(POINT_LABELS[lang(user_text)])


def friendly_error(e: Exception, user_text: str = "") -> str:
    """A calm message for the user instead of the raw error (the raw error goes to the action log)."""
    name, msg = type(e).__name__, str(e).lower()
    status = getattr(e, "status_code", None)
    if status in (402, 429) or any(w in msg for w in ("quota", "credit", "insufficient", "billing")):
        key = "no_credits"
    elif "timeout" in name.lower() or "timed out" in msg:
        key = "slow"
    elif "connection" in name.lower() or "connect" in msg or "network" in msg:
        key = "api_down"
    else:
        key = "went_wrong"
    return phrase(key, user_text)
