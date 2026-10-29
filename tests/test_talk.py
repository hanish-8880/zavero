from zavero.driver import Shot
from zavero.talk import clean_drawing, is_diagram, is_question


def test_diagram_requests():
    for t in ["explain this diagram", "ee diagram enti?", "ye chart samjhao", "I have a doubt in this figure",
              "draw this diagram for me", "ఈ డయాగ్రామ్ అర్థం కాలేదు", "इस आरेख को समझाओ"]:
        assert is_diagram(t) and is_question(t), t
    assert not is_diagram("make a chart in excel")
    assert not is_diagram("what is this button")


def test_clean_drawing_steps():
    shot = Shot("", 1280, 720, 1.5)
    data = {"answer": "heart", "region": {"x": 100, "y": 100, "w": 400, "h": 200}, "steps": [
        {"shape": "circle", "color": "red", "points": [[300, 200]], "label": "Left ventricle", "detail": "pumps"},
        {"shape": "path", "color": "blue", "points": [[100, 100], [500, 300]], "label": "Vena cava", "detail": "in"},
        {"shape": "arrow", "color": "pink", "points": [[300, 200]], "label": "bad", "detail": "one point"},
        {"shape": "path", "color": "red", "points": [], "label": "empty", "detail": "dropped"},
    ]}
    out = clean_drawing(data, shot)
    assert out["region"] == {"x": 100, "y": 100, "w": 400, "h": 200}
    s = out["steps"]
    assert len(s) == 3
    assert s[0]["shape"] == "circle" and s[0]["pts"] == [(0.5, 0.5)]
    assert s[1]["shape"] == "path" and s[1]["pts"] == [(0.0, 0.0), (1.0, 1.0)] and s[1]["color"] == "blue"
    assert s[2]["shape"] == "circle" and s[2]["color"] == "red"  # 1-point arrow -> circle, unknown colour -> red
    assert clean_drawing({"answer": "no diagram", "region": None, "steps": []}, shot)["region"] is None


def test_questions_go_to_talk():
    for t in ["what is this?", "What does this error mean?", "explain this page", "why is it not loading",
              "ee button enti?", "ఇది ఏంటి?", "ye kya hai", "यह क्या है?", "is this safe to download?"]:
        assert is_question(t), t


def test_tasks_stay_tasks():
    for t in ["how do I pay the bill", "open my college website", "current bill ela kattali?",
              "poster kaise banate hai", "what is this, open it for me", "open notepad"]:
        assert not is_question(t), t
