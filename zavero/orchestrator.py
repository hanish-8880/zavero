"""Ties voice -> brain -> overlay -> driver together and holds session state."""
import datetime
import re
import threading
import time

from pynput import keyboard, mouse

from zavero import actionlog, briefing, config, driver, narrator, reminders, safety, talk
from zavero.phrases import lang, phrase
from zavero.brain import Brain, Step

# Short spoken commands. Matched as whole words/phrases after lowercasing.
WORDS = {
    "stop": ["stop", "aagu", "aapu", "aapandi", "ruko", "ruk", "bas", "ఆగు", "ఆపు", "ఆపండి", "రుకో", "रुको", "रुक", "बस"],
    "no": ["no", "nope", "nahi", "nahin", "vaddu", "oddu", "cancel", "don't", "వద్దు", "కాదు", "नहीं", "नही", "मत"],
    "do": ["do it", "you do it", "you do", "do for me", "do it for me", "please do", "you can do",
           "chey", "cheyyi", "cheyi", "nuvve chey", "chesey", "naku chey", "kar do", "karo", "aap karo", "tum karo",
           "kar dijiye", "mere liye kar", "చెయ్", "చెయ్యి", "చేయి", "చేసెయ్", "చేసేయ్", "చేయండి", "నువ్వే చెయ్",
           "కర్ దో", "कर दो", "करो", "कर दीजिए", "आप करो"],
    "yes": ["yes", "yeah", "yep", "ok", "okay", "sure", "haan", "haa", "han", "ha", "avunu", "avnu", "sare",
            "theek hai", "thik hai", "అవును", "సరే", "హా", "హాం", "ఓకే", "हाँ", "हां", "हा", "ठीक है", "ओके",
            "send", "send it", "pampu", "pampandi", "bhejo", "bhej do", "పంపు", "పంపండి", "भेजो", "भेज दो"],
    "next": ["next", "done", "ayindi", "aipoyindi", "ho gaya", "hogaya", "అయింది", "అయ్యింది", "అయిపోయింది", "हो गया"],
}


def _norm(text: str) -> str:
    # Only strip punctuation; \W would also strip Telugu/Hindi vowel signs.
    return " " + " ".join(re.sub(r"[.,!?।॥\"'“”‘’]", " ", text.lower()).split()) + " "


def classify(text: str) -> str:
    """Return 'stop' | 'no' | 'do' | 'yes' | 'next' | 'task'. Commands only count in short phrases."""
    n = _norm(text)
    short = len(n.split()) <= 4
    has = lambda k: any(f" {w} " in n for w in WORDS[k])  # noqa: E731
    if short and has("stop"):
        return "stop"
    if short and has("no"):
        return "no"
    if has("do"):
        return "do"
    if short and has("yes"):
        return "yes"
    if short and has("next"):
        return "next"
    return "task"


class Cancelled(Exception):
    pass


class GuideEnded(Exception):
    """The user stopped following the guide (walked away or is doing something else)."""


