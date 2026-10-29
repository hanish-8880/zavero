"""Ties voice -> brain -> overlay -> driver together and holds session state."""
import datetime
import json
import queue
import re
import threading
import time

from pynput import keyboard, mouse

from zavero import actionlog, briefing, coach, config, driver, narrator, onboarding, reminders, safety, talk, writer
from zavero.phrases import friendly_error, lang, phrase, point_label
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
    "next": ["next", "next step", "inka", "aage", "ఇంకా", "తర్వాత", "आगे", "done", "ayindi", "aipoyindi", "ho gaya", "hogaya", "అయింది", "అయ్యింది", "అయిపోయింది", "हो गया"],
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
        self._talk_seq = 0  # bumped on every hotkey press: older quick answers still in flight are dropped
        self._guide_target: tuple[int, int] | None = None
        self._off_target = False
        self._strikes = 0
        self.reminders = reminders.Reminders()
        self.coach = coach.Coach(self)
        self.gmail = None  # Gmail API client, set by main.py when Gmail is connected
        self.lang = briefing.load_state().get("lang", "en")  # user's language, remembered across runs
        mouse.Listener(on_click=self._on_click).start()
        keyboard.Listener(on_press=self._on_key).start()

    @property
    def busy(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    # --- inputs ---------------------------------------------------------
    def on_press(self) -> None:
        """Hotkey went down: the user is interrupting. Drop older answers; Chai stops pointing."""
        self._talk_seq += 1
        if not self.busy:  # a running guide keeps its target
            self.ui.go_home.emit()
            threading.Thread(target=self._prefetch, daemon=True).start()

    PREFETCH_S = 20  # a screenshot taken at key-press is used for quick answers if it's this fresh

    def _prefetch(self) -> None:
        """Capture the screen while the user is still talking, so the answer comes sooner."""
        try:
            self.ui.hide_for_capture()
            try:
                self._prefetched = (time.monotonic(), driver.screenshot(keep_full=True))
            finally:
                self.ui.show_after_capture()
        except Exception as e:  # noqa: BLE001 - _talk will just capture again
            actionlog.log("prefetch_error", error=str(e))

    def _take_prefetched(self):
        """The key-press screenshot if it is fresh, else None. Used once."""
        got, self._prefetched = getattr(self, "_prefetched", None), None
        if got and time.monotonic() - got[0] < self.PREFETCH_S:
            return got[1]
        return None

    def on_transcript(self, text: str) -> None:
        """Called with each final transcript from voice.py."""
        intent = classify(text)
        actionlog.log("heard", text=text, intent=intent)
        if self._onboard_q is not None:  # first-run hello: everything the user says goes to it
            self._onboard_q.put(text)
            return
        if self.coach.active:  # a Guide-anything goal is running: it gets every answer
            if intent == "stop":
                self.stop()
            else:
                self.coach.feed(text)
            return
        loop = self._circled()
        if loop and intent not in ("stop", "no") and not self._asking:  # circled a part while asking
            threading.Thread(target=self._talk_circle, args=(text, loop), daemon=True).start()
            return
        if self.ui.is_3d_open and intent in ("next", "yes") and not self._asking:
            self.ui.next_3d.emit()  # "next" / "inka" / "aage": next step of the 3D model
            return
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
        if self._feedback_next or re.search(actionlog.FEEDBACK_WORDS, text.lower()):
            self._feedback_next = False
            actionlog.feedback(text)
            self._say(phrase("feedback_thanks", text), "done")
            return
        platform = writer.platform_of(text)
        if platform and not self.busy:  # "post this on LinkedIn": write it, show it, post only after a yes
            threading.Thread(target=self._post, args=(text, platform), daemon=True).start()
            return
        if briefing.is_briefing(text) and not self.busy:
            threading.Thread(target=self.brief, daemon=True).start()
            return
        if not self.busy and coach.is_continue(text):  # "continue": resume the last unfinished goal
            self.coach.resume()
            return
        if not self.busy and coach.is_goal(text):  # "teach me ..." / "I want to ...": plan + guided steps
            self.coach.start(text)
            return
        if talk.is_3d(text) and not self.busy:  # "heart ni 3D lo explain chey": a rotating 3D model
            threading.Thread(target=self._talk3d, args=(text,), daemon=True).start()
            return
        if talk.is_question(text):  # "what is this?" -> quick answer; a running guide keeps going
            threading.Thread(target=self._talk, args=(text,), daemon=True).start()
            return
        if self.busy:
            if intent == "do":  # "do it" / "you do for me ..." mid-task: same task, Zavero takes over
                self._take_over(text)
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

    _feedback_next = False

    @property
    def _zavero_acting(self) -> bool:
        """Do mode is clicking/typing itself: those events must not dismiss its own bubbles."""
        return self.busy and self.mode == "do"
    _onboard_q: queue.Queue | None = None

    def onboard(self) -> None:
        """Run the first-run hello (also tray -> Replay onboarding)."""
        if self._onboard_q is not None or self.busy:
            return
        self._onboard_q = queue.Queue()

        def work() -> None:
            try:
                onboarding.run(self, self._onboard_q)
            except Exception as e:  # noqa: BLE001
                actionlog.log("onboarding_error", error=str(e))
            finally:
                self._onboard_q = None

        threading.Thread(target=work, daemon=True).start()

    def ask_feedback(self) -> None:
        """Tray "Send feedback": the next thing the user says is saved as a bug report."""
        self._feedback_next = True
        self._say(phrase("feedback_ask", self.user_text), "hold")

    def _answers_do_question(self) -> bool:
        """True if Zavero just finished a do-mode task by asking something: the reply keeps do mode."""
        return (self.mode == "do" and getattr(self, "_asked_at", None) is not None
                and time.monotonic() - self._asked_at < 300)

    def _on_click(self, x, y, button, pressed) -> None:
        if not pressed or self.ui.is_on_avatar(x, y) or self.ui.is_on_bubble_button(x, y):
            return  # dragging Chai or pressing a bubble button is not a guide step
        if not self._zavero_acting:
            self.ui.dismiss.emit()  # overlay keeps "hold" bubbles (guide steps, questions)
        if self._waiting:
            t = self._guide_target
            self._off_target = bool(t) and (x - t[0]) ** 2 + (y - t[1]) ** 2 > config.CLICK_RADIUS ** 2
            self._acted.set()

    def _on_key(self, key) -> None:
        if key == keyboard.Key.esc:
            self.ui.hide_board.emit()
            self.ui.hide_text.emit()
        elif key != getattr(keyboard.Key, config.PTT_KEY) and not self._zavero_acting:
            self.ui.dismiss.emit()  # the user started typing: an old bubble gets out of the way
        if key == keyboard.Key.esc and self.busy:
            self.stop()
        elif key == keyboard.Key.enter and self._waiting:
            self._acted.set()

    def stop(self) -> None:
        """Cancel the running task right away."""
        if self.coach.active:  # progress is saved: "continue" picks it up again
            self.coach.cancel()
            self.ui.go_home.emit()
            self.ui.set_thinking.emit(False)
            self._say(phrase("stopped", self.user_text), "done")
        if self.busy:
            self._cancel.set()
            self._acted.set()
            self._answered.set()
            # React right away; the worker may still be waiting for the model for a few seconds.
            self.ui.go_home.emit()
            self.ui.set_thinking.emit(False)
            self._say(phrase("stopped", self.user_text), "done")

    def start(self, text: str, mode: str, said: str | None = None) -> None:
        """Run a task. said = the user's own words when text is a task Zavero wrote (keeps their language)."""
        self.user_text = said or text
        self.mode = mode
        self._prefetched = None  # guide/do mode always looks at the screen fresh
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
        seq = self._talk_seq
        mouse_at = tuple(int(v) for v in mouse.Controller().position)
        try:
            shot = self._take_prefetched()  # taken when the hotkey went down
            if shot is None:
                self.ui.hide_for_capture()
                try:
                    shot = driver.screenshot(keep_full=True)  # full resolution: sharp diagram copy + zoomed pointing check
                finally:
                    self.ui.show_after_capture()
            res = self._think(lambda: talk.answer(self._with_context(text), shot, mouse_at, lang(text), draw, error))
        except Exception as e:  # noqa: BLE001
            actionlog.log("talk_error", text=text, error=str(e))
            if seq == self._talk_seq:
                self._say(friendly_error(e, text), "error")
            return
        if seq != self._talk_seq:  # the user pressed the hotkey again: this answer is stale
            actionlog.log("talk_dropped", question=text)
            return
        reply = res["answer"]
        if res.get("sketch"):  # a new drawing on a blank whiteboard (side -1 = whiteboard)
            self.ui.show_board.emit(talk.whiteboard_png(), res["steps"], -1.0)
            reply += "\n" + "\n".join(f"**{i}. {s['label']}** – {s['detail']}"
                                      for i, s in enumerate(res["steps"], 1) if s["shape"] != "text")
        elif res["region"]:
            r = res["region"]
            side = (r["x"] + r["w"] / 2) / shot.width
            self.ui.show_board.emit(driver.crop_png(shot, r["x"], r["y"], r["w"], r["h"]), res["steps"], side)
            reply += "\n" + "\n".join(f"**{i}. {s['label']}** – {s['detail']}" for i, s in enumerate(res["steps"], 1))
        elif res["point"]:
            self.ui.point_at.emit(*driver.to_screen(res["point"]["x"], res["point"]["y"], shot))
            self.ui.set_label.emit(point_label(res.get("label", ""), text))
        self._remember("user", text)
        self._remember("zavero", reply)
        actionlog.log("talk", question=text, answer=reply, point=res["point"], region=res["region"])
        self._say(reply, "info", ["copy"])
        if res.get("goto"):
            self._open_line(res["goto"], reply, lang(text), seq)

    # --- circle to ask -------------------------------------------------------
    def _circled(self) -> list | None:
        """The loop the user drew with the mouse while holding the talk key (real px), or None."""
        try:
            ink = self.ui.take_ink()
            return ink if talk.circled_region(ink) else None
        except Exception:  # noqa: BLE001 - no overlay (tests) or an odd trail: just no circle
            return None

    def on_silent(self) -> bool:
        """The key was released without words: a circle alone means 'what is this?'. True if handled."""
        loop = self._circled()
        if not loop or self.coach.active or self._asking:
            return False
        question = {"te": "ఇది ఏంటి?", "hi": "यह क्या है?"}.get(self.lang, "What is this?")
        threading.Thread(target=self._talk_circle, args=(question, loop), daemon=True).start()
        return True

    def _talk_circle(self, text: str, loop: list) -> None:
        """Explain the part the user circled (on a diagram, the 3D board, or anything on screen)."""
        self.ui.set_mode.emit("Explain")
        self.ui.keep_lasso(loop)
        seq = self._talk_seq
        context = self.ui.board_context()
        self._prefetched = None  # taken at key press, before the circle (and without the 3D board)
        try:
            self.ui.hide_for_capture(keep_3d=True)
            try:
                shot = driver.screenshot(keep_full=True)
            finally:
                self.ui.show_after_capture()
            pts = [((x - shot.left) / shot.scale, (y - shot.top) / shot.scale) for x, y in loop]
            res = self._think(lambda: talk.answer_circle(self._with_context(text), shot, pts, context, lang(text)))
        except Exception as e:  # noqa: BLE001
            actionlog.log("circle_error", text=text, error=str(e))
            if seq == self._talk_seq:
                self._say(friendly_error(e, text), "error")
            return
        if seq != self._talk_seq:
            return
        reply = (f"**{res['label']}**\n" if res["label"] else "") + res["answer"]
        self._remember("user", f"(circled a part) {text}")
        self._remember("zavero", reply)
        actionlog.log("circle_talk", question=text, label=res["label"], answer=res["answer"])
        self._say(reply, "info", ["copy"])

    def _talk3d(self, text: str) -> None:
        """Build a 3D teaching model of the topic; the board explains it step by step."""
        self.ui.set_mode.emit("3D")
        seq = self._talk_seq
        try:
            scene = self._think(lambda: talk.answer_3d(self._with_context(text), lang(text)))
        except Exception as e:  # noqa: BLE001
            actionlog.log("talk3d_error", text=text, error=str(e))
            if seq == self._talk_seq:
                self._say(friendly_error(e, text), "error")
            return
        if seq != self._talk_seq:  # they asked something else meanwhile
            return
        self.ui.show_3d.emit(json.dumps(scene, ensure_ascii=False))
        self._remember("user", text)
        self._remember("zavero", scene["answer"] + " " + "; ".join(s["label"] for s in scene["steps"]))
        actionlog.log("talk3d", question=text, title=scene["title"], parts=len(scene["parts"]))

    def _open_line(self, goto: dict, error: str, user_lang: str, seq: int) -> None:
        """Jump to the broken line in VS Code, point at it and say exactly what to change."""
        file, line = goto["file"], goto["line"]
        time.sleep(2.5)  # let the user read the first explanation
        if seq != self._talk_seq:  # they asked something else meanwhile
            return
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
            self.ui.set_label.emit(f"line {line}")
        self._remember("zavero", res.get("answer", ""))
        self._say(f"**{file} · line {line}**\n{res.get('answer', '')}", "info")

    # --- "post this on LinkedIn" --------------------------------------------
    def _post(self, text: str, platform: str) -> None:
        """Write the post, show it, and after a spoken yes put it on the site (stopping before Post)."""
        self.ui.set_mode.emit("Post")
        try:
            shot = self._take_prefetched()
            if shot is None:
                self.ui.hide_for_capture()
                try:
                    shot = driver.screenshot(keep_full=True)
                finally:
                    self.ui.show_after_capture()
            res = self._think(lambda: writer.compose_post(text, shot, platform, writer.post_language(text)))
        except Exception as e:  # noqa: BLE001
            actionlog.log("post_error", text=text, error=str(e))
            self._say(friendly_error(e, text), "error")
            return
        image = writer.save_screenshot(shot) if writer.wants_screenshot(text) else None
        site = {"linkedin": "LinkedIn", "x": "X", "facebook": "Facebook"}[platform]
        draft = res["post"] if len(res["post"]) < 700 else res["post"][:700] + "…"
        actionlog.log("post_draft", platform=platform, post=res["post"], image=str(image or ""))
        if not self.ask(f"{draft}\n\n{phrase('post_ask', text).format(site=site)}", buttons=["yes", "no", "copy"]):
            self._say(phrase("post_cancel", text), "done")
            return
        driver.set_clipboard(res["post"])  # pasted, never typed: works for Telugu/Hindi too
        actionlog.log("post_approved", platform=platform)
        self.start(writer.post_task(platform, image), "do", said=text)

    # --- "what matters today?" -------------------------------------------
    def brief(self) -> None:
        """Short briefing: at most 3 things that matter, from reminders + unread Gmail."""
        self.ui.set_mode.emit("Today")
        try:
            facts = self._think(lambda: briefing.gather(self.reminders, self.gmail))
            text = self._think(lambda: briefing.write(facts, self.lang))
        except Exception as e:  # noqa: BLE001
            actionlog.log("briefing_error", error=str(e))
            self._say(friendly_error(e, self.user_text), "error")
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
            self._say(friendly_error(e, said), "error")
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

    def _point(self, target: tuple[int, int], step: Step) -> None:
        """Chai flies to the target; the chip shows the button's name ("Pay Bill") when the model quoted it."""
        self.ui.point_at.emit(*target)
        quoted = re.findall(r'["“]([^"”]{1,30})["”]', step.text or "")
        self.ui.set_label.emit(point_label(quoted[0] if quoted else "", self.user_text))

    def _guide(self, step: Step, shot) -> list | None:
        """Show the user what to do and wait for them. Returns acked checks, or None to switch to do mode."""
        if all(getattr(a, "type", "") in ("wait", "screenshot", "move") for a in step.actions):
            for a in step.actions:
                driver.execute(a, shot)
            return []
        self._check()  # "stop" may have come while the model was thinking
        target = self._target(step, shot)
        if target:
            self._point(target, step)
        text = self._think(lambda: narrator.narrate("guide", self.user_text, step.text, step.actions))
        self._check()
        self._say(text, "hold", ["do", "next"])  # stays until the user does the step
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
            self._say(narrator.narrate("handoff", self.user_text, step.text, step.actions, secret), "hold", ["next"])
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
                self._point(target, step)
            question = narrator.narrate("confirm", self.user_text, step.text, step.actions, reason)
            if not self._ask(question):
                raise Cancelled
            actionlog.log("approved", reason=reason, note=step.text)
        if target:
            self._point(target, step)
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

    def _say(self, text: str, mood: str, buttons: list | None = None) -> None:
        """Show bubble text (with optional buttons, see overlay.BUTTONS) and invalidate older async narration."""
        self._say_seq += 1
        if buttons:
            self.ui.show_buttons.emit(text, mood, buttons)
        else:
            self.ui.show_text.emit(text, mood)

    def on_button(self, b: str) -> None:
        """A bubble button was clicked: same as saying it."""
        actionlog.log("button", id=b)
        if self.coach.active:
            self.coach.button(b)
            return
        if self._asking and b in ("yes", "no", "close"):
            self._answer = b == "yes"  # closing a question = no
            self._answered.set()
        elif b == "do" and self.busy:
            self._take_over("(clicked: do it for me)")
        elif b == "next" and self._waiting:
            self._acted.set()

    def _take_over(self, said: str) -> None:
        """Same task, but now Zavero does the steps (do mode)."""
        self._remember("user", said)
        self.mode = "do"
        self.ui.set_mode.emit("Doing")
        self._acted.set()

    def _say_async(self, kind: str, step: Step) -> None:
        """Narrate in the background; drop the result if something newer was shown meanwhile."""
        self._say_seq += 1
        seq = self._say_seq

        def work() -> None:
            text = narrator.narrate(kind, self.user_text, step.text, step.actions)
            if seq == self._say_seq:
                self.ui.show_text.emit(text, "info")

        threading.Thread(target=work, daemon=True).start()

    def ask(self, question: str, timeout: float = 120, buttons: list | None = None) -> bool:
        """Ask a yes/no question in the bubble; the user answers by voice or the Yes/No buttons. No answer = no."""
        self._say(question, "hold", buttons or ["yes", "no"])  # stays until they answer
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
