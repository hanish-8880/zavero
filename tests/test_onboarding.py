import queue

from zavero import briefing, driver, onboarding
from zavero.phrases import greeting

from test_interrupt import FakeUI


def test_greeting():
    assert greeting("Hanish", "", hour=8) == "Good morning, **Hanish** 👋"
    assert greeting("Hanish", "నమస్తే", hour=19).startswith("శుభ సాయంత్రం")


def test_name_fallback(monkeypatch):
    monkeypatch.setattr(onboarding, "_ask_spark", lambda *a: (_ for _ in ()).throw(RuntimeError("offline")))
    assert onboarding.pick_name("call me Ravi.") == "Ravi"


def test_flow(monkeypatch, tmp_path):
    monkeypatch.setattr(briefing, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(onboarding.time, "sleep", lambda s: None)
    monkeypatch.setattr(onboarding, "pick_name", lambda said: "Hanish")
    monkeypatch.setattr(driver, "screenshot", lambda **k: driver.Shot("", 1280, 720, 1.5))
    monkeypatch.setattr(onboarding, "demo_point", lambda shot, l: {"x": 640, "y": 360, "comment": "నీ వాల్‌పేపర్ సూపర్!",
                                                                    "label": "Wallpaper"})
    orch = type("O", (), {"ui": FakeUI(), "lang": "en"})()
    heard = queue.Queue()
    heard.put("హాయ్ చాయ్")      # says hi in Telugu
    heard.put("naa peru Hanish")
    onboarding.run(orch, heard)
    shown = [a[0] for n, a in orch.ui.log if n == "show_text"]
    assert any("Hanish" in s and "నేను ఇవి చేయగలను" in s for s in shown)  # powers, in Telugu
    assert ("point_at", (960, 540)) in orch.ui.log
    state = briefing.load_state()
    assert state["onboarded"] and state["name"] == "Hanish" and state["lang"] == "te"
