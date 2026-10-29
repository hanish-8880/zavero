from zavero import writer
from zavero.safety import risky_reason


def test_post_requests():
    assert writer.platform_of("post this on LinkedIn") == "linkedin"
    assert writer.platform_of("ee screenshot linkedin lo post chey") == "linkedin"
    assert writer.platform_of("isko twitter pe daalo") == "x"
    assert writer.platform_of("share my result on facebook") == "facebook"
    assert writer.platform_of("open linkedin") is None  # no posting word: normal task
    assert writer.platform_of("how do I post on LinkedIn?") is None  # guide them instead
    assert writer.platform_of("what is this?") is None


def test_post_details():
    assert writer.wants_screenshot("post this screenshot on linkedin")
    assert not writer.wants_screenshot("post about my new shop on linkedin")
    assert writer.post_language("linkedin lo post chey, telugu lo") == "te"
    assert writer.post_language("post this on linkedin") == "en"


def test_post_task_stops_before_post():
    task = writer.post_task("linkedin", None)
    assert "linkedin.com" in task and "Ctrl+V" in task and 'STOP before clicking "Post"' in task
    # and safety still asks if the model tries to click it
    assert risky_reason('I will click "Post" to publish it.', []) is not None
