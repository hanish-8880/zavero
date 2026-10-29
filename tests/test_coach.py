"""The Guide-anything coach with two made-up apps and one made-up goal: nothing in the engine knows them,
so everything it does for them must come from skills/*.md (or research), proving it is general."""
import queue
import re
from datetime import date, timedelta
from pathlib import Path

from zavero import coach, driver, research, skills
from zavero.coach import Coach, Goals, clean_step, is_continue, is_goal, keys_match, norm_keys, pynput_name, to_actions

from test_interrupt import FakeUI

PIXELPAD = """---
name: PixelPad basics
triggers: [pixelpad, pixel pad, photo collage]
apps: [PixelPad]
updated: {today}
sources: [https://help.pixelpad.example/start]
---
## Screen names
- The **Canvas** is in the middle; **Layers** panel on the right.
## Shortcuts
- Ctrl+Shift+N = new layer
"""
TUNEBOX = """---
name: TuneBox Studio basics
triggers: [tunebox, music mix]
apps: [TuneBox Studio]
updated: {old}
sources: []
---
## Screen names
- **Track list** on the left.
"""


def _skill_dir(tmp_path: Path) -> Path:
    d = tmp_path / "skills"
    d.mkdir()
    (d / "pixelpad.md").write_text(PIXELPAD.format(today=date.today().isoformat()), encoding="utf-8")
    (d / "tunebox.md").write_text(TUNEBOX.format(old=(date.today() - timedelta(days=90)).isoformat()), encoding="utf-8")
    return d


def test_skills_match_by_window_and_words(tmp_path):
    d = _skill_dir(tmp_path)
    assert [s.slug for s in skills.match("make a photo collage", "", d)] == ["pixelpad"]
    assert [s.slug for s in skills.match("help me", "My song - TuneBox Studio", d)] == ["tunebox"]
    assert skills.match("cook biryani", "Untitled - Notes", d) == []
    pix, tune = skills.match("pixelpad", "", d)[0], skills.match("tunebox", "", d)[0]
    assert not pix.stale and tune.stale  # older than 60 days -> research again
    assert "Ctrl+Shift+N" in skills.as_context([pix])
    skills.append_learned("pixelpad", ["Users often miss the Layers tab -> point at it first"], d)
    text = (d / "pixelpad.md").read_text(encoding="utf-8")
    assert "## Learned" in text and "Layers tab" in text and skills.parse("pixelpad", text).name == "PixelPad basics"


def test_goal_words():
    for t in ["teach me pixelpad", "TuneBox nerpinchu", "mujhe music mix banana sikhao", "I want to start a tiffin business",
              "guide me to make a photo collage", "పిక్సెల్‌ప్యాడ్ నేర్పించు", "मुझे ट्यूनबॉक्स सिखाओ"]:
        assert is_goal(t), t
    for t in ["open notepad", "what is this?", "current bill ela kattali?"]:  # "how to" stays on the screen agent
        assert not is_goal(t), t
    assert is_continue("continue") and is_continue("కొనసాగించు") and not is_continue("continue to pay the bill now please")


def test_keys():
    assert norm_keys("Ctrl+Shift+N") == ["ctrl", "shift", "n"]
    assert norm_keys(["Control", "Return"]) == ["ctrl", "enter"]
    ctrl = type("K", (), {"name": "ctrl_l"})()
    n_with_ctrl = type("K", (), {"vk": 78, "char": "\x0e"})()  # what pynput gives for Ctrl+N
    assert pynput_name(ctrl) == "ctrl" and pynput_name(n_with_ctrl) == "n"
    assert keys_match({"ctrl", "shift", "n"}, ["ctrl", "shift", "n"])
    assert not keys_match({"ctrl", "n"}, ["ctrl", "shift", "n"])


