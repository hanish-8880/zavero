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
from PyQt6.QtGui import QAction  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon  # noqa: E402

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
    orch = Orchestrator(overlay)

    tray = QSystemTrayIcon(avatar_icon(), app)
    tray.setToolTip("Zavero - hold Right Ctrl and speak")
    menu = QMenu()
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
            overlay.set_listening.emit(True)
            overlay.show_text.emit("Listening…", "listen")
        elif msg.startswith("Transcribing"):
            overlay.set_listening.emit(False)
            overlay.set_thinking.emit(True)
        elif msg.startswith("Heard nothing"):
            overlay.set_thinking.emit(False)
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
    )
    ptt.start()

    overlay.show_text.emit(phrase("welcome"), "info")
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
