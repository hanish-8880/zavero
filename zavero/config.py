"""Settings and constants. Reads the API key from .env."""
import functools
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

BASE_URL = "https://api.meta.ai/v1"
ASR_URL = "wss://api.meta.ai/v1/asr/realtime"

MODEL_SPARK = "muse-spark-1.3"
MODEL_WONDER = "muse-wonder-1.0"
MODEL_VOICE = "muse-voice-transcribe-1.0"
MODEL_SAM = "sam-3.1"

SCREENSHOT_WIDTH = 1280
MAX_STEPS = 25
GUIDE_IDLE_S = 120  # guide mode gives up if the user does nothing for this long
CLICK_RADIUS = 90  # real px: a click this close to the ring counts as following the guide
API_TIMEOUT_S = 60
# Muse Spark thinking depth. "low" measured Oct 28: screen steps 7.1s -> 4.4s with the same click,
# bubble text 5.2s -> ~2.5s and still correct ("minimal" got the wording wrong).
REASONING = {"effort": "low"}

# Hold this one key to talk. Any pynput Key name: "ctrl_r", "alt_r", "f9", ...
PTT_KEY = "ctrl_r"
MIN_TALK_S = 0.4  # shorter presses are treated as accidental
MAX_TALK_S = 15  # recording stops by itself after this

SAMPLE_RATE = 24_000
LANGUAGE_BIAS = ["English", "Telugu", "Hindi"]
# Words the speech model should expect (biases recognition; Oct 28 "APSPDCL" came out as "minus AB square").
ASR_KEYWORDS = ["Zavero", "APSPDCL", "APEPDCL", "TGSPDCL", "current bill", "service number", "Quick Pay",
                "Canva", "Gmail", "Chrome", "WhatsApp", "Notepad", "nuvve chey", "kar do", "do it for me",
                "remind me", "gurthu", "yaad dilana", "ayindi", "ho gaya"]

LOG_DIR = ROOT / "logs"


def api_key() -> str:
    """Return MODEL_API_KEY or exit with a clear message."""
    key = os.environ.get("MODEL_API_KEY", "").strip()
    if not key:
        raise SystemExit("MODEL_API_KEY is missing. Copy .env.example to .env and paste your key.")
    return key


@functools.lru_cache(maxsize=1)
def client():
    """OpenAI SDK client pointed at the Meta Model API. One shared client = one warm TLS connection."""
    from openai import OpenAI

    return OpenAI(base_url=BASE_URL, api_key=api_key(), timeout=API_TIMEOUT_S)


def warm_up() -> None:
    """Open the API connection early so the first question isn't slow. Errors don't matter here."""
    try:
        client().models.list()
    except Exception:  # noqa: BLE001
        pass