def test_clean_step_and_actions():
    st = clean_step({"action": "drag", "x": 5000, "y": 10, "label": "Photo"}, 1280, 720)
    assert st["action"] == "click" and st["x"] == 1279  # no end point -> click; clamped into the screenshot
    assert clean_step({"action": "key", "keys": []}, 1280, 720)["action"] == "look"
    assert clean_step({"action": "explode"}, 1280, 720)["action"] == "look"
    drag = clean_step({"action": "drag", "x": 10, "y": 20, "to": {"x": 300, "y": 400}}, 1280, 720)
    assert to_actions(drag) == [{"type": "drag", "path": [{"x": 10, "y": 20}, {"x": 300, "y": 400}]}]
    assert to_actions(clean_step({"action": "key", "keys": ["Ctrl", "S"]}, 1280, 720)) == [
        {"type": "keypress", "keys": ["ctrl", "s"]}]


class FakeModel:
    """Scripted Muse Spark: answers by which prompt it gets, and records what it was told."""

    def __init__(self, steps: list[dict], questions=None, fail_first_check=False) -> None:
        self.steps, self.questions, self.fail_first = list(steps), questions or [], fail_first_check
        self.prompts: list[str] = []

    def __call__(self, system: str, text: str, shot=None) -> dict:
        self.prompts.append(system)
        if system.startswith("A beginner in India"):
            return {"questions": self.questions}
        if system.startswith("You plan"):
            return {"title": "Goal done", "steps": [{"title": f"Step {i + 1}", "why": "because"}
                                                    for i in range(len(self.steps))],
                    "follow_ups": [{"title": "Check orders", "days": 7}]}
        if system.startswith("You guide"):
            n = int(re.search(r"Current step (\d+)", system).group(1))
            return self.steps[n - 1]
        if system.startswith("A beginner just tried"):
            if self.fail_first:
                self.fail_first = False
                return {"ok": False, "what_happened": "Nothing changed", "fix": "Click the blue button"}
            return {"ok": True, "what_happened": "Done"}
        if system.startswith("A beginner finished"):
            return {"lines": ["Pointing at the Layers panel first helped"]}
        raise AssertionError(system[:40])


def _coach(tmp_path, model: FakeModel, waits: list[str]) -> tuple[Coach, object, list]:
    added = []
    orch = type("O", (), {"ui": FakeUI(), "lang": "en", "user_text": "",
                          "reminders": type("R", (), {"add": lambda self, *a: added.append(a)})()})()
    c = Coach(orch, Goals(tmp_path / "goals.json"), _skill_dir(tmp_path))
    c.model = model
    c.screenshot = lambda: driver.Shot("", 1280, 720, 1.5)
    done_steps = []
    c.do_step = lambda st, shot: done_steps.append(st["action"])
    seq = iter(waits)
    c.wait_for = lambda st, shot: next(seq)
    c._inbox = queue.Queue()
    c.pause = lambda s: None
    return c, orch, done_steps


def test_two_fake_apps_use_only_their_skill_files(tmp_path, monkeypatch):
    monkeypatch.setattr(driver, "active_window_title", lambda: "Holiday - PixelPad")
    model = FakeModel([{"action": "key", "keys": ["ctrl", "shift", "n"], "say": "Make a new layer"},
                       {"action": "drag", "x": 100, "y": 100, "to": {"x": 400, "y": 300}, "say": "Drag the photo"},
                       {"action": "click", "x": 50, "y": 60, "say": "Click Export", "label": "Export"}],
                      fail_first_check=True)
    c, orch, done = _coach(tmp_path, model, ["done", "done", "do", "done"])  # step 1 is retried once
    c._inbox.put(("button", "yes"))   # start the plan
    c._inbox.put(("button", "no"))    # no reminder
    c.run("teach me pixelpad")
    plan_prompt = next(p for p in model.prompts if p.startswith("You plan"))
    assert "Ctrl+Shift+N" in plan_prompt and "TuneBox" not in plan_prompt  # its own skill only
    names = [n for n, _ in orch.ui.log]
    assert ("show_keys", (["Ctrl", "Shift", "N"],)) in orch.ui.log       # key chip for the shortcut step
    assert "show_arrow" in names and "point_at" in names                  # arrow for the drag, ring for the click
    assert done == ["drag"]                                               # "Do it for me" on step 2 only
    g = c.goals._load()
    goal = next(iter(g.values()))
    assert goal["done"] and goal["step"] == 3 and goal["log"][1]["ok"]
    assert "Layers panel" in (tmp_path / "skills" / "pixelpad.md").read_text(encoding="utf-8")  # learned


