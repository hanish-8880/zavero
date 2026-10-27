# Zavero

Voice-first AI companion that helps beginners use any website or desktop app — in Telugu, Hindi or English.
Hold a hotkey, say what you want, and Zavero shows you exactly what to click (or does it for you, asking before anything risky).

Built for the Meta Global AI Developer Hackathon with Muse Spark, Muse Wonder, Muse Voice Transcribe and SAM 3.1.

## Setup (Windows)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # paste your MODEL_API_KEY
```

## Try it

```bash
python scripts/test_click.py      # screenshot -> model -> click coordinates
python scripts/test_telugu.py     # Telugu / Hindi bubble text
python -m zavero.voice            # hold Right Ctrl and speak
pytest -q
```
