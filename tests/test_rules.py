from zavero.orchestrator import classify
from zavero.safety import risky_reason, secret_reason


def test_classify_commands():
    assert classify("nuvve chey") == "do"
    assert classify("Kar do.") == "do"
    assert classify("చేయండి") == "do"
    assert classify("stop") == "stop"
    assert classify("ఆగు") == "stop"
    assert classify("అవును") == "yes"
    assert classify("haan") == "yes"
    assert classify("vaddu") == "no"
    assert classify("नहीं") == "no"
    assert classify("ayindi") == "next"


def test_classify_tasks():
    assert classify("current bill ఎలా కట్టాలి?") == "task"
    assert classify("mujhe ek birthday poster banana hai") == "task"
    assert classify("how do I open notepad") == "task"
    assert classify("mera bill pay kar do") == "do"


def test_risky():
    assert risky_reason("I'll click the Pay Now button", []) is not None
    assert risky_reason("I'll click Submit", []) is not None
    assert risky_reason("I'll click the Start button", []) is None
    assert risky_reason("Opening the Display settings", []) is None


def test_secrets():
    typed = [{"type": "type", "text": "1234 5678 9012"}]
    assert secret_reason("Typing the number", typed) is not None
    assert secret_reason("I'll type the OTP", [{"type": "type", "text": "4821"}]) is not None
    assert secret_reason("Typing hello", [{"type": "type", "text": "hello"}]) is None
    assert secret_reason("I'll click Password", [{"type": "click", "x": 1, "y": 2}]) is None
