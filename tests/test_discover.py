import json
from pathlib import Path

import pytest

import discover
from src import apify, db

FIXTURE = Path(__file__).parent / "fixtures" / "apify_hashtag.json"


def fake_response(text):
    class Block:
        def __init__(self, t):
            self.text = t
    class Msg:
        def __init__(self, t):
            self.content = [Block(t)]
    return Msg(text)


@pytest.fixture()
def db_path(tmp_path):
    p = str(tmp_path / "t.db")
    conn = db.connect(p)
    db.init_schema(conn)
    conn.close()
    return p


def test_search_hashtag_accounts_dedupes_by_username(mocker):
    m = mocker.patch("src.apify.requests.post")
    m.return_value.status_code = 200
    m.return_value.json.return_value = json.loads(FIXTURE.read_text())
    out = apify.search_hashtag_accounts("tok", ["winememes"], limit=50)
    usernames = [c["username"] for c in out]
    assert usernames == ["winememequeen", "corporate_wine_seminars"]
    queen = out[0]
    assert queen["followers"] == 145000
    assert len(queen["sample_captions"]) == 2


def test_search_hashtag_accounts_empty_on_failure(mocker):
    mocker.patch("src.apify.requests.post", side_effect=Exception("boom"))
    assert apify.search_hashtag_accounts("tok", ["x"], 50) == []


def test_search_hashtag_accounts_sends_tags_as_a_list(mocker):
    """Joining the tags into one `search` string matched no hashtag and found
    0 accounts in production for weeks."""
    m = mocker.patch("src.apify.requests.post")
    m.return_value.json.return_value = []
    apify.search_hashtag_accounts("tok", ["winememes", "serverlife"], limit=200)
    url, body = m.call_args.args[0], m.call_args.kwargs["json"]
    assert "instagram-hashtag-scraper" in url
    assert body["hashtags"] == ["winememes", "serverlife"]
    assert body["resultsLimit"] == 100  # per tag


def test_search_hashtag_accounts_empty_on_error_payload(mocker):
    m = mocker.patch("src.apify.requests.post")
    m.return_value.json.return_value = {"error": {"type": "user-or-token-not-found"}}
    assert apify.search_hashtag_accounts("tok", ["x"], 50) == []