class Orchestrator:
    """One task at a time. Guide mode by default; 'do it' switches to do mode."""

    def __init__(self, ui) -> None:
        self.ui = ui
        self.mode = "guide"
        self.user_text = ""
        self._worker: threading.Thread | None = None
        self._cancel = threading.Event()
        self._acted = threading.Event()      # guide mode: user did the step (or said "do it")
        self._waiting = False
        self._asking = False
        self._answer: bool | None = None
        self._answered = threading.Event()
        self._say_seq = 0
        self._guide_target: tuple[int, int] | None = None
        self._off_target = False
        self._strikes = 0
        self.reminders = reminders.Reminders()
        self.gmail = None  # Gmail API client, set by main.py when Gmail is connected
        self.lang = briefing.load_state().get("lang", "en")  # user's language, remembered across runs
        mouse.Listener(on_click=self._on_click).start()
        keyboard.Listener(on_press=self._on_key).start()

    @property
    def busy(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    # --- inputs ---------------------------------------------------------
    def on_transcript(self, text: str) -> None:
        """Called with each final transcript from voice.py."""
        intent = classify(text)
        actionlog.log("heard", text=text, intent=intent)
        if not self._asking:
            self.ui.hide_board.emit()  # a new request closes the enlarged diagram
        if len(_norm(text).split()) > 2 and lang(text) != self.lang:
            self.lang = lang(text)
            briefing.save_state(lang=self.lang)
        if self._asking:
            if intent in ("yes", "do", "no", "stop"):
                self._answer = intent in ("yes", "do")
                self._answered.set()
            if intent == "stop":
                self.stop()
            return
        if intent == "stop":
            self.stop()
            return
        if reminders.is_reminder(text):  # handled on the side; a running guide keeps going
            threading.Thread(target=self._remind, args=(text,), daemon=True).start()
            return
        if briefing.is_briefing(text) and not self.busy:
            threading.Thread(target=self.brief, daemon=True).start()
            return
        if talk.is_question(text):  # "what is this?" -> quick answer; a running guide keeps going
            threading.Thread(target=self._talk, args=(text,), daemon=True).start()
            return
        if self.busy:
            if intent == "do":  # "do it" / "you do for me ..." mid-task: same task, Zavero takes over
                self._remember("user", text)
                self.mode = "do"
                self.ui.set_mode.emit("Doing")
                self._acted.set()
                return
            if intent == "next":
                self._acted.set()
                return
            if intent in ("yes", "no", "do") or len(_norm(text).split()) <= 3:
                return  # stray "okay" / "haan" while working: ignore
            self.stop()
            self._worker.join(5)
        if intent == "do" and len(_norm(text).split()) <= 4:
            if not self.user_text:
                self._say("Tell me what you want to do first.", "info")
                return
            self.start(self.user_text, "do")  # "do it" after a guided task -> redo it for them
            return
        self.start(text, "do" if intent == "do" or self._answers_do_question() else "guide")

    def _answers_do_question(self) -> bool:
        """True if Zavero just finished a do-mode task by asking something: the reply keeps do mode."""
        return (self.mode == "do" and getattr(self, "_asked_at", None) is not None
                and time.monotonic() - self._asked_at < 300)

    def _on_click(self, x, y, button, pressed) -> None:
        if pressed and self._waiting and not self.ui.is_on_avatar(x, y):  # dragging Chai is not a step
            t = self._guide_target
            self._off_target = bool(t) and (x - t[0]) ** 2 + (y - t[1]) ** 2 > config.CLICK_RADIUS ** 2
            self._acted.set()

    def _on_key(self, key) -> None:
        if key == keyboard.Key.esc:
            self.ui.hide_board.emit()
        if key == keyboard.Key.esc and self.busy:
            self.stop()
        elif key == keyboard.Key.enter and self._waiting:
            self._acted.set()

    def stop(self) -> None:
        """Cancel the running task right away."""
        if self.busy:
            self._cancel.set()
            self._acted.set()
            self._answered.set()
            # React right away; the worker may still be waiting for the model for a few seconds.
            self.ui.go_home.emit()
            self.ui.set_thinking.emit(False)
            self._say(phrase("stopped", self.user_text), "done")

    def start(self, text: str, mode: str) -> None:
        self.user_text = text
        self.mode = mode
        self._cancel.clear()
        self._strikes = 0
        task = self._with_context(text)  # earlier turns, so "APSPDCL" answers "which company?"
        self._remember("user", text)
        self._worker = threading.Thread(target=self._run, args=(task,), daemon=True)
        self._worker.start()

    # --- short conversation memory ---------------------------------------
    MEMORY_S = 15 * 60  # what was said in the last 15 minutes counts as the same conversation

    def _remember(self, who: str, text: str) -> None:
        now = time.monotonic()
        self._history = [h for h in getattr(self, "_history", []) if now - h[0] < self.MEMORY_S][-7:]
        self._history.append((now, who, text))

    def _with_context(self, text: str) -> str:
        """The new request, with the recent conversation in front of it."""
        now = time.monotonic()
        recent = [h for h in getattr(self, "_history", []) if now - h[0] < self.MEMORY_S]
        if not recent:
            return text
        lines = [f"{'User' if who == 'user' else 'You (Zavero)'}: {t}" for _, who, t in recent]
        return ("Earlier in this conversation (oldest first):\n" + "\n".join(lines)
                + f"\n\nThe user now says: {text}")

    # --- "what is this?" ---------------------------------------------------
    def _talk(self, text: str) -> None:
        """Quick answer about the screen, pointing at the thing it explains."""
        draw = talk.is_diagram(text)
        error = not draw and talk.is_error(text)
        self.ui.set_mode.emit("Diagram" if draw else "Error" if error else "Explain")
        mouse_at = tuple(int(v) for v in mouse.Controller().position)
        try:
            self.ui.hide_for_capture()
            try:
                shot = driver.screenshot(keep_full=draw)  # full resolution kept for a sharp enlarged copy
            finally:
                self.ui.show_after_capture()
            res = self._think(lambda: talk.answer(self._with_context(text), shot, mouse_at, lang(text), draw, error))
        except Exception as e:  # noqa: BLE001
            actionlog.log("talk_error", text=text, error=str(e))
            self._say(f"Sorry, I couldn't look at your screen:\n{e}", "error")
            return
        reply = res["answer"]
        if res["region"]:
            r = res["region"]
            side = (r["x"] + r["w"] / 2) / shot.width
            self.ui.show_board.emit(driver.crop_png(shot, r["x"], r["y"], r["w"], r["h"]), res["steps"], side)
            reply += "\n" + "\n".join(f"**{i}. {s['label']}** – {s['detail']}" for i, s in enumerate(res["steps"], 1))
        elif res["point"]:
            self.ui.point_at.emit(*driver.to_screen(res["point"]["x"], res["point"]["y"], shot))
        self._remember("user", text)
        self._remember("zavero", reply)
        actionlog.log("talk", question=text, answer=reply, point=res["point"], region=res["region"])
        self._say(reply, "info")
        if res.get("goto"):
            self._open_line(res["goto"], reply, lang(text))

    def _open_line(self, goto: dict, error: str, user_lang: str) -> None:
        """Jump to the broken line in VS Code, point at it and say exactly what to change."""
        file, line = goto["file"], goto["line"]
        time.sleep(2.5)  # let the user read the first explanation
        if not driver.open_in_editor(file, line):
            self._say(f"{error}\n\n👉 Open **{file}** and go to line **{line}** (Ctrl+G).", "info")
            return
        actionlog.log("goto_line", file=file, line=line)
        self._say(f"➡️ **{file}** · line **{line}**", "info")
        time.sleep(1.0)  # let the editor scroll there
        try:
            shot = self._screenshot()
            res = self._think(lambda: talk.explain_line(shot, file, line, error, user_lang))
        except Exception as e:  # noqa: BLE001 - the first explanation is already on screen
            actionlog.log("talk_error", text=f"line {line}", error=str(e))
            return
        if res.get("point"):
            self.ui.point_at.emit(*driver.to_screen(res["point"]["x"], res["point"]["y"], shot))
        self._remember("zavero", res.get("answer", ""))
        self._say(f"**{file} · line {line}**\n{res.get('answer', '')}", "info")

    # --- "what matters today?" -------------------------------------------
    def brief(self) -> None:
        """Short briefing: at most 3 things that matter, from reminders + unread Gmail."""
        self.ui.set_mode.emit("Today")
        try:
            facts = self._think(lambda: briefing.gather(self.reminders, self.gmail))
            text = self._think(lambda: briefing.write(facts, self.lang))
        except Exception as e:  # noqa: BLE001
            actionlog.log("briefing_error", error=str(e))
            self._say(f"Sorry, I couldn't make your briefing:\n{e}", "error")
            return
        briefing.save_state(last_brief=datetime.date.today().isoformat())
        actionlog.log("briefing", text=text)
        self.ui.attention.emit()
        self._say(text, "info")

    # --- reminders ------------------------------------------------------
    def _remind(self, text: str) -> None:
        """Save a reminder / important date, or list the upcoming ones."""
        self.ui.set_mode.emit("Reminder")
        try:
            r = self._think(lambda: reminders.parse(text))
        except Exception as e:  # noqa: BLE001 - tell the user, never crash the voice thread
            actionlog.log("reminder_error", text=text, error=str(e))
            self._say(phrase("remind_fail", text), "warn")
            return
        if r.get("action") == "add":
            item = self.reminders.add(r.get("title", text), r["when"], r.get("repeat", "none"), r.get("alert", ""))
            actionlog.log("reminder_added", **item)
            self._say(f"{r.get('confirm', '')}\n🗓 {reminders.pretty(item['when'])}".strip(), "done")
        elif r.get("action") == "list":
            items = self.reminders.upcoming()
            lines = [f"• **{reminders.pretty(it['when'])}** · {it['title']}" for it in items]
            self._say("\n".join(lines) if lines else phrase("no_reminders", text), "info")
        else:
            self._say(phrase("remind_fail", text), "warn")

    # --- the loop -------------------------------------------------------
    def _run(self, task: str) -> None:
        ui = self.ui
        said = self.user_text  # the user's latest words: decides the bubble language
        self._set_step(1)
        self._say(phrase("looking", said), "info")
        actionlog.log("task", text=task, mode=self.mode)
        brain = Brain(task)
        try:
            shot = self._screenshot()
            result = self._think(lambda: brain.start(shot))
            while isinstance(result, Step):
                self._check()
                if brain.steps > config.MAX_STEPS:
                    ui.go_home.emit()
                    self._say("This is taking too many steps, so I stopped. Please try a smaller task.", "warn")
                    return
                step = result
                acked = self._guide(step, shot) if self.mode == "guide" else None
                if acked is None:  # do mode (or user switched to do mid-step)
                    acked = self._do(step, shot)
                time.sleep(1.0)  # let the screen update
                self._check()
                shot = self._screenshot()
                result = self._think(lambda: brain.next(step, shot, acked))
                self._set_step(brain.steps)
            ui.go_home.emit()
            self._remember("zavero", result)
            self._asked_at = time.monotonic() if "?" in result else None  # ended with a question for the user
            self._say(self._think(lambda: narrator.narrate("final", said, result)), "done")
            actionlog.log("finished", text=result)
        except Cancelled:
            ui.go_home.emit()
            self._remember("zavero", "(the user stopped this task)")
            self._say(phrase("stopped", said), "done")
            actionlog.log("stopped")
        except GuideEnded as e:
            ui.go_home.emit()
            self._remember("zavero", f"(guide paused: {e})")
            note = ("The user stopped following the steps, so you paused the guide. "
                    "Tell them kindly to hold Right Ctrl whenever they need help again.")
            self._say(narrator.narrate("final", said, note), "done")
            actionlog.log("guide_ended", reason=str(e))
        except Exception as e:  # noqa: BLE001 - show every problem to the user
            ui.go_home.emit()
            self._say(f"Sorry, something went wrong:\n{e}", "error")
            actionlog.log("error", error=str(e))
        finally:
            ui.set_thinking.emit(False)
            self._waiting = self._asking = False
            actionlog.log("tokens", input=brain.tokens_in, output=brain.tokens_out, steps=brain.steps)

    def _think(self, fn):
        """Run a slow model call with the avatar's thinking dots on."""
        self.ui.set_thinking.emit(True)
        try:
            return fn()
        finally:
            self.ui.set_thinking.emit(False)

    def _set_step(self, n: int) -> None:
        self.ui.set_mode.emit(f"{'Doing' if self.mode == 'do' else 'Guide'} · Step {n}")

    def _screenshot(self):
        """Model screenshot with the avatar blanked out for a moment."""
        self.ui.hide_for_capture()
        try:
            return driver.screenshot()
        finally:
            self.ui.show_after_capture()

    def _check(self) -> None:
        if self._cancel.is_set():
            raise Cancelled

    def _target(self, step: Step, shot) -> tuple[int, int] | None:
        """Real-screen point of the first action that has coordinates."""
        get = driver._get
        for a in step.actions:
            x, y = get(a, "x"), get(a, "y")
            path = get(a, "path")
            if x is None and path:
                x, y = get(path[0], "x"), get(path[0], "y")
            if x is not None and y is not None:
                return driver.to_screen(x, y, shot)
        return None

    def _guide(self, step: Step, shot) -> list | None:
        """Show the user what to do and wait for them. Returns acked checks, or None to switch to do mode."""
        if all(getattr(a, "type", "") in ("wait", "screenshot", "move") for a in step.actions):
            for a in step.actions:
                driver.execute(a, shot)
            return []
        self._check()  # "stop" may have come while the model was thinking
        target = self._target(step, shot)
        if target:
            self.ui.point_at.emit(*target)
        text = self._think(lambda: narrator.narrate("guide", self.user_text, step.text, step.actions))
        self._check()
        self._say(text, "info")
        actionlog.log("guide", note=step.text, bubble=text, target=target)
        self._guide_target = target
        self._off_target = False
        self._acted.clear()
        self._waiting = True
        acted = self._acted.wait(config.GUIDE_IDLE_S)
        self._waiting = False
        self._guide_target = None
        self._check()
        if self.mode == "do":
            return None
        if not acted:
            raise GuideEnded("no response")
        # Clicks far from the ring mean the user is busy with something else.
        self._strikes = self._strikes + 1 if self._off_target else 0
        if self._strikes >= 2:
            raise GuideEnded("clicked elsewhere twice")
        if self._off_target:
            self._say(phrase("oops", self.user_text), "warn")
        elif target:
            self._say(phrase("great", self.user_text), "done")
        # The user did this step with their own hands, so they have approved it.
        return step.safety_checks

    def _do(self, step: Step, shot) -> list:
        """Run the step ourselves, asking first if it is risky."""
        ui = self.ui
        secret = safety.secret_reason(step.text, step.actions)
        if secret:
            self._say(narrator.narrate("handoff", self.user_text, step.text, step.actions, secret), "warn")
            actionlog.log("handoff", reason=secret, note=step.text)
            self._acted.clear()
            self._waiting = True
            self._acted.wait()
            self._waiting = False
            self._check()
            return step.safety_checks
        # The API flags every action with the generic code below. The user's "do it" is their OK for
        # those; anything else (risky words, other check codes) still needs a spoken yes.
        reason = safety.risky_reason(step.text, step.actions)
        special = [c for c in step.safety_checks if c.get("code") != safety.GENERIC_CHECK]
        if not reason and special:
            reason = special[0].get("message") or "the system flagged this step"
        if not reason and step.safety_checks:
            actionlog.log("auto_ack", reason="user said do it", checks=[c["code"] for c in step.safety_checks])
        target = self._target(step, shot)
        if reason:
            if target:
                ui.point_at.emit(*target)
            question = narrator.narrate("confirm", self.user_text, step.text, step.actions, reason)
            if not self._ask(question):
                raise Cancelled
            actionlog.log("approved", reason=reason, note=step.text)
        if target:
            ui.point_at.emit(*target)
        self._say_async("do", step)  # write the bubble while we click, not before
        time.sleep(0.6)  # let the avatar fly there first
        for a in step.actions:
            self._check()
            kind = getattr(a, "type", "")
            if kind in ("click", "double_click") and target:
                ui.tap_at.emit(*driver.to_screen(a.x, a.y, shot))
            driver.execute(a, shot)
            actionlog.log("action", **a.model_dump())
            time.sleep(0.15)
        return step.safety_checks

    def _say(self, text: str, mood: str) -> None:
        """Show bubble text and invalidate any older async narration still in flight."""
        self._say_seq += 1
        self.ui.show_text.emit(text, mood)

    def _say_async(self, kind: str, step: Step) -> None:
        """Narrate in the background; drop the result if something newer was shown meanwhile."""
        self._say_seq += 1
        seq = self._say_seq

        def work() -> None:
            text = narrator.narrate(kind, self.user_text, step.text, step.actions)
            if seq == self._say_seq:
                self.ui.show_text.emit(text, "info")

        threading.Thread(target=work, daemon=True).start()

    def ask(self, question: str, timeout: float = 120) -> bool:
        """Ask a yes/no question in the bubble; the user answers by voice. No answer = no."""
        self._say(question, "warn")
        self._answer = None
        self._answered.clear()
        self._asking = True
        self._answered.wait(timeout)
        self._asking = False
        return bool(self._answer)

    @property
    def idle(self) -> bool:
        """Nothing running and no question open: a good moment to interrupt (e.g. urgent email)."""
        return not self.busy and not self._asking

    def _ask(self, question: str) -> bool:
        answer = self.ask(question)
        self._check()
        return answer
