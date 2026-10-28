from datetime import datetime

from zavero.briefing import gather, is_briefing
from zavero.reminders import Reminders


def test_triggers():
    for t in ["what matters today", "What needs my attention right now?", "ivala emi undi",
              "ఈరోజు ఏమి ఉంది", "aaj kya zaroori hai", "आज क्या है", "good morning zavero"]:
        assert is_briefing(t), t
    assert not is_briefing("open notepad")


def test_gather_only_today_and_tomorrow(tmp_path):
    r = Reminders(tmp_path / "r.json")
    r.add("pay bill", "2026-10-28T17:00")
    r.add("doctor", "2026-10-29T09:00")
    r.add("amma birthday", "2026-11-12T09:00", "yearly")
    facts = gather(r, None, now=datetime(2026, 10, 28, 8, 0))
    assert "pay bill" in facts and "doctor" in facts
    assert "amma birthday" not in facts
    assert "Email: not connected" in facts
