"""Push-to-talk: hold the hotkey, speak, release -> transcript via Muse Voice Transcribe.

Test it alone:
    python -m zavero.voice
"""
import asyncio
import json
import queue
import threading
import time
from typing import Callable

import sounddevice as sd
from pynput import keyboard

from zavero import config

BLOCK = config.SAMPLE_RATE // 10  # 100 ms of audio per frame
_END = None  # sentinel: user released the hotkey


class PushToTalk:
    """Hold the PTT key (default Right Ctrl) to record. Calls on_final(text) after release."""

    def __init__(
        self,
        on_final: Callable[[str], None],
        on_partial: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ):
        self.on_final = on_final
        self.on_partial = on_partial or (lambda t: None)
        self.on_error = on_error or (lambda m: print("[voice error]", m))
        self.on_status = on_status or (lambda m: None)
        self._started = 0.0
        self._too_short = False
        self._recording = False
        self._peak = 0
        self._audio: queue.Queue = queue.Queue()
        self._mic: sd.InputStream | None = None
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()
        self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)

    def start(self) -> None:
        """Start listening for the hotkey (non-blocking)."""
        self._listener.start()

    def join(self) -> None:
        self._listener.join()

    # --- hotkey ---------------------------------------------------------
    debug = False
    _KEY = getattr(keyboard.Key, config.PTT_KEY)

    def _press(self, key) -> None:
        if self.debug:
            print(f"[key down] {key!r}", flush=True)
        if key == self._KEY and not self._recording:
            self._begin()

    def _release(self, key) -> None:
        if key == self._KEY and self._recording:
            self._end()

    # --- recording ------------------------------------------------------
    def _begin(self) -> None:
        self._recording = True
        self._started = time.monotonic()
        self._peak = 0
        self._audio = queue.Queue()
        audio = self._audio

        def on_audio(data, frames, t, status) -> None:
            self._peak = max(self._peak, int(abs(data).max()))
            audio.put(bytes(data))

        # Start the mic right away so the first words aren't lost while the socket connects.
        try:
            self._mic = sd.InputStream(
                samplerate=config.SAMPLE_RATE, channels=1, dtype="int16", blocksize=BLOCK,
                callback=on_audio,
            )
            self._mic.start()
        except Exception as e:  # noqa: BLE001
            self._recording = False
            self.on_error(f"Microphone failed: {e}")
            return
        self.on_status("Listening...")
        fut = asyncio.run_coroutine_threadsafe(self._session(audio), self._loop)
        fut.add_done_callback(self._done)

    def _end(self) -> None:
        self._recording = False
        if self._mic:
            self._mic.stop()
            self._mic.close()
            self._mic = None
        self._audio.put(_END)
        self._too_short = time.monotonic() - self._started < config.MIN_TALK_S
        if self._too_short:
            self.on_status("Too quick. Keep holding the key while you speak.")
            return
        self.on_status(f"Transcribing... (mic peak {self._peak}/32767)")
        if self._peak < 1000:
            self.on_status("Mic is very quiet - check Windows mic volume / privacy settings.")

    def _done(self, fut) -> None:
        if self._too_short:
            return
        try:
            text = fut.result()
        except Exception as e:  # noqa: BLE001 - report every failure to the user
            self.on_error(f"{type(e).__name__}: {e}")
            return
        if text.strip():
            self.on_final(text.strip())
        else:
            self.on_status("Heard nothing. Hold the key while you speak.")

    # --- websocket ------------------------------------------------------
    async def _session(self, audio: queue.Queue) -> str:
        """Stream one push-to-talk turn and return the final transcript."""
        import websockets

        loop = asyncio.get_running_loop()
        async with websockets.connect(config.ASR_URL, open_timeout=10, max_size=None) as ws:
            await ws.send(json.dumps({
                "authorization": {"accessToken": f"Bearer {config.api_key()}"},
                "model": config.MODEL_VOICE,
                "audioEncoding": "PCM_24KHZ",
                "mode": "PUSH_TO_TALK",
                "partialMode": "CUMULATIVE",
                "emitAudioProgress": False,
                "languageBias": config.LANGUAGE_BIAS,
            }))
            ack = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if ack.get("type") == "error":
                raise RuntimeError(ack.get("message", ack))

            async def send_audio() -> None:
                while (chunk := await loop.run_in_executor(None, audio.get)) is not _END:
                    await ws.send(chunk)
                await ws.send(json.dumps({"type": "endStream"}))

            sender = asyncio.create_task(send_audio())
            final = ""
            # Keep reading until the server closes; closing early can drop the final transcript.
            async for msg in ws:
                if not isinstance(msg, str):
                    continue
                event = json.loads(msg)
                kind = event.get("type")
                if kind == "transcript":
                    if event.get("final"):
                        final = event.get("transcript", "")
                    else:
                        self.on_partial(event.get("transcript", ""))
                elif kind == "error":
                    raise RuntimeError(event.get("message", event))
            await sender
            return final


if __name__ == "__main__":
    import sys

    ptt = PushToTalk(
        on_final=lambda t: print(f"\r>> {t}" + " " * 20, flush=True),
        on_partial=lambda t: print(f"\r.. {t}", end="", flush=True),
        on_status=lambda m: print(f"\n[{m}]", flush=True),
    )
    try:
        if "--enter" in sys.argv:
            # No hotkey: Enter to start, Enter to stop. Isolates mic + server from the hotkey.
            print("Press Enter to start talking, Enter again to stop. Ctrl+C to quit.", flush=True)
            while True:
                input()
                ptt._begin()
                input()
                ptt._end()
        else:
            ptt.debug = "--debug" in sys.argv
            print(f"Ready. Hold {config.PTT_KEY.upper()} (Right Ctrl) and speak. Let go to finish. Ctrl+C to quit.", flush=True)
            ptt.start()
            ptt.join()
    except KeyboardInterrupt:
        pass
