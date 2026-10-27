"""Settings and constants. Reads the API key from .env."""
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

# Hold this one key to talk. Any pynput Key name: "ctrl_r", "alt_r", "f9", ...
PTT_KEY = "ctrl_r"
MIN_TALK_S = 0.4  # shorter presses are treated as accidental

SAMPLE_RATE = 24_000
LANGUAGE_BIAS = ["English", "Telugu", "Hindi"]

LOG_DIR = ROOT / "logs"


def api_key() -> str:
    """Return MODEL_API_KEY or exit with a clear message."""
    key = os.environ.get("MODEL_API_KEY", "").strip()
    if not key:
        raise SystemExit("MODEL_API_KEY is missing. Copy .env.example to .env and paste your key.")
    return key


def client():
    """OpenAI SDK client pointed at the Meta Model API."""
    from openai import OpenAI

    return OpenAI(base_url=BASE_URL, api_key=api_key(), timeout=API_TIMEOUT_S)
