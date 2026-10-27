"""Day-1 test: does Muse Spark write natural Telugu / Hindi / Hinglish bubble text?

    python scripts/test_telugu.py
    python scripts/test_telugu.py --model muse-wonder-1.0

Read the output yourself: it should sound like a person talking, not a translation.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import APIStatusError

from zavero import config

SYSTEM = (
    "You write one short instruction for a beginner computer user in India. "
    "Reply in the same language and script as the user's request. Telugu -> Telugu script. "
    "Hindi -> Devanagari. Hinglish -> simple romanized Hinglish. "
    "Max 2 short sentences, very simple everyday words, no jargon. "
    "Keep on-screen English button labels in English and in **bold**."
)

CASES = [
    ("current bill ela kattali?", 'Next step: click the button labelled "Pay Bill".'),
    ("కరెంట్ బిల్లు ఎలా కట్టాలి?", 'Next step: type the consumer number into the box labelled "Service Number".'),
    ("बिजली का बिल कैसे भरूं?", 'Next step: click the button labelled "Quick Pay".'),
    ("mujhe ek birthday poster banana hai", 'Next step: click the search box labelled "Search templates" and type "birthday poster".'),
]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=config.MODEL_SPARK)
    args = p.parse_args()
    client = config.client()

    for request, step in CASES:
        try:
            resp = client.responses.create(
                model=args.model,
                instructions=SYSTEM,
                input=f"User said: {request}\n{step}\nWrite the bubble text.",
            )
        except APIStatusError as e:
            raise SystemExit(f"API error {e.status_code}: {e.message}")
        print(f"User:   {request}\nBubble: {resp.output_text.strip()}\n")


if __name__ == "__main__":
    main()
