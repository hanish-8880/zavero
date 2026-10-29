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
