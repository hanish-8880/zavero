from datetime import datetime

from zavero.reminders import Reminders, is_reminder, next_time


def test_triggers():
    assert is_reminder("remind me at 5 pm to pay the bill")
    assert is_reminder("Nov 12 amma birthday")
    assert is_reminder("saayantram 5 ki bill gurthu cheyyi")
    assert is_reminder("కరెంట్ బిల్ గుర్తు చేయి")
    assert is_reminder("kal doctor ke paas jaana hai yaad dilana")
    assert not is_reminder("open notepad")
    assert not is_reminder("current bill ela kattali")


def test_next_time():
    now = datetime(2026, 10, 28, 12, 0)
    assert next_time(datetime(2026, 10, 28, 9, 0), "daily", now) == datetime(2026, 10, 29, 9, 0)
    assert next_time(datetime(2026, 10, 28, 9, 0), "weekly", now) == datetime(2026, 11, 4, 9, 0)
    assert next_time(datetime(2026, 10, 28, 9, 0), "yearly", now) == datetime(2027, 10, 28, 9, 0)
    assert next_time(datetime(2024, 2, 29, 9, 0), "yearly", now) == datetime(2027, 2, 28, 9, 0)
    assert next_time(datetime(2026, 10, 28, 9, 0), "none", now) is None


def test_due_once_and_yearly(tmp_path):
    r = Reminders(tmp_path / "r.json")
    r.add("pay bill", "2026-10-28T17:00")
    r.add("amma birthday", "2026-11-12T09:00", "yearly")
    assert r.due(datetime(2026, 10, 28, 16, 59)) == []
    fired = r.due(datetime(2026, 10, 28, 17, 0))
    assert [f["title"] for f in fired] == ["pay bill"]
    assert r.due(datetime(2026, 10, 28, 17, 1)) == []  # one-time reminder is gone
    fired = r.due(datetime(2026, 11, 12, 9, 30))
    assert fired[0]["title"] == "amma birthday" and fired[0]["late_min"] == 30
    assert r.upcoming()[0]["when"] == "2027-11-12T09:00"  # moved to next year
    assert Reminders(tmp_path / "r.json").upcoming()[0]["title"] == "amma birthday"  # saved to disk
