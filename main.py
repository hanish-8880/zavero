"""Zavero entry point: overlay + push-to-talk + orchestrator.

    python main.py                                   # hold Right Ctrl and speak
    python main.py --task "open notepad"             # skip voice, guide mode
    python main.py --task "open notepad and type hello" --do

start_zavero.bat runs this with pythonw (no console window). Output then goes to logs/zavero.log.
"""
import argparse
import signal
import sys

from zavero import config

if sys.stdout is None:  # started with pythonw: no console, so keep prints and errors in a file
    config.LOG_DIR.mkdir(exist_ok=True)
    sys.stdout = sys.stderr = open(config.LOG_DIR / "zavero.log", "a", encoding="utf-8", buffering=1)

from PyQt6.QtCore import QLockFile, QTimer  # noqa: E402
from PyQt6.QtGui import QAction, QActionGroup  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon  # noqa: E402

import threading  # noqa: E402

from zavero import actionlog, briefing, phrases, reminders  # noqa: E402
from zavero.messaging.gmail import GmailWatcher  # noqa: E402
from zavero.orchestrator import Orchestrator  # noqa: E402
from zavero.overlay import Overlay, avatar_icon  # noqa: E402
from zavero.phrases import phrase  # noqa: E402
from zavero.voice import PushToTalk  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--task", help="run this task without speaking")
    p.add_argument("--do", action="store_true", help="do mode: Zavero clicks for you")
    args = p.parse_args()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Only one Zavero at a time (double-clicking the launcher twice is easy to do).
    config.LOG_DIR.mkdir(exist_ok=True)
    lock = QLockFile(str(config.LOG_DIR / "zavero.lock"))
    if not lock.tryLock(100):
        print("Zavero is already running.")
        return

    overlay = Overlay()
    overlay.show()
    threading.Thread(target=config.warm_up, daemon=True).start()
    orch = Orchestrator(overlay)
    overlay.button_clicked.connect(orch.on_button)

    tray = QSystemTrayIcon(avatar_icon(), app)
    tray.setToolTip("Zavero - hold Right Ctrl and speak")
    menu = QMenu()
    state = briefing.load_state()

    def set_speed(v: str) -> None:
        config.REASONING["effort"] = v  # read by every model call

    # Settings: (saved key, menu title, default, choices, apply). Saved in data/state.json.
    settings = [
        ("show_mode", "Show Zavero", "always", [("always", "Always"), ("talk", "Only while I talk")],
         lambda v: setattr(overlay, "show_mode", v)),
        ("chai_follow", "Chai position", "auto", [("auto", "Follow my mouse while helping"),
                                                  ("always", "Always follow my mouse"),
                                                  ("corner", "Stay in the corner")],
         lambda v: setattr(overlay, "follow_mode", v)),
        ("lang_mode", "Language", "auto", [("auto", "Auto (same as I speak)"), ("te", "తెలుగు"), ("hi", "हिंदी"),
                                           ("en", "English")],
         lambda v: setattr(phrases, "FORCED", None if v == "auto" else v)),
        ("speed", "Speed", "low", [("low", "Fast"), ("medium", "Careful (slower, thinks more)")], set_speed),
    ]
    for key, title, default, choices, apply in settings:
        current = state.get(key, default)
        apply(current)
        sub = menu.addMenu(title)
        group = QActionGroup(sub)
        for value, label in choices:
            act = QAction(label, sub, checkable=True, checked=current == value)
            act.triggered.connect(lambda _, k=key, v=value, f=apply: (f(v), briefing.save_state(**{k: v})))
            group.addAction(act)
            sub.addAction(act)
    menu.addSeparator()
    feedback_action = QAction("Send feedback (say the problem)", menu)
    feedback_action.triggered.connect(orch.ask_feedback)
    menu.addAction(feedback_action)
    replay_action = QAction("Replay onboarding", menu)
    replay_action.triggered.connect(orch.onboard)
    menu.addAction(replay_action)
    stop_action = QAction("Stop current task", menu)
    stop_action.triggered.connect(orch.stop)
    quit_action = QAction("Quit Zavero", menu)
    quit_action.triggered.connect(app.quit)
    menu.addAction(stop_action)
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.show()

    def on_status(msg: str) -> None:
        print(f"[{msg}]", flush=True)
        if msg.startswith("Listening"):
            orch.on_press()
            overlay.set_listening.emit(True)
            overlay.show_text.emit("Listening…", "listen")
        elif msg.startswith("Transcribing"):
            overlay.set_listening.emit(False)
            overlay.set_thinking.emit(True)
        elif msg.startswith("Heard nothing"):
            overlay.set_thinking.emit(False)
            if not orch.on_silent():  # a circle drawn without words still gets explained
                overlay.show_text.emit(phrase("heard_nothing", orch.user_text), "info")
        elif not msg.startswith("Mic"):
            overlay.show_text.emit(msg, "info")

    def on_final(text: str) -> None:
        print(f">> {text}", flush=True)
        overlay.set_listening.emit(False)
        overlay.set_thinking.emit(False)
        overlay.show_text.emit(f"“{text}”", "listen")
        orch.on_transcript(text)

    ptt = PushToTalk(
        on_final=on_final,
        on_partial=lambda t: overlay.show_text.emit(t, "listen"),
        on_error=lambda m: (print("[voice error]", m), overlay.show_text.emit(m, "error")),
        on_status=on_status,
        on_level=overlay.set_level.emit,
    )
    ptt.start()

    def check_reminders() -> None:
        """Pop up anything that is due (also ones missed while Zavero was closed)."""
        fired = orch.reminders.due()
        if not fired:
            return
        lines = []
        for it in fired:
            late = f"  ({reminders.pretty(it['when'])})" if it["late_min"] > 5 else ""
            lines.append(it["alert"] + late)
        overlay.set_mode.emit("Reminder")
        overlay.show_text.emit("\n".join(lines), "warn")
        overlay.attention.emit()
        for it in fired:
            actionlog.log("reminder_fired", id=it["id"], title=it["title"], late_min=it["late_min"])

    reminder_timer = QTimer()
    reminder_timer.timeout.connect(check_reminders)
    reminder_timer.start(15_000)

    watcher = GmailWatcher(orch, overlay)
    if watcher.start():  # does nothing until scripts/gmail_login.py has been run
        orch.gmail = watcher.gmail

    first_run = not state.get("onboarded") and not args.task
    if first_run:
        QTimer.singleShot(1200, orch.onboard)
    else:
        said = {"te": "తెలుగు", "hi": "हिंदी"}.get(orch.lang, "")
        hello = phrase("welcome", said)
        if state.get("name"):  # "Good evening, Hanish 👋" in their language
            hello = phrases.greeting(state["name"], said) + "\n" + hello.split("\n", 1)[-1]
        overlay.show_text.emit(hello, "info")
    QTimer.singleShot(4000, check_reminders)  # after the welcome, show any missed ones
    if briefing.due_this_morning() and not args.task and not first_run:  # "what matters today"
        QTimer.singleShot(9000, lambda: threading.Thread(target=orch.brief, daemon=True).start())
    if args.task:
        QTimer.singleShot(800, lambda: orch.start(args.task, "do" if args.do else "guide"))

    # Let Ctrl+C in the terminal quit (Qt blocks it otherwise).
    signal.signal(signal.SIGINT, lambda *a: app.quit())
    tick = QTimer()
    tick.timeout.connect(lambda: None)
    tick.start(200)

    print("Zavero is running. Hold Right Ctrl and speak. Esc = stop. Quit from the tray icon.", flush=True)
    app.exec()
    lock.unlock()


if __name__ == "__main__":
    main()
