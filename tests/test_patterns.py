import json
from datetime import datetime, timedelta, timezone

import pytest

from src import db, patterns


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


PATTERNS = [
    {"pattern": "Service-industry confessionals",
     "description": "Insider admits something about the job",
     "occurrences_7d": 18, "occurrences_30d": 40, "occurrences_90d": 95,
     "avg_performance": 88.2, "trend_direction": "rising", "dtw_relevance": 92},
]


def test_save_and_read_analysis(conn):
    account_id = db.upsert_account(conn, "wineexample")
    # Relative to now: get_analyses_since() measures against the real clock, so a
    # hardcoded date silently ages out of the window.
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    post_id = db.upsert_post(conn, {
        "shortcode": "A1", "account_id": account_id,
        "posted_at": recent,
    })
    db.save_analysis(conn, post_id, "text", {"reusable_pattern": "x"}, 89.0,
                     "claude-sonnet-5")
    rows = db.get_analyses_since(conn, days=7)
    assert len(rows) == 1
    assert json.loads(rows[0]["json"])["reusable_pattern"] == "x"
    assert rows[0]["shortcode"] == "A1"


def test_save_analysis_is_idempotent_per_tier(conn):
    account_id = db.upsert_account(conn, "wineexample")
    post_id = db.upsert_post(conn, {"shortcode": "A1", "account_id": account_id,
                                    "posted_at": "2026-09-06T10:00:00+00:00"})
    db.save_analysis(conn, post_id, "text", {"a": 1}, 50.0, "m")
    db.save_analysis(conn, post_id, "text", {"a": 2}, 60.0, "m")
    rows = conn.execute("SELECT json FROM analyses").fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0]["json"])["a"] == 2


def test_get_analyses_since_excludes_old_posts(conn):
    account_id = db.upsert_account(conn, "wineexample")
    old = db.upsert_post(conn, {"shortcode": "OLD", "account_id": account_id,
                                "posted_at": "2020-01-01T00:00:00+00:00"})
    db.save_analysis(conn, old, "text", {"a": 1}, 10.0, "m")
    assert db.get_analyses_since(conn, days=7) == []


def test_save_pattern_upserts_on_name(conn):
    db.save_pattern(conn, {**PATTERNS[0], "occurrences_7d": 3})
    db.save_pattern(conn, PATTERNS[0])
    rows = db.get_patterns(conn)
    assert len(rows) == 1
    assert rows[0]["occurrences_7d"] == 18


def test_detect_patterns_parses_array(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response(json.dumps(PATTERNS))
    out = patterns.detect_patterns(
        client, {"7": [{"reusable_pattern": "x"}], "30": [], "90": []},
        "claude-opus-5", brand={"name": "Drink Toilet Wine"})
    assert out[0]["pattern"] == "Service-industry confessionals"
    assert out[0]["trend_direction"] == "rising"


def test_detect_patterns_returns_empty_with_no_analyses(mocker):
    client = mocker.Mock()
    out = patterns.detect_patterns(client, {"7": [], "30": [], "90": []},
                                   "claude-opus-5", brand={"name": "D"})
    assert out == []
    client.messages.create.assert_not_called()


def test_detect_patterns_survives_bad_response(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response("sorry")
    out = patterns.detect_patterns(client, {"7": [{"reusable_pattern": "x"}],
                                            "30": [], "90": []},
                                   "claude-opus-5", brand={"name": "D"})
    assert out == []
