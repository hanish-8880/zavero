"""Turns the model's next step into short bubble text in the user's language."""
from zavero import config, phrases

# Tone rules for every text a beginner reads (adapted from Clicky's prompt).
STYLE = (
    "Style: never use the words 'simply', 'just', 'obviously' or 'easy' (they make beginners feel stupid). "
    "Never end with a yes/no offer like 'Want me to explain more?'. "
    "If the user asks for more detail (explain more / inka cheppu / aur batao), you may write longer. "
    "If the screen has nothing to do with the question, answer the question directly. "
    "Mention specific things you can see on screen when it helps."
)
# Only for answers and results, not for step-by-step instructions.
SEED = "When it feels natural, end with one bigger next thing they could try. Ending with nothing is fine too."

SYSTEM = (
    "You are Zavero, a friendly helper for beginner computer users in India. "
    "Write the text for a small chat bubble.\n"
    "Language: reply in the same language as the user's request. "
    "If the request has Telugu words (in any script) -> Telugu script. "
    "Hindi in Devanagari -> Devanagari. Hindi in English letters (Hinglish) -> simple romanized Hinglish. "
    "English -> simple English.\n"
    "Max 2 short sentences. Very simple everyday words. No jargon, never mention coordinates. "
    "Keep on-screen labels (buttons, menus, boxes) in English exactly as shown, in **bold**.\n" + STYLE
)

KINDS = {
    "guide": "Tell the user what THEY should do now. They will click or type themselves.",
    "do": "Tell the user what YOU (Zavero) are doing right now, e.g. \"I'm clicking **Start**\".",
    "confirm": (
        "This step is risky ({reason}). Do NOT do it yet. Briefly say what the step does and ask "
        "permission. End with: hold Right Ctrl and say yes or no (use their language's words, "
        "e.g. avunu / vaddu, haan / nahi)."
    ),
    "handoff": (
        "Zavero must not do this step itself because {reason}. Ask the user to do it themselves, "
        "then hold Right Ctrl and say \"next\" (or ayindi / ho gaya)."
    ),
    "final": "The task is finished, or cannot be done. Tell the user the result. " + SEED,
}


def describe_actions(actions) -> str:
    """Plain summary of actions without coordinates."""
    parts = []
    for a in actions:
        get = a.get if isinstance(a, dict) else (lambda k, d=None, a=a: getattr(a, k, d))
        kind = get("type")
        if kind == "type":
            parts.append(f'type "{get("text", "")}"')
        elif kind == "keypress":
            parts.append("press " + "+".join(get("keys", []) or []))
        elif kind == "scroll":
            parts.append("scroll " + ("down" if (get("scroll_y", 0) or 0) > 0 else "up"))
        elif kind not in ("screenshot", "wait", "move"):
            parts.append(kind.replace("_", " "))
    return ", ".join(parts) or "look at the screen"


def narrate(kind: str, user_text: str, model_text: str, actions=(), reason: str = "") -> str:
    """Bubble text for this step. Falls back to the model's own text on any error."""
    prompt = (
        f"User's request: {user_text}\n"
        f"Screen helper's note (English): {model_text or '-'}\n"
        f"Planned actions: {describe_actions(actions)}\n"
        f"Task: {KINDS[kind].format(reason=reason)}"
    )
    if phrases.FORCED:  # the user picked a language in the tray menu
        prompt += f"\nAlways reply in {phrases.LANG_NAMES[phrases.FORCED]}, whatever language the request is in."
    try:
        resp = config.client().responses.create(
            model=config.MODEL_SPARK, instructions=SYSTEM, input=prompt, reasoning=config.REASONING,
        )
        text = (resp.output_text or "").strip()
        return text or model_text
    except Exception as e:  # noqa: BLE001 - a bubble must always show something
        print(f"[narrator] {type(e).__name__}: {e}")
        return model_text or describe_actions(actions)
