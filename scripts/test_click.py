"""Day-1 test: screenshot -> Muse Spark computer use -> print returned coordinates.

Does NOT click anything. Also prints every output item type, to check whether
a text message can come back next to a computer_call (CLAUDE.md 3.4 #1).

    python scripts/test_click.py
    python scripts/test_click.py "Click the Windows Start button" --model muse-wonder-1.0
    python scripts/test_click.py --truncation   # check if truncation=auto is allowed
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import APIStatusError

from zavero import config, driver


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("task", nargs="?", default="Click the Windows Start button on the taskbar.")
    p.add_argument("--model", default=config.MODEL_SPARK)
    p.add_argument("--truncation", action="store_true", help="send truncation='auto'")
    args = p.parse_args()

    shot = driver.screenshot()
    print(f"Screenshot: {shot.width}x{shot.height}, scale {shot.scale:.3f}")

    extra = {"truncation": "auto"} if args.truncation else {}
    client = config.client()
    t0 = time.time()
    try:
        resp = client.responses.create(
            model=args.model,
            tools=[{"type": "computer"}],
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": args.task},
                    {"type": "input_image", "image_url": shot.data_url},
                ],
            }],
            **extra,
        )
    except APIStatusError as e:
        raise SystemExit(f"API error {e.status_code}: {e.message}")
    print(f"Model: {args.model}  ({time.time() - t0:.1f}s)")

    for item in resp.output:
        print(f"\n[{item.type}]")
        if item.type == "computer_call":
            print("  call_id:", item.call_id)
            for a in item.actions:
                line = f"  {a.type}"
                x, y = getattr(a, "x", None), getattr(a, "y", None)
                if x is not None and y is not None:
                    sx, sy = driver.to_screen(x, y, shot)
                    line += f"  model=({x}, {y})  screen=({sx}, {sy})"
                print(line, {k: v for k, v in a.model_dump().items() if k not in ("type", "x", "y")})
            if item.pending_safety_checks:
                print("  SAFETY CHECKS:", [c.model_dump() for c in item.pending_safety_checks])
        elif item.type == "message":
            print("  text:", resp.output_text)
        else:
            print(" ", item.model_dump())

    if resp.usage:
        print(f"\nTokens: in={resp.usage.input_tokens} out={resp.usage.output_tokens}")


if __name__ == "__main__":
    main()
