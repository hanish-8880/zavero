"""Guide anything: one general engine that walks a beginner to any goal, on any app, in their language.

    "teach me <app>" / "I want to <goal>" / "<app> nerpinchu" / "mujhe <goal> sikhao"

1. The request becomes a goal. 2. If it needs personal details (business, city, budget, level), ask 3-5
short questions (buttons + voice). 3. Knowledge comes ONLY from skills/*.md (skills.py); if there is none
(or it is older than 60 days) read the official help pages and write one (research.py). 4. Plan 8-20
plain steps with a "why" each; the user can change it. 5. Each step is shown with the right guide for the
action (ring / key chip / drag or scroll arrow / text to type / zoom for tiny icons) and the user does it,
or presses "Do it for me". 6. A new screenshot checks the result; wrong -> explain and retry.
7. Paying, publishing, submitting, sending or sharing personal data needs a clear Yes; secrets are never
typed. 8. Progress is saved per goal ("continue" resumes); follow-ups become reminders (after asking).
9. At the end, what worked (and fixes for mistakes) is added to the skill file.

Nothing here is about one app or one field.
"""
import json
import math
import queue
import re
import threading
import time
import uuid
from datetime import datetime, timedelta

from zavero import actionlog, config, driver, research, safety, skills, talk
from zavero.phrases import LANG_NAMES, lang
from zavero.reminders import extract_json

GOAL_WORDS = [
    r"\bteach me\b", r"\bi want to (learn|make|create|build|start|design|set ?up|edit|record|open a)\b",
    r"\bhelp me (learn|make|create|build|start|set ?up)\b", r"\bguide me\b", r"\bstep by step\b",
    r"\blearn (how|to)\b", r"\bshow me how to\b",
    r"\bnerpinch", r"\bnerchuko", r"\bnerpu\b", r"నేర్పించ", r"నేర్చుకో", r"నేర్పు",
    r"\bsikha(o|na|do|iye|ye)\b", r"\bseekh(na|ni|ao)\b", r"सिखा", r"सीख",
]
HOW_WORDS = [r"\bhow (do|can) i\b", r"\bhow to\b", r"\bela\b", r"\bkaise\b", r"ఎలా", r"कैसे"]
CONTINUE_WORDS = [r"^\s*(continue|resume|carry on|go on)\b", r"\bkonasaginchu", r"కొనసాగించు",
                  r"\baage badh", r"\bjaari rakh", r"जारी रख", r"आगे बढ़"]
CHANGE_WORDS = r"\bchange\b|\binstead\b|\bmaarchu|\bmarchu|\bbadlo|\bbadal|మార్చు|बदल"
KINDS = ("click", "double_click", "key", "drag", "scroll", "type", "choose", "look", "done_already")
STORE = config.ROOT / "data" / "goals.json"
MAX_TRIES = 3
WAIT_S = 300  # a step waits this long for the user before pausing the goal