def test_score_candidates_attaches_scores(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response(json.dumps([
        {"username": "winememequeen", "relevance_score": 88, "category": "wine memes",
         "reason": "same audience, same humour"},
        {"username": "corporate_wine_seminars", "relevance_score": 12,
         "category": "wine", "reason": "corporate tone, wrong audience"},
    ]))
    out = discover.score_candidates(
        client,
        [{"username": "winememequeen", "followers": 145000, "sample_captions": []},
         {"username": "corporate_wine_seminars", "followers": 900,
          "sample_captions": []}],
        {"name": "DTW", "voice": "v"}, "claude-opus-5",
        categories=["wine", "wine memes"],
    )
    by_name = {c["username"]: c for c in out}
    assert by_name["winememequeen"]["relevance_score"] == 88
    assert by_name["corporate_wine_seminars"]["relevance_score"] == 12


def test_score_candidates_returns_empty_on_bad_response(mocker):
    client = mocker.Mock()
    client.messages.create.return_value = fake_response("nope")
    assert discover.score_candidates(client, [{"username": "a"}],
                                     {"name": "D", "voice": "v"},
                                     "claude-opus-5", categories=[]) == []


def test_score_candidates_uses_16000_max_tokens(mocker):
    """200 hashtag candidates + up to 75 existing accounts can run to
    thousands of output tokens; 4000 truncates and fails silently."""
    client = mocker.Mock()
    client.messages.create.return_value = fake_response("[]")
    discover.score_candidates(client, [{"username": "a"}], {"name": "D", "voice": "v"},
                              "claude-opus-5", categories=[])
    assert client.messages.create.call_args.kwargs["max_tokens"] == 16000


def test_score_candidates_logs_error_not_warning_on_bad_response(mocker, caplog):
    """A truncated/bad response on a non-empty candidate list must not just be
    a warning — that lets the weekly run silently no-op while exiting 0."""
    client = mocker.Mock()
    client.messages.create.return_value = fake_response("not json")
    with caplog.at_level("WARNING", logger="discover"):
        discover.score_candidates(client, [{"username": "a"}],
                                  {"name": "D", "voice": "v"},
                                  "claude-opus-5", categories=[])
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_run_discovery_activates_and_deactivates(db_path, mocker, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")

    conn = db.connect(db_path)
    stale_id = db.upsert_account(conn, "corporate_wine_seminars", active=1)
    conn.close()

    mocker.patch("discover.apify.search_hashtag_accounts", return_value=[
        {"username": "winememequeen", "followers": 145000, "sample_captions": []},
        {"username": "corporate_wine_seminars", "followers": 900,
         "sample_captions": []},
    ])
    mocker.patch("discover.score_candidates", return_value=[
        {"username": "winememequeen", "relevance_score": 88, "category": "wine memes"},
        {"username": "corporate_wine_seminars", "relevance_score": 12,
         "category": "wine"},
    ])
    mocker.patch("discover.Anthropic", return_value=mocker.Mock())

    stats = discover.run_discovery(config_path="config.yaml", db_path=db_path)
    assert stats["activated"] == 1
    assert stats["deactivated"] == 1

    conn = db.connect(db_path)
    active = [r["username"] for r in db.get_active_accounts(conn)]
    assert "winememequeen" in active
    assert "corporate_wine_seminars" not in active
    conn.close()


def test_run_discovery_caps_candidates_before_scoring(db_path, mocker, monkeypatch):
    """200 hashtag results + up to 75 existing accounts can exceed what a single
    call can score reliably; cap the list at a sane number before calling out."""
    monkeypatch.setenv("APIFY_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")

    conn = db.connect(db_path)
    for i in range(60):
        db.upsert_account(conn, f"existing{i}", active=1)
    conn.close()

    mocker.patch("discover.apify.search_hashtag_accounts", return_value=[
        {"username": f"new{i}", "followers": 1, "sample_captions": []}
        for i in range(150)
    ])
    score_candidates = mocker.patch("discover.score_candidates", return_value=[])
    mocker.patch("discover.Anthropic", return_value=mocker.Mock())

    discover.run_discovery(config_path="config.yaml", db_path=db_path)
    passed_candidates = score_candidates.call_args[0][1]
    assert len(passed_candidates) <= 100


def test_run_discovery_respects_max_accounts(db_path, mocker, monkeypatch):
    """Never activate past monitoring.max_accounts — that is the spend ceiling."""
    monkeypatch.setenv("APIFY_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")
    conn = db.connect(db_path)
    for i in range(75):
        db.upsert_account(conn, f"existing{i}", relevance_score=80, active=1)
    conn.close()

    mocker.patch("discover.apify.search_hashtag_accounts",
                 return_value=[{"username": "newcomer", "followers": 1,
                                "sample_captions": []}])
    mocker.patch("discover.score_candidates",
                 return_value=[{"username": "newcomer", "relevance_score": 99,
                                "category": "wine"}])
    mocker.patch("discover.Anthropic", return_value=mocker.Mock())

    stats = discover.run_discovery(config_path="config.yaml", db_path=db_path)
    assert stats["activated"] == 0

    conn = db.connect(db_path)
    assert len(db.get_active_accounts(conn)) == 75
    conn.close()


def test_run_discovery_preserves_existing_accounts_before_cap(db_path, mocker, monkeypatch):
    """Existing active accounts must survive the MAX_CANDIDATES cap so they can
    be re-evaluated. Cap should never slice away all existing accounts."""
    monkeypatch.setenv("APIFY_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")

    conn = db.connect(db_path)
    for i in range(3):
        db.upsert_account(conn, f"existing{i}", active=1)
    conn.close()

    mocker.patch("discover.apify.search_hashtag_accounts",
                 return_value=[{"username": f"new{i}", "followers": 1,
                                "sample_captions": []} for i in range(120)])
    score_candidates = mocker.patch("discover.score_candidates", return_value=[])
    mocker.patch("discover.Anthropic", return_value=mocker.Mock())

    discover.run_discovery(config_path="config.yaml", db_path=db_path)

    # Inspect what score_candidates was called with
    passed_candidates = score_candidates.call_args[0][1]

    # All 3 existing accounts must be in the list
    passed_usernames = [c["username"] for c in passed_candidates]
    assert "existing0" in passed_usernames
    assert "existing1" in passed_usernames
    assert "existing2" in passed_usernames

    # List must be capped at MAX_CANDIDATES (100)
    assert len(passed_candidates) <= 100
