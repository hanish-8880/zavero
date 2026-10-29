from zavero.phrases import PHRASES, friendly_error


class Status(Exception):
    def __init__(self, code: int, msg: str = "") -> None:
        super().__init__(msg)
        self.status_code = code


class APITimeoutError(Exception):
    pass


class APIConnectionError(Exception):
    pass


def test_friendly_errors():
    assert friendly_error(Status(402)) == PHRASES["no_credits"]["en"]
    assert friendly_error(Status(400, "Insufficient credit balance")) == PHRASES["no_credits"]["en"]
    assert friendly_error(APITimeoutError("Request timed out.")) == PHRASES["slow"]["en"]
    assert friendly_error(APIConnectionError("Connection error."), "కరెంట్ బిల్") == PHRASES["api_down"]["te"]
    assert friendly_error(ValueError("bad json"), "बिल भरो") == PHRASES["went_wrong"]["hi"]


def test_every_phrase_has_three_languages():
    for key, langs in PHRASES.items():
        assert set(langs) == {"en", "te", "hi"}, key


def test_feedback_words():
    import re

    from zavero.actionlog import FEEDBACK_WORDS

    for t in ["report a bug", "I want to send feedback", "zavero lo problem undi", "zavero mein dikkat hai"]:
        assert re.search(FEEDBACK_WORDS, t.lower()), t
    for t in ["ee site lo problem undi", "payment mein dikkat hai", "what is this error"]:
        assert not re.search(FEEDBACK_WORDS, t.lower()), t


def test_forced_language():
    from zavero import phrases

    phrases.FORCED = "te"
    try:
        assert phrases.lang("hello") == "te"
    finally:
        phrases.FORCED = None
    assert phrases.lang("hello") == "en"