def test_stale_skill_is_refreshed_by_research(tmp_path, monkeypatch):
    monkeypatch.setattr(driver, "active_window_title", lambda: "Song - TuneBox Studio")
    fresh = skills.Skill("tunebox", "TuneBox Studio basics", ["tunebox"], ["tunebox studio"], date.today(),
                         ["https://help.tunebox.example"], "## Screen names\n- **Mixer** at the bottom")
    monkeypatch.setattr(research, "learn", lambda goal, title: (skills.save(fresh, tmp_path / "skills"), fresh)[1])
    model = FakeModel([{"action": "look", "say": "See the Mixer"}])
    c, orch, _ = _coach(tmp_path, model, ["done"])
    c._inbox.put(("button", "yes"))
    c._inbox.put(("button", "no"))
    c.run("tunebox nerpinchu")
    assert "Mixer" in next(p for p in model.prompts if p.startswith("You plan"))


def test_fake_goal_asks_details_and_saves_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(driver, "active_window_title", lambda: "New tab - Browser")
    monkeypatch.setattr(research, "learn", lambda goal, title: None)  # nothing found: still guides
    model = FakeModel([{"action": "type", "x": 10, "y": 10, "text": "Amma's Tiffins", "say": "Type the name"},
                       {"action": "click", "x": 20, "y": 20, "say": "Click Publish", "risky": True, "label": "Publish"}],
                      questions=[{"q": "Which city?", "options": ["Hyderabad", "Vijayawada"]},
                                 {"q": "Budget?", "options": ["Under ₹5,000", "More"]}])
    c, orch, _ = _coach(tmp_path, model, ["done", "done"])
    for ev in [("button", "opt:Vijayawada"), ("say", "under five thousand"),  # details: button + voice
               ("say", "make it shorter"),                                   # change the plan once
               ("button", "yes"),                                            # start
               ("button", "yes"),                                            # approve the risky Publish step
               ("button", "yes")]:                                           # remind me in 7 days
        c._inbox.put(ev)
    c.run("I want to start a tiffin business")
    goal = next(iter(c.goals._load().values()))
    assert goal["answers"] == {"Which city?": "Vijayawada", "Budget?": "under five thousand"}
    assert any("make it shorter" in p for p in model.prompts)        # revised plan
    assert ("show_buttons", ("Which city?", "hold", ["opt:Hyderabad", "opt:Vijayawada"])) in orch.ui.log
    assert goal["done"] and orch.reminders  # follow-up reminder after a yes
    assert any("Publish" in str(a) for n, a in orch.ui.log if n == "show_buttons")  # asked before publishing


def test_resume_picks_the_unfinished_goal(tmp_path):
    store = Goals(tmp_path / "goals.json")
    store.save({"id": "a", "goal": "old", "plan": {"steps": [{}]}, "step": 1, "done": True})
    store.save({"id": "b", "goal": "half way", "plan": {"steps": [{}, {}]}, "step": 1, "done": False})
    assert store.latest_unfinished()["id"] == "b"


def test_engine_code_knows_no_app():
    """App knowledge lives only in skills/*.md: the engine files must not name any app or field."""
    root = Path(__file__).resolve().parent.parent / "zavero"
    code = "".join((root / f).read_text(encoding="utf-8").lower() for f in ("coach.py", "skills.py", "research.py"))
    for app in ["canva", "blender", "excel", "apspdcl", "irctc", "figma", "photoshop", "youtube", "whatsapp",
                "linkedin", "notepad", "pixelpad", "tunebox", "tiffin"]:
        assert app not in code, app
