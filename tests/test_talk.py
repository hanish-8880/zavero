from zavero.talk import is_question


def test_questions_go_to_talk():
    for t in ["what is this?", "What does this error mean?", "explain this page", "why is it not loading",
              "ee button enti?", "ఇది ఏంటి?", "ye kya hai", "यह क्या है?", "is this safe to download?"]:
        assert is_question(t), t


def test_tasks_stay_tasks():
    for t in ["how do I pay the bill", "open my college website", "current bill ela kattali?",
              "poster kaise banate hai", "what is this, open it for me", "open notepad"]:
        assert not is_question(t), t