DETAILS_SYSTEM = (
    "A beginner in India wants help with this goal: {goal}\nKnown skill notes:\n{skill}\n"
    "Decide if a GOOD plan needs personal details (e.g. their business, city, budget, level, purpose, "
    "style). If not, return no questions. Else 3-5 very short questions, each with 2-4 short answer options. "
    "Language of questions and options: {lang}. Reply with ONLY JSON: "
    '{"questions": [{"q": str, "options": [str]}]}'
)
PLAN_SYSTEM = (
    "You plan how to guide a complete beginner to this goal on their own computer: {goal}\n"
    "Their answers: {answers}\nOpen window: {title}\nSkill notes (use these names and choices):\n{skill}\n"
    "Write 8-20 small steps that each need ONE action on screen (click, keyboard shortcut, drag, scroll, "
    "type, or pick an option). Plain words, no jargon. Each step has a one-line 'why' in plain words. "
    "Add follow-ups only if the goal truly has later tasks (e.g. check results in a week). "
    "Language of title, steps and why: {lang}; keep on-screen labels in English in **bold**. "
    "Reply with ONLY JSON: "
    '{"title": str, "steps": [{"title": str, "why": str}], "follow_ups": [{"title": str, "days": int}]}'
)
REVISE_ADD = "\nThe user saw this plan and asked to change it: {change}\nPlan was: {plan}"
STEP_SYSTEM = (
    "You guide a beginner one step at a time on their screen. Goal: {goal}. Their answers: {answers}.\n"
    "Skill notes:\n{skill}\nCurrent step {n} of {total}: {step}\nWhy: {why}\n{retry}"
    "Look at the screenshot and say exactly what to do NOW for this step. Reply with ONLY JSON: "
    '{"action": "click|double_click|key|drag|scroll|type|choose|look|done_already", '
    '"x": int, "y": int, "to": {"x": int, "y": int} | null, "keys": [str], "scroll": "up|down", '
    '"text": str, "label": str, "say": str, "why_choice": str, "tiny": bool, "risky": bool, "secret": bool}\n'
    "- x, y: screenshot pixel centre of the thing to click / press on / scroll over / type into. "
    "to: where a drag ends. keys: e.g. [\"ctrl\", \"s\"]. text: exactly what to type.\n"
    "- choose = picking a setting / filter / option: point at the best one and fill why_choice with why it "
    "fits THEIR answers. look = nothing to do but read something on screen.\n"
    "- done_already: the screen shows this step is already done.\n"
    "- label: 1-3 words naming the target as on screen. say: max 2 short sentences telling them what to do, "
    "in {lang}, on-screen labels in English **bold**. tiny: true if the target is a very small icon.\n"
    "- risky: true if this step spends money, publishes, posts, submits a form, sends a message, or shares "
    "personal data. secret: true if it needs a password, OTP, PIN, card, Aadhaar or PAN (the user types it)."
)
CHECK_SYSTEM = (
    "A beginner just tried this step: {step} (expected: {expect}). Look at the new screenshot. Reply with ONLY "
    'JSON: {"ok": bool, "what_happened": str, "fix": str}. what_happened: 1 short sentence. fix: if not ok, '
    "1-2 short sentences on what to do instead. Language: {lang}."
)
LEARN_SYSTEM = (
    "A beginner finished this goal: {goal}. Steps and what happened:\n{log}\n"
    "Write 2-6 short English bullet lines for the skill file: what worked well, and each mistake made with "
    'its fix. Reply with ONLY JSON: {"lines": [str]}'
)

TEXT = {
    "reading": {"en": "Let me read the official help pages first… 📖", "te": "ముందు అధికారిక సహాయ పేజీలు చదువుతాను… 📖",
                "hi": "पहले आधिकारिक हेल्प पेज पढ़ता हूँ… 📖"},
    "start_q": {"en": "Shall we start? Or tell me what to change.", "te": "మొదలుపెడదామా? లేదా ఏం మార్చాలో చెప్పండి.",
                "hi": "शुरू करें? या बताइए क्या बदलना है।"},
    "step": {"en": "Step {n} of {total}", "te": "{total} లో {n}వ స్టెప్", "hi": "{total} में से स्टेप {n}"},
    "type_this": {"en": "Type this:", "te": "ఇది టైప్ చేయండి:", "hi": "ये टाइप कीजिए:"},
    "secret": {"en": "Please type this yourself 🔒 (I never type passwords or OTPs). Then press **Done**.",
               "te": "దీన్ని మీరే టైప్ చేయండి 🔒 (నేను పాస్‌వర్డ్/OTP టైప్ చేయను). తర్వాత **Done** నొక్కండి.",
               "hi": "इसे आप खुद टाइप कीजिए 🔒 (मैं पासवर्ड/OTP नहीं डालता)। फिर **Done** दबाइए।"},
    "risky": {"en": "⚠️ This step {what}. Do you want to go ahead?", "te": "⚠️ ఈ స్టెప్ {what}. ముందుకు వెళ్దామా?",
              "hi": "⚠️ ये स्टेप {what}। आगे बढ़ें?"},
    "paused": {"en": "Paused at {step} 🙂 Say **continue** anytime.",
               "te": "{step} దగ్గర ఆపాను 🙂 ఎప్పుడైనా **continue** అనండి.",
               "hi": "{step} पर रोका 🙂 कभी भी **continue** बोलिए।"},
    "moving_on": {"en": "Let's move on to the next step.", "te": "తర్వాతి స్టెప్‌కి వెళ్దాం.",
                  "hi": "अगले स्टेप पर चलते हैं।"},
    "finished": {"en": "🎉 You did it: **{title}**!", "te": "🎉 మీరు పూర్తి చేశారు: **{title}**!",
                 "hi": "🎉 आपने कर दिखाया: **{title}**!"},
    "remind": {"en": "Shall I remind you in {days} days: {title}?", "te": "{days} రోజుల్లో గుర్తు చేయనా: {title}?",
               "hi": "{days} दिन में याद दिलाऊँ: {title}?"},
    "nothing": {"en": "Nothing to continue 🙂 Tell me what you want to learn.",
                "te": "కొనసాగించడానికి ఏమీ లేదు 🙂 ఏం నేర్చుకోవాలో చెప్పండి.",
                "hi": "जारी रखने को कुछ नहीं 🙂 बताइए क्या सीखना है।"},
}


