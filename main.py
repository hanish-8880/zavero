"""Zavero entry point: overlay + push-to-talk + orchestrator.

    python main.py                                   # hold Right Ctrl and speak
    python main.py --task "open notepad"             # skip voice, guide mode
    python main.py --task "open notepad and type hello" --do
"""
import argparse
import signal
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from zavero.orchestrator import Orchestrator
from zavero.overlay import Overlay
from zavero.voice import PushToTalk


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--task", help="run this task without speaking")
    p.add_argument("--do", action="store_true", help="do mode: Zavero clicks for you")
    args = p.parse_args()

    app = QApplication(sys.argv)
    overlay = Overlay()
    overlay.show()
    orch = Orchestrator(overlay)

    def on_status(msg: str) -> None:
        print(f"[{msg}]", flush=True)
        if msg.startswith("Listening"):
            overlay.set_listening.emit(True)
            overlay.show_text.emit("Listening…", "listen")
        elif msg.startswith("Transcribing"):
            overlay.set_listening.emit(False)
        elif not msg.startswith("Mic"):
            overlay.show_text.emit(msg, "info")

    def on_final(text: str) -> None:
        print(f">> {text}", flush=True)
        overlay.set_listening.emit(False)
        overlay.show_text.emit(f"“{text}”", "listen")
        orch.on_transcript(text)

    ptt = PushToTalk(
        on_final=on_final,
        on_partial=lambda t: overlay.show_text.emit(t, "listen"),
        on_error=lambda m: (print("[voice error]", m), overlay.show_text.emit(m, "error")),
        on_status=on_status,
    )
    ptt.start()

    overlay.show_text.emit("Hi! I'm **Zavero**. Hold **Right Ctrl** and tell me what you want to do.", "info")
    if args.task:
        QTimer.singleShot(800, lambda: orch.start(args.task, "do" if args.do else "guide"))

    # Let Ctrl+C in the terminal quit (Qt blocks it otherwise).
    signal.signal(signal.SIGINT, lambda *a: app.quit())
    tick = QTimer()
    tick.timeout.connect(lambda: None)
    tick.start(200)

    print("Zavero is running. Hold Right Ctrl and speak. Esc = stop. Ctrl+C here = quit.", flush=True)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
