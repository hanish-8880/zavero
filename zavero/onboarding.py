"""First run: Chai says hello in three languages, checks the mic, learns the user's name and language,
flies to something real on their screen with a playful comment, and shows its three powers.

Runs once (data/state.json -> onboarded: true). Tray -> "Replay onboarding" runs it again.
"""
import queue
import time

from zavero import actionlog, briefing, config, driver
from zavero.phrases import LANG_NAMES, lang
from zavero.reminders import extract_json

HELLO = [
    ("en", "Hey! I'm **Chai**, your **Zavero** buddy 👋"),
    ("te", "నమస్తే! నేను **Chai**, మీ **Zavero** స్నేహితుడిని 👋"),
    ("hi", "नमस्ते! मैं **Chai** हूँ, आपका **Zavero** दोस्त 👋"),
]
SAY_HI = "Hold **Right Ctrl** and say hi in your language 🎤\nపట్టుకుని హాయ్ చెప్పండి · दबाकर हाय बोलिए"
TEXT = {
    "name": {
        "en": "I heard you! 🎉 What should I call you?",
        "te": "వినిపించింది! 🎉 మిమ్మల్ని ఏమని పిలవాలి?",
        "hi": "सुनाई दिया! 🎉 आपको क्या बुलाऊँ?",
    },
    "nice": {
        "en": "Nice to meet you, **{name}**! Let me look at your screen…",
        "te": "మిమ్మల్ని కలవడం సంతోషం, **{name}**! మీ స్క్రీన్ చూస్తాను…",
        "hi": "आपसे मिलकर खुशी हुई, **{name}**! आपकी स्क्रीन देखता हूँ…",
    },
    "powers": {
        "en": "Here's what I can do, **{name}**:\n• Ask **\"what is this?\"** about anything\n"
              "• Say **\"do it\"** and I'll click for you (I always ask before paying or sending)\n"
              "• Ask me to **draw** and explain\nHold **Right Ctrl** anytime 🙂",
        "te": "**{name}**, నేను ఇవి చేయగలను:\n• ఏదైనా **\"ఇది ఏంటి?\"** అని అడగండి\n"
              "• **\"నువ్వే చెయ్\"** అంటే నేనే క్లిక్ చేస్తాను (డబ్బు కట్టే ముందు, పంపే ముందు అడుగుతాను)\n"
              "• **గీసి** వివరించమని అడగండి\nఎప్పుడైనా **Right Ctrl** పట్టుకోండి 🙂",
        "hi": "**{name}**, मैं ये कर सकता हूँ:\n• किसी भी चीज़ पर **\"ये क्या है?\"** पूछिए\n"
              "• **\"कर दो\"** बोलिए, मैं क्लिक कर दूँगा (पैसे भरने या भेजने से पहले पूछूँगा)\n"
              "• **बना के समझाने** को कहिए\nकभी भी **Right Ctrl** दबाइए 🙂",
    },
    "privacy": {
        "en": "🔒 I only look at your screen when you hold the key, and I never save screenshots.",
        "te": "🔒 మీరు key పట్టుకున్నప్పుడే స్క్రీన్ చూస్తాను, స్క్రీన్‌షాట్లు సేవ్ చేయను.",
        "hi": "🔒 मैं सिर्फ़ key दबाने पर स्क्रीन देखता हूँ और स्क्रीनशॉट सेव नहीं करता।",
    },
}

NAME_SYSTEM = ('The user was asked "What should I call you?" and answered (speech-to-text, may be Telugu, Hindi '
               'or English). Reply with ONLY JSON {"name": str | null}: just their name, capitalised, in English '
               'letters if possible.')
DEMO_SYSTEM = (
    "You are Chai, a cute, playful helper buddy meeting a new user. Look at their screen and pick ONE specific, "
    "concrete thing you can name (an app icon, a picture, a button, a word) whose centre is between 20% and 80% "
    "of the width and height. Reply with ONLY JSON {\"x\": int, \"y\": int, \"comment\": str, \"label\": str}: "
    "x, y = its centre in screenshot pixels; comment = at most 6 playful, friendly words about it in {lang} "
    "(never quote long screen text); label = 1-3 words naming it."
)
WAIT_S = 45


def _ask_spark(system: str, content) -> dict:
    resp = config.client().responses.create(model=config.MODEL_SPARK, reasoning=config.REASONING,
                                            instructions=system, input=content)
    return extract_json(resp.output_text)


def pick_name(said: str) -> str:
    """Their name from "naa peru Hanish" / "call me Ravi" (Spark, with a simple fallback)."""
    try:
        name = _ask_spark(NAME_SYSTEM, said).get("name")
    except Exception:  # noqa: BLE001
        name = None
    if not name:
        words = [w.strip(".,!?") for w in said.split()]
        name = words[-1] if words else ""
    return str(name).strip()[:24]


def demo_point(shot: driver.Shot, user_lang: str) -> dict | None:
    """One playful comment about something in the middle of the screen, or None."""
    try:
        data = _ask_spark(DEMO_SYSTEM.replace("{lang}", LANG_NAMES[user_lang]), [{"role": "user", "content": [
            {"type": "input_text", "text": "Say hi to my screen!"},
            {"type": "input_image", "image_url": shot.data_url}]}])
        x, y = float(data["x"]), float(data["y"])
    except Exception:  # noqa: BLE001 - onboarding goes on without the demo
        return None
    if not (0.15 * shot.width <= x <= 0.85 * shot.width and 0.15 * shot.height <= y <= 0.85 * shot.height):
        return None
    return {"x": x, "y": y, "comment": str(data.get("comment", ""))[:60], "label": str(data.get("label", ""))[:24]}


def run(orch, heard: queue.Queue) -> None:
    """The whole first-run flow. `heard` receives every final transcript while onboarding is on."""
    ui = orch.ui
    ui.set_mode.emit("Hello")
    for _, text in HELLO:
        ui.show_text.emit(text, "info")
        time.sleep(2.4)
    ui.attention.emit()
    ui.show_text.emit(SAY_HI, "listen")
    try:
        hi = heard.get(timeout=WAIT_S)
    except queue.Empty:
        hi = ""
    user_lang = lang(hi) if hi else orch.lang
    orch.lang = user_lang
    ui.show_text.emit(TEXT["name"][user_lang], "hold")  # waits for their answer
    try:
        name = pick_name(heard.get(timeout=WAIT_S))
    except queue.Empty:
        name = ""
    name = name or {"te": "స్నేహితుడు", "hi": "दोस्त"}.get(user_lang, "friend")
    briefing.save_state(name=name, lang=user_lang)
    ui.show_text.emit(TEXT["nice"][user_lang].format(name=name), "info")

    ui.hide_for_capture()
    try:
        shot = driver.screenshot()
    finally:
        ui.show_after_capture()
    ui.set_thinking.emit(True)
    demo = demo_point(shot, user_lang)
    ui.set_thinking.emit(False)
    if demo:
        ui.point_at.emit(*driver.to_screen(demo["x"], demo["y"], shot))
        ui.set_label.emit(demo["label"] or "👀")
        ui.show_text.emit(demo["comment"] or "👀", "done")
        time.sleep(4)
        ui.go_home.emit()
    # Two short bubbles instead of one tall one.
    ui.show_text.emit(TEXT["powers"][user_lang].format(name=name), "hold")
    time.sleep(8)
    ui.show_text.emit(TEXT["privacy"][user_lang], "info")  # fades after its reading time (~6 s)
    briefing.save_state(onboarded=True)
    actionlog.log("onboarded", lang=user_lang, name=name, demo=bool(demo))