def is_goal(text: str) -> bool:
    t = text.lower()
    words = GOAL_WORDS + (HOW_WORDS if config.COACH_HOW_TO else [])
    return any(re.search(w, t) for w in words)


def is_continue(text: str) -> bool:
    t = text.lower().strip()
    return len(t.split()) <= 4 and any(re.search(w, t) for w in CONTINUE_WORDS)


# --- keys ---------------------------------------------------------------------
_KEY_ALIASES = {"control": "ctrl", "ctl": "ctrl", "windows": "win", "cmd": "win", "super": "win", "meta": "win",
                "return": "enter", "escape": "esc", "del": "delete", "option": "alt", "spacebar": "space",
                "pgup": "page_up", "pgdn": "page_down", "pageup": "page_up", "pagedown": "page_down"}


def norm_key(k: str) -> str:
    k = str(k).strip().lower().replace(" ", "_")
    k = re.sub(r"_(l|r|gr)$", "", k)
    return _KEY_ALIASES.get(k, k)


def norm_keys(keys) -> list[str]:
    if isinstance(keys, str):
        keys = re.split(r"\s*\+\s*", keys)
    return [norm_key(k) for k in keys if str(k).strip()]


def pynput_name(key) -> str:
    """pynput key -> our name ('ctrl', 's', 'f5'). Letters come from the virtual-key code, because
    with Ctrl held the character is a control code."""
    name = getattr(key, "name", None)
    if name:
        return norm_key(name)
    vk = getattr(key, "vk", None)
    if vk is not None and (48 <= vk <= 57 or 65 <= vk <= 90):
        return chr(vk).lower()
    return norm_key(getattr(key, "char", "") or "")


def keys_match(pressed: set[str], expected: list[str]) -> bool:
    """All expected keys are down together (extra keys don't matter, order doesn't matter)."""
    return bool(expected) and set(expected) <= pressed


def key_label(k: str) -> str:
    return {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "⊞ Win", "enter": "Enter", "esc": "Esc",
            "space": "Space", "tab": "Tab", "delete": "Delete", "backspace": "⌫"}.get(k, k.upper() if len(k) == 1 else k.title())


# --- cleaning model output -------------------------------------------------------
def clean_plan(data: dict) -> dict:
    steps = [{"title": str(s.get("title", "")).strip()[:160], "why": str(s.get("why", "")).strip()[:200]}
             for s in data.get("steps") or [] if isinstance(s, dict) and str(s.get("title", "")).strip()][:20]
    if not steps:
        raise ValueError("plan has no steps")
    ups = []
    for f in data.get("follow_ups") or []:
        try:
            days = int(f.get("days", 0))
        except (TypeError, ValueError, AttributeError):
            continue
        if f.get("title") and 0 < days <= 365:
            ups.append({"title": str(f["title"])[:120], "days": days})
    return {"title": str(data.get("title") or "").strip()[:80] or steps[0]["title"], "steps": steps,
            "follow_ups": ups[:3]}


