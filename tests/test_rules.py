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
    assert classify("do for me?") == "do"  # was missed on Oct 28
    assert classify("you do for me pay the current bill for me.") == "do"


def test_conversation_memory():
    from zavero.orchestrator import Orchestrator

    o = Orchestrator.__new__(Orchestrator)  # no listeners/UI needed for this
    assert o._with_context("i want to pay current bill") == "i want to pay current bill"
    o._remember("user", "i want to pay current bill")
    o._remember("zavero", "Which electricity company? (APSPDCL, APEPDCL...)")
    task = o._with_context("APSPDCL")
    assert "pay current bill" in task and "Which electricity company" in task
    assert task.endswith("The user now says: APSPDCL")


def test_answer_keeps_do_mode():
    import time

    from zavero.orchestrator import Orchestrator

    o = Orchestrator.__new__(Orchestrator)
    o.mode = "do"
    o._asked_at = None
    assert not o._answers_do_question()  # finished without a question
    o._asked_at = time.monotonic()  # "Which electricity company?"
    assert o._answers_do_question()
    o.mode = "guide"
    assert not o._answers_do_question()


def test_risky():
    assert risky_reason("I'll click the Pay Now button", []) is not None
    assert risky_reason("I'll click Submit", []) is not None
    assert risky_reason("I'll click the Start button", []) is None
    assert risky_reason("Opening the Display settings", []) is None
    assert risky_reason('I\'ll click "Proceed to Pay".', []) is not None
    assert risky_reason("APPROVAL NEEDED: I'll click \"Go\".", []) is not None


def test_not_risky_while_paying_a_bill():
    # The goal mentions payment, but these clicks only open pages (the bug from Oct 28).
    assert risky_reason("I will click the New tab plus button to start your bill payment.", []) is None
    assert risky_reason('I\'ll click "Quick Pay" to open the payment page.', []) is None
    assert risky_reason('I\'ll click "Google Search" to find the APSPDCL payment site.', []) is None
    assert risky_reason('I\'ll type the service number in "Service Number" for payment.', []) is None


def test_posting_needs_approval():
    for note in ['I will click "Post" to publish it.', "I'll click the Publish button", 'I will click "Tweet"',
                 'I will click "Reply all"', 'I will click "Upload"', 'I will click "Share now"', 'I will click "Go live"']:
        assert risky_reason(note, []) is not None, note
    assert risky_reason('I will click "Start a post" to open the editor.', []) is None
    assert risky_reason('I will click the "Posts" tab.', []) is None


def test_secrets():
    typed = [{"type": "type", "text": "1234 5678 9012"}]
    assert secret_reason("Typing the number", typed) is not None
    assert secret_reason("I'll type the OTP", [{"type": "type", "text": "4821"}]) is not None
    assert secret_reason("Typing hello", [{"type": "type", "text": "hello"}]) is None
    assert secret_reason("I'll click Password", [{"type": "click", "x": 1, "y": 2}]) is None
