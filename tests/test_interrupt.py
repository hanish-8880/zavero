from zavero import driver, orchestrator, talk
from zavero.orchestrator import Orchestrator


class Sig:
    def __init__(self, log: list, name: str) -> None:
        self.log, self.name = log, name

    def emit(self, *args) -> None:
        self.log.append((self.name, args))


class FakeUI:
    def __init__(self) -> None:
        self.log: list = []

    def __getattr__(self, name):
        return Sig(self.log, name)

    def hide_for_capture(self) -> None:
        pass

    def show_after_capture(self) -> None:
        pass


def _orch() -> Orchestrator:
    o = Orchestrator.__new__(Orchestrator)
    o.ui = FakeUI()
    o._worker = None
    o._say_seq = o._talk_seq = 0
    return o


def test_new_press_drops_the_old_answer(monkeypatch):
    o = _orch()
    monkeypatch.setattr(orchestrator.mouse, "Controller", lambda: type("M", (), {"position": (5, 5)})())
    monkeypatch.setattr(driver, "screenshot", lambda **k: driver.Shot("", 1280, 720, 1.5))

    def slow_answer(*a, **k):
        o.on_press()  # the user presses Right Ctrl again while Spark is thinking
        return {"answer": "old answer", "point": None, "goto": None, "region": None, "steps": []}

    monkeypatch.setattr(talk, "answer", slow_answer)
    o._talk("what is this?")
    shown = [args[0] for name, args in o.ui.log if name in ("show_text", "show_buttons")]
    assert "old answer" not in shown
    assert ("go_home", ()) in o.ui.log


def test_answer_shows_without_interrupt(monkeypatch):
    o = _orch()
    monkeypatch.setattr(orchestrator.mouse, "Controller", lambda: type("M", (), {"position": (5, 5)})())
    monkeypatch.setattr(driver, "screenshot", lambda **k: driver.Shot("", 1280, 720, 1.5))
    monkeypatch.setattr(talk, "answer", lambda *a, **k: {"answer": "fresh", "point": None, "goto": None,
                                                         "region": None, "steps": []})
    o._talk("what is this?")
    assert ("show_buttons", ("fresh", "info", ["copy"])) in o.ui.log


def test_uses_the_key_press_screenshot(monkeypatch):
    o = _orch()
    pressed = driver.Shot("pressed", 1280, 720, 1.5)
    monkeypatch.setattr(orchestrator.mouse, "Controller", lambda: type("M", (), {"position": (5, 5)})())
    monkeypatch.setattr(driver, "screenshot", lambda **k: pressed)
    o._prefetch()
    monkeypatch.setattr(driver, "screenshot", lambda **k: driver.Shot("late", 1280, 720, 1.5))
    seen = []
    monkeypatch.setattr(talk, "answer", lambda q, shot, *a, **k: seen.append(shot.data_url) or
                        {"answer": "ok", "point": None, "goto": None, "region": None, "steps": []})
    o._talk("what is this?")
    o._talk("and this?")  # used once: the next question captures again
    assert seen == ["pressed", "late"]