def _num(v, hi: int) -> int | None:
    try:
        return min(max(int(round(float(v))), 0), hi - 1)
    except (TypeError, ValueError):
        return None


def clean_step(data: dict, width: int, height: int) -> dict:
    """Validate the model's step: known action, coordinates inside the screenshot, keys normalised."""
    action = data.get("action") if data.get("action") in KINDS else "look"
    x, y = _num(data.get("x"), width), _num(data.get("y"), height)
    to = data.get("to") if isinstance(data.get("to"), dict) else {}
    tx, ty = _num(to.get("x"), width), _num(to.get("y"), height)
    if action in ("click", "double_click", "choose", "drag", "scroll", "type") and (x is None or y is None):
        action = "look" if action != "type" else "type"
    if action == "drag" and (tx is None or ty is None):
        action = "click"
    keys = norm_keys(data.get("keys") or [])
    if action == "key" and not keys:
        action = "look"
    return {"action": action, "x": x, "y": y, "to": (tx, ty) if action == "drag" else None, "keys": keys,
            "scroll": "up" if str(data.get("scroll")).lower() == "up" else "down",
            "text": str(data.get("text") or "")[:500], "label": str(data.get("label") or "")[:30],
            "say": str(data.get("say") or "").strip(), "why_choice": str(data.get("why_choice") or "").strip(),
            "tiny": bool(data.get("tiny")), "risky": bool(data.get("risky")), "secret": bool(data.get("secret"))}


def to_actions(st: dict) -> list[dict]:
    """The step as computer actions in screenshot pixels (driver.execute), for "Do it for me"."""
    a, x, y = st["action"], st["x"], st["y"]
    if a in ("click", "choose"):
        return [{"type": "click", "x": x, "y": y}]
    if a == "double_click":
        return [{"type": "double_click", "x": x, "y": y}]
    if a == "key":
        return [{"type": "keypress", "keys": st["keys"]}]
    if a == "drag":
        return [{"type": "drag", "path": [{"x": x, "y": y}, {"x": st["to"][0], "y": st["to"][1]}]}]
    if a == "scroll":
        return [{"type": "scroll", "x": x, "y": y, "scroll_y": -400 if st["scroll"] == "up" else 400}]
    if a == "type":
        return ([{"type": "click", "x": x, "y": y}] if x is not None else []) + [{"type": "type", "text": st["text"]}]
    return []


# --- saved progress --------------------------------------------------------------
class Goals:
    """data/goals.json: every goal with its plan and how far the user got."""

    def __init__(self, path=STORE) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}

    def save(self, g: dict) -> None:
        with self._lock:
            data = self._load()
            g["updated"] = datetime.now().isoformat(timespec="seconds")
            data[g["id"]] = g
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def latest_unfinished(self) -> dict | None:
        open_ = [g for g in self._load().values() if not g.get("done") and g.get("plan")]
        return max(open_, key=lambda g: g.get("updated", ""), default=None)


class Cancelled(Exception):
    pass


