import json

import pytest

from src import db, ideas


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(str(tmp_path / "t.db"))
    db.init_schema(c)
    yield c
    c.close()


def fake_response(text):
    class Block:
        def __init__(self, t):
            self.text = t
    class Msg:
        def __init__(self, t):
            self.content = [Block(t)]
    return Msg(text)


def brief(concept, risk="LOW", confidence=80):
    return {
        "concept": concept, "why_now": "pattern rising", "source_pattern": "P",
        "hook": "POV: ...", "opening_frame": "close on glass", "script": "...",
        "on_screen_text": "...", "shot_list": ["a", "b"], "caption": "c",
        "cta": "tag a coworker", "format": "Reel", "difficulty": "easy",
        "confidence": confidence, "similarity_risk": risk,
    }


CONTEXT = {
    "brand": {"name": "Drink Toilet Wine", "voice": "irreverent"},
    "top_posts": [], "patterns": [], "previous_ideas": [], "our_results": [],
}


def test_generate_ideas_returns_parsed_briefs(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response(
        json.dumps([brief("The Sommelier Is Watching")])
    )
    out = ideas.generate_ideas(client, CONTEXT, "claude-opus-5", count=10)
    assert out[0]["concept"] == "The Sommelier Is Watching"


def test_high_similarity_ideas_are_rejected(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response(json.dumps([
        brief("safe one", risk="LOW"),
        brief("too close to a real post", risk="HIGH"),
        brief("borderline", risk="MEDIUM"),
    ]))
    out = ideas.generate_ideas(client, CONTEXT, "claude-opus-5", count=10)
    concepts = [i["concept"] for i in out]
    assert "too close to a real post" not in concepts
    assert concepts == ["safe one", "borderline"]


def test_generate_ideas_truncates_to_count(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response(
        json.dumps([brief(f"idea {i}") for i in range(20)])
    )
    out = ideas.generate_ideas(client, CONTEXT, "claude-opus-5", count=10)
    assert len(out) == 10


def test_generate_ideas_survives_api_failure(mocker):
    client = mocker.Mock()
    client.messages.create.side_effect = Exception("overloaded")
    assert ideas.generate_ideas(client, CONTEXT, "claude-opus-5", count=10) == []


def test_save_and_get_idea_roundtrip(conn):
    idea_id = db.save_idea(conn, brief("x"), None, "LOW", 80.0)
    row = db.get_idea(conn, idea_id)
    assert json.loads(row["brief_json"])["concept"] == "x"
    assert row["status"] == "new"


def test_get_recent_ideas_newest_first(conn):
    a = db.save_idea(conn, brief("first"), None, "LOW", 50.0)
    b = db.save_idea(conn, brief("second"), None, "LOW", 50.0)
    rows = db.get_recent_ideas(conn, limit=5)
    assert [r["id"] for r in rows] == [b, a]
