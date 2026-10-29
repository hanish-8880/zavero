from zavero.driver import Shot
from zavero.talk import _goto, clean_drawing, is_diagram, is_error, is_question


def test_error_questions():
    for t in ["what is this error?", "ee error enti?", "why is my code failing", "fix this error",
              "I got a traceback", "my program is not working", "ये एरर क्या है"]:
        assert is_error(t) and is_question(t), t
    assert not is_error("open notepad")
    assert not is_error("create an error page")


def test_goto_is_sanitised():
    assert _goto({"file": "src/app/main.py", "line": 12}) == {"file": "main.py", "line": 12}
    assert _goto({"file": "C:\\proj\\utils.js", "line": 3}) == {"file": "utils.js", "line": 3}
    assert _goto({"file": "main.py", "line": 0}) is None
    assert _goto({"file": "a b; rm -rf", "line": 4}) is None  # only plain file names are typed
    assert _goto(None) is None


def test_diagram_requests():
    for t in ["explain this diagram", "ee diagram enti?", "ye chart samjhao", "I have a doubt in this figure",
              "draw this diagram for me", "ఈ డయాగ్రామ్ అర్థం కాలేదు", "इस आरेख को समझाओ"]:
        assert is_diagram(t) and is_question(t), t
    assert not is_diagram("make a chart in excel")
    assert not is_diagram("what is this button")


def test_draw_requests_use_the_board_not_paint():
    for t in ["can you draw me another triangle?", "can you draw for me the triangle?", "can you draw me?",
              "explain and draw for me how it will work", "bomma geesi chupinchu", "ye bana ke samjhao"]:
        assert is_diagram(t), t
    assert not is_diagram("open paint and draw a circle")


def test_sketch_steps_on_whiteboard():
    shot = Shot("", 1280, 720, 1.5)
    data = {"answer": "triangle", "mode": "sketch", "region": None, "steps": [
        {"shape": "polygon", "color": "blue", "points": [[100, 600], [900, 600], [100, 100]], "label": "Triangle", "detail": "d"},
        {"shape": "rect", "color": "green", "points": [[100, 550], [150, 600]], "label": "Right angle", "detail": "d"},
        {"shape": "text", "color": "red", "points": [[500, 650]], "text": "a", "label": "a", "detail": "d"},
        {"shape": "text", "color": "red", "points": [[50, 50]], "text": "", "label": "empty", "detail": "dropped"},
    ]}
    out = clean_drawing(data, shot)
    assert out["sketch"] and out["region"] is None
    assert [s["shape"] for s in out["steps"]] == ["polygon", "polygon", "text"]
    assert out["steps"][0]["pts"][0] == (0.1, 600 / 700)
    assert len(out["steps"][1]["pts"]) == 4  # rect corners
    assert out["steps"][2]["text"] == "a"


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


def test_sketch_shapes_are_filled_2d():
    shot = Shot("", 1280, 720, 1.5)
    data = {"answer": "cell", "mode": "sketch", "region": None, "steps": [
        {"shape": "ellipse", "color": "green", "points": [[100, 100], [900, 600]], "label": "Cell"},
        {"shape": "circle", "color": "purple", "points": [[500, 350]], "r": 80, "fill": False, "label": "Ring"},
        {"shape": "line", "color": "blue", "points": [[0, 0], [10, 10]], "label": "Edge"},
    ]}
    s = clean_drawing(data, shot)["steps"]
    assert s[0]["shape"] == "ellipse" and len(s[0]["pts"]) == 2 and s[0]["fill"]  # filled by default
    assert not s[1]["fill"] and not s[2]["fill"]                                  # asked unfilled / not closed


def test_zoom_refine_maps_back(monkeypatch):
    from PIL import Image

    from zavero import talk

    shot = Shot("", 1280, 720, 1.5, full=Image.new("RGB", (1920, 1080)))
    reply = type("R", (), {"output_text": '{"found": true, "x": 400, "y": 100}'})()
    fake = type("C", (), {"responses": type("X", (), {"create": lambda self, **k: reply})()})()
    monkeypatch.setattr(talk.config, "client", lambda: fake)
    # close look: 300x190 model px around (640, 360) = x0 490, y0 265; 450 real px -> x2 = 900 px (3 per model px)
    assert talk.refine_point(shot, {"x": 640, "y": 360}, "Settings") == {"x": 490 + 133, "y": 265 + 33}
    reply.output_text = '{"found": false}'
    assert talk.refine_point(shot, {"x": 640, "y": 360}, "Settings") == {"x": 640, "y": 360}


def test_3d_requests():
    from zavero.talk import is_3d

    for t in ["heart ni 3D lo explain chey", "show me the earth in 3d", "explain the inside of an engine",
              "దీన్ని త్రీడీ లో చూపించు", "इसे 3डी में समझाओ"]:
        assert is_3d(t), t
    for t in ["open blender", "install 3d paint", "explain this diagram", "draw me a triangle"]:
        assert not is_3d(t), t


def test_clean_scene():
    from zavero.talk import clean_scene

    out = clean_scene({"title": "Heart", "answer": "The heart pumps blood.", "parts": [
        {"shape": "sphere", "pos": [0, 0, 0], "size": [1.2], "color": "red", "label": "Left ventricle", "step": 3},
        {"shape": "tube", "points": [[0, 1, 0]], "size": [0.2], "color": "#1E66F5", "label": "Vena cava", "step": 5},
        {"shape": "laser", "pos": [99, -99, "x"], "size": [0], "rotation": [720, 0, 0], "color": "zz", "step": 3},
        "junk",
    ]})
    p = out["parts"]
    assert len(p) == 3
    assert p[0]["color"] == "#e53935" and p[1]["color"] == "#1e66f5" and p[2]["color"] == "#e57373"
    assert p[1]["shape"] == "cylinder"            # a tube needs 2+ points
    assert p[2]["shape"] == "sphere" and p[2]["pos"] == [4, -4, 0] and p[2]["size"][0] == 0.02
    assert p[2]["rotation"][0] == 360
    assert [s["n"] for s in out["steps"]] == [1, 2] and [x["step"] for x in p] == [1, 2, 1]  # 3, 5 -> 1, 2
    assert out["steps"][0]["label"] == "Left ventricle"