class Coach:
    """Runs one goal at a time in its own thread. While active, the orchestrator sends it every transcript
    (feed) and bubble button (button)."""

    def __init__(self, orch, goals: Goals | None = None, skill_dir=None) -> None:
        self.o = orch
        self.ui = orch.ui
        self.goals = goals or Goals()
        self.skill_dir = skill_dir
        self.active = False
        self._inbox: queue.Queue = queue.Queue()  # ("say", text) / ("button", id) / ("act", how)
        self._cancel = threading.Event()
        self.pause = time.sleep  # tests replace this

    # --- hooks the orchestrator calls ----------------------------------------
    def feed(self, text: str) -> None:
        self._inbox.put(("say", text))

    def button(self, b: str) -> None:
        self._inbox.put(("button", b))

    def cancel(self) -> None:
        self._cancel.set()
        self._inbox.put(("button", "close"))

    def start(self, text: str) -> None:
        self._launch(self.run, text)

    def resume(self) -> None:
        g = self.goals.latest_unfinished()
        if not g:
            self._say(self._t("nothing", self.o.lang), "info")
            return
        self._launch(self._run_goal, g)

    def _launch(self, fn, arg) -> None:
        if self.active:
            return
        self.active = True
        self._cancel.clear()
        self._inbox = queue.Queue()

        def work() -> None:
            try:
                fn(arg)
            except Cancelled:
                actionlog.log("coach_stopped")
            except Exception as e:  # noqa: BLE001 - tell the user, keep the saved progress
                actionlog.log("coach_error", error=str(e))
                from zavero.phrases import friendly_error
                self._say(friendly_error(e, self.o.user_text), "error")
            finally:
                self.active = False
                self.ui.show_keys.emit([])
                self.ui.go_home.emit()
                self.ui.set_thinking.emit(False)

        threading.Thread(target=work, daemon=True).start()

    # --- small helpers ---------------------------------------------------------
    @staticmethod
    def _t(key: str, lg: str, **kw) -> str:
        return TEXT[key].get(lg, TEXT[key]["en"]).format(**kw)

    def _say(self, text: str, mood: str, buttons: list | None = None) -> None:
        if buttons:
            self.ui.show_buttons.emit(text, mood, buttons)
        else:
            self.ui.show_text.emit(text, mood)

    def _check(self) -> None:
        if self._cancel.is_set():
            raise Cancelled

    def model(self, system: str, text: str, shot=None) -> dict:
        """One Muse Spark call returning JSON (screenshot optional)."""
        content = [{"type": "input_text", "text": text}]
        if shot is not None:
            content.append({"type": "input_image", "image_url": shot.data_url})
        self.ui.set_thinking.emit(True)
        try:
            resp = config.client().responses.create(model=config.MODEL_SPARK, reasoning=config.REASONING,
                                                    instructions=system, input=[{"role": "user", "content": content}])
        finally:
            self.ui.set_thinking.emit(False)
        return extract_json(resp.output_text)

    def screenshot(self):
        self.ui.hide_for_capture()
        try:
            return driver.screenshot(keep_full=True)
        finally:
            self.ui.show_after_capture()

    def next_event(self, timeout: float):
        """Next transcript / button from the user, or None after timeout."""
        try:
            ev = self._inbox.get(timeout=timeout)
        except queue.Empty:
            return None
        self._check()
        return ev

    def ask_choice(self, question: str, options: list[str], timeout: float = 120) -> str:
        """A question with answer buttons; the user clicks one or just says the answer."""
        self._say(question, "hold", [f"opt:{o}" for o in options[:4]])
        while True:
            ev = self.next_event(timeout)
            if ev is None:
                return ""
            kind, val = ev
            if kind == "button" and val.startswith("opt:"):
                return val[4:]
            if kind == "button" and val == "close":
                return ""
            if kind == "say":
                return val

    def ask_yes(self, question: str, timeout: float = 120) -> bool | str:
        """True / False, or the user's words if they said something else (e.g. a change request)."""
        self._say(question, "hold", ["yes", "no"])
        while True:
            ev = self.next_event(timeout)
            if ev is None:
                return False
            kind, val = ev
            if kind == "button" and val in ("yes", "no", "close"):
                return val == "yes"
            if kind == "say":
                from zavero.orchestrator import classify  # same yes / no words as everywhere else
                c = classify(val)
                return True if c in ("yes", "do") else False if c in ("no", "stop") else val

    # --- the flow ----------------------------------------------------------------
    def run(self, text: str) -> None:
        lg = lang(text)
        title = driver.active_window_title()
        found = self.knowledge(text, title, lg)
        g = {"id": uuid.uuid4().hex[:8], "goal": text, "lang": lg, "title": title,
             "skills": [s.slug for s in found], "answers": {}, "step": 0, "done": False, "log": []}
        skill_text = skills.as_context(found) or "(none)"
        g["answers"] = self.ask_details(text, skill_text, lg)
        g["plan"] = self.make_plan(g, skill_text)
        self.goals.save(g)
        self._run_goal(g)

    def knowledge(self, goal: str, title: str, lg: str) -> list[skills.Skill]:
        """Matching skills; research and write one when there is none or it is too old."""
        found = skills.match(goal, title, self.skill_dir)
        if found and not found[0].stale:
            return found
        self._say(self._t("reading", lg), "info")
        try:
            learned = research.learn(goal, title)
        except Exception as e:  # noqa: BLE001 - old notes (or none) still let us guide
            actionlog.log("research_error", error=str(e))
            learned = None
        self._check()
        if learned:
            actionlog.log("skill_written", slug=learned.slug, sources=learned.sources)
            return [learned] + [s for s in found if s.slug != learned.slug][:skills.MAX_SKILLS - 1]
        return found

    def ask_details(self, goal: str, skill_text: str, lg: str) -> dict:
        data = self.model(DETAILS_SYSTEM.replace("{goal}", goal).replace("{skill}", skill_text[:3000])
                          .replace("{lang}", LANG_NAMES[lg]), goal)
        answers = {}
        for q in (data.get("questions") or [])[:5]:
            if not isinstance(q, dict) or not q.get("q"):
                continue
            opts = [str(o)[:24] for o in q.get("options") or [] if str(o).strip()]
            answers[str(q["q"])] = self.ask_choice(str(q["q"]), opts) or "-"
        return answers

    def make_plan(self, g: dict, skill_text: str) -> dict:
        lg = g["lang"]
        base = (PLAN_SYSTEM.replace("{goal}", g["goal"]).replace("{answers}", json.dumps(g["answers"], ensure_ascii=False))
                .replace("{title}", g["title"] or "-").replace("{skill}", skill_text[:4000]).replace("{lang}", LANG_NAMES[lg]))
        plan = clean_plan(self.model(base, g["goal"]))
        for _ in range(3):  # show it; the user can change it by voice
            listing = "\n".join(f"{i}. {s['title']}" for i, s in enumerate(plan["steps"], 1))
            reply = self.ask_yes(f"**{plan['title']}**\n{listing}\n\n{self._t('start_q', lg)}")
            if reply is True:
                return plan
            if reply is False:
                raise Cancelled
            extra = REVISE_ADD.replace("{change}", reply).replace("{plan}", json.dumps(plan, ensure_ascii=False))
            plan = clean_plan(self.model(base + extra, reply))
        return plan

    def _run_goal(self, g: dict) -> None:
        lg, steps = g["lang"], g["plan"]["steps"]
        skill_text = skills.as_context([s for s in skills.load_all(self.skill_dir) if s.slug in g.get("skills", [])])
        while g["step"] < len(steps):
            self._check()
            n = g["step"] + 1
            self.ui.set_mode.emit(f"Coach · {n}/{len(steps)}")
            result = self.run_step(g, steps[g["step"]], n, skill_text)
            if result == "paused":
                self._say(self._t("paused", lg, step=self._t("step", lg, n=n, total=len(steps))), "info")
                return
            g["log"].append({"step": steps[g["step"]]["title"], **result})
            g["step"] += 1
            self.goals.save(g)
        self.finish(g)

    def run_step(self, g: dict, step: dict, n: int, skill_text: str) -> dict:
        """Guide one plan step until the screen shows it worked (max MAX_TRIES). Returns what happened."""
        lg, total = g["lang"], len(g["plan"]["steps"])
        retry, mistakes = "", []
        for _ in range(MAX_TRIES):
            self._check()
            shot = self.screenshot()
            system = (STEP_SYSTEM.replace("{goal}", g["goal"]).replace("{answers}", json.dumps(g["answers"], ensure_ascii=False))
                      .replace("{skill}", skill_text[:4000] or "(none)").replace("{n}", str(n)).replace("{total}", str(total))
                      .replace("{step}", step["title"]).replace("{why}", step["why"]).replace("{retry}", retry)
                      .replace("{lang}", LANG_NAMES[lg]))
            st = clean_step(self.model(system, step["title"], shot), shot.width, shot.height)
            if st["x"] is not None and st["action"] in ("click", "double_click", "choose", "type", "drag", "scroll"):
                better = talk.refine_point(shot, {"x": st["x"], "y": st["y"]}, st["label"] or step["title"])
                st["x"], st["y"] = better["x"], better["y"]  # zoomed second look: lands exactly on it
            self._last_shot = shot
            if st["action"] == "done_already":
                return {"ok": True, "mistakes": mistakes}
            if st["risky"] and not self.approve(st, lg):
                raise Cancelled
            how = self.show_and_wait(st, step, shot, n, total, lg)
            if how == "paused":
                return "paused"
            if how == "skip":
                return {"ok": True, "skipped": True, "mistakes": mistakes}
            if how == "do":
                self.do_step(st, shot)
            self.pause(1.0)  # let the screen update
            self._check()
            after = self.screenshot()
            check = self.model(CHECK_SYSTEM.replace("{step}", step["title"]).replace("{expect}", st["say"])
                               .replace("{lang}", LANG_NAMES[lg]), step["title"], after)
            self.ui.show_keys.emit([])
            if check.get("ok"):
                self._say(f"✅ {check.get('what_happened', '')}".strip(), "done")
                return {"ok": True, "mistakes": mistakes}
            fix = str(check.get("fix") or "")
            mistakes.append(f"{check.get('what_happened', '')} -> {fix}")
            self._say(f"🙂 {check.get('what_happened', '')}\n{fix}".strip(), "warn")
            retry = f"The last try did not work: {check.get('what_happened', '')}. Fix: {fix}\n"
            self.pause(2.5)
        self._say(self._t("moving_on", lg), "info")
        return {"ok": False, "mistakes": mistakes}

    def approve(self, st: dict, lg: str) -> bool:
        what = st["label"] or st["say"]
        if st["x"] is not None:
            self.ui.point_at.emit(*driver.to_screen(st["x"], st["y"], self._last_shot))
        ok = self.ask_yes(self._t("risky", lg, what=f"(**{what}**)") + "\n" + st["say"]) is True
        actionlog.log("coach_approval", label=what, approved=ok)
        return ok

    def show_and_wait(self, st: dict, step: dict, shot, n: int, total: int, lg: str) -> str:
        """Show the right guide for the action and wait. Returns 'done' | 'do' | 'skip' | 'paused'."""
        self._last_shot = shot
        a = st["action"]
        head = f"**{self._t('step', lg, n=n, total=total)}** · {step['title']}"
        body = st["say"]
        if st["why_choice"]:
            body += f"\n💡 {st['why_choice']}"
        elif step["why"]:
            body += f"\n💡 {step['why']}"
        if st["x"] is not None and a not in ("key", "look"):
            target = driver.to_screen(st["x"], st["y"], shot)
            self.ui.point_at.emit(*target)
            self.ui.set_label.emit(st["label"] or "👆")
        if a == "key":
            self.ui.show_keys.emit([key_label(k) for k in st["keys"]])
        elif a == "drag":
            self.ui.show_arrow.emit(*driver.to_screen(st["x"], st["y"], shot), *driver.to_screen(*st["to"], shot))
        elif a == "scroll":
            x, y = driver.to_screen(st["x"], st["y"], shot)
            self.ui.show_arrow.emit(x, y, x, y + (-160 if st["scroll"] == "up" else 160))
        elif a == "type" and st["text"] and not st["secret"]:
            body += f"\n{self._t('type_this', lg)} **{st['text']}**"
        if st["secret"]:
            body += "\n" + self._t("secret", lg)
        if st["tiny"] and st["x"] is not None and shot.full is not None:  # zoomed copy of a tiny icon
            bx, by = max(0, st["x"] - 80), max(0, st["y"] - 50)
            self.ui.show_board.emit(driver.crop_png(shot, bx, by, 160, 100), [], st["x"] / shot.width)
        buttons = ["next"] if st["secret"] else ["do", "next"] + (["copy"] if a == "type" else [])
        self._say(f"{head}\n{body}", "hold", buttons)
        actionlog.log("coach_step", n=n, action=a, label=st["label"])
        how = self.wait_for(st, shot)
        self.ui.hide_board.emit()
        if how == "do" and st["secret"]:
            how = self.wait_for({**st, "action": "look"}, shot)  # secrets: the user types them, never Zavero
        return how

    def wait_for(self, st: dict, shot) -> str:
        """Wait until the user does the action (exact keys, a click, a drag, a scroll, Enter after typing),
        presses Done / Do it for me, or says next / do it."""
        done = threading.Event()
        listeners = []
        a = st["action"]
        if a in ("click", "double_click", "choose"):
            from pynput import mouse

            def on_click(x, y, button, pressed):
                if pressed and not self.ui.is_on_bubble_button(x, y) and not self.ui.is_on_avatar(x, y):
                    done.set()
            listeners.append(mouse.Listener(on_click=on_click))
        elif a == "drag":
            from pynput import mouse
            start = {}

            def on_drag(x, y, button, pressed):
                if pressed:
                    start["p"] = (x, y)
                elif "p" in start and math.dist(start["p"], (x, y)) > 30:
                    done.set()
            listeners.append(mouse.Listener(on_click=on_drag))
        elif a == "scroll":
            from pynput import mouse
            listeners.append(mouse.Listener(on_scroll=lambda *args: done.set()))
        elif a in ("key", "type"):
            from pynput import keyboard
            down: set[str] = set()
            want = st["keys"] if a == "key" else ["enter"]

            def on_press(k):
                down.add(pynput_name(k))
                if keys_match(down, want):
                    done.set()
            listeners.append(keyboard.Listener(on_press=on_press, on_release=lambda k: down.discard(pynput_name(k))))
        for lis in listeners:
            lis.start()
        try:
            deadline = time.monotonic() + WAIT_S
            while not done.is_set():
                left = deadline - time.monotonic()
                if left <= 0:
                    return "paused"
                ev = self.next_event(min(0.25, left))
                if ev is None:
                    continue
                kind, val = ev
                if kind == "button":
                    if val == "next":
                        return "done"
                    if val == "do":
                        return "do"
                    if val == "close":
                        self._check()
                if kind == "say":
                    from zavero.orchestrator import classify
                    c = classify(val)
                    if c == "do":
                        return "do"
                    if c in ("next", "yes"):
                        return "done"
                    if re.search(r"\bskip\b|vadili|chhod", val.lower()):
                        return "skip"
            return "done"
        finally:
            for lis in listeners:
                lis.stop()

    def do_step(self, st: dict, shot) -> None:
        """"Do it for me": Zavero performs this one step. Never types secrets."""
        acts = to_actions(st)
        if st["secret"] or safety.secret_reason(st["say"], acts):
            return
        for act in acts:
            self._check()
            driver.execute(act, shot)
            actionlog.log("coach_action", **act)
            self.pause(0.2)

    def finish(self, g: dict) -> None:
        lg = g["lang"]
        g["done"] = True
        self.goals.save(g)
        self._say(self._t("finished", lg, title=g["plan"]["title"]), "done")
        actionlog.log("coach_finished", goal=g["goal"], steps=len(g["plan"]["steps"]))
        for f in g["plan"].get("follow_ups", []):
            if self.ask_yes(self._t("remind", lg, days=f["days"], title=f["title"])) is True:
                when = (datetime.now() + timedelta(days=f["days"])).replace(hour=10, minute=0, second=0, microsecond=0)
                self.o.reminders.add(f["title"], when.isoformat(timespec="minutes"))
        if g.get("skills"):
            try:
                log = json.dumps(g["log"], ensure_ascii=False)[:4000]
                lines = self.model(LEARN_SYSTEM.replace("{goal}", g["goal"]).replace("{log}", log), g["goal"]).get("lines", [])
                skills.append_learned(g["skills"][0], [str(x) for x in lines][:6], self.skill_dir)
            except Exception as e:  # noqa: BLE001 - learning is a bonus
                actionlog.log("coach_learn_error", error=str(e))
