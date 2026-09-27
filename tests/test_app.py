import json
import logging
from pathlib import Path

import pytest

import app
from src import db

FIXTURE = Path(__file__).parent / "fixtures" / "apify_instagram.json"


@pytest.fixture()
def cfg_file(tmp_path):
    src = Path("config.yaml").read_text()
    p = tmp_path / "config.yaml"
    p.write_text(src)
    return str(p)


def fake_claude_response(text):
    class Block:
        def __init__(self, t):
            self.text = t
    class Msg:
        def __init__(self, t):
            self.content = [Block(t)]
    return Msg(text)


ANALYSIS = {
    "hook": "POV", "hook_type": "relatability", "payoff": "p",
    "emotional_driver": "e", "humor_mechanism": "h", "social_driver": "s",
    "comment_driver": "c", "rewatch_driver": "r", "visual_structure": "v",
    "caption_role": "cr", "audience": "a", "timing": "t",
    "why_it_overperformed": ["1", "2", "3"], "reusable_pattern": "P",
    "scores": {"hook": 90, "shareability": 80, "originality": 70,
               "relatability": 90, "rewatchability": 80, "cultural_relevance": 60},
    "ai_virality_score": 88,
}
PATTERNS = [{"pattern": "P", "description": "d", "occurrences_7d": 3,
             "occurrences_30d": 5, "occurrences_90d": 9, "avg_performance": 80,
             "trend_direction": "rising", "dtw_relevance": 90}]
IDEAS = [{"concept": "idea one", "why_now": "w", "source_pattern": "P",
          "hook": "h", "opening_frame": "o", "script": "s", "on_screen_text": "t",
          "shot_list": ["a"], "caption": "c", "cta": "cta", "format": "Reel",
          "difficulty": "easy", "confidence": 85, "similarity_risk": "LOW"}]


def test_daily_run_end_to_end(tmp_path, cfg_file, mocker, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")
    monkeypatch.setenv("GEMINI_API_KEY", "t")

    db_path = str(tmp_path / "test.db")
    conn = db.connect(db_path)
    db.init_schema(conn)
    db.upsert_account(conn, "wineexample", category="wine", followers=82000)
    conn.close()

    # Apify returns the fixture
    mocker.patch("app.apify.fetch_profile_posts",
                 return_value=[p for p in
                               (__import__("src.apify", fromlist=["x"]).normalize_post(i)
                                for i in json.loads(FIXTURE.read_text())) if p])

    # Claude answers analysis, patterns, then ideas in that order
    claude = mocker.Mock()
    claude.messages.create.side_effect = [
        fake_claude_response(json.dumps(ANALYSIS)),
        fake_claude_response(json.dumps(ANALYSIS)),
        fake_claude_response(json.dumps(PATTERNS)),
        fake_claude_response(json.dumps(IDEAS)),
    ]
    mocker.patch("app.Anthropic", return_value=claude)

    # Gemini video tier
    mocker.patch("app.analyze.analyze_video", return_value=None)

    report_path = tmp_path / "latest.html"
    stats = app.run_daily(config_path=cfg_file, db_path=db_path,
                          report_path=str(report_path))

    assert stats["posts"] == 2
    assert report_path.exists()
    html = report_path.read_text()
    assert "idea one" in html

    conn = db.connect(db_path)
    assert len(db.get_recent_ideas(conn)) == 1
    assert len(conn.execute("SELECT * FROM post_snapshots").fetchall()) == 2
    conn.close()


def test_daily_run_survives_total_apify_failure(tmp_path, cfg_file, mocker, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")
    db_path = str(tmp_path / "test.db")
    conn = db.connect(db_path)
    db.init_schema(conn)
    db.upsert_account(conn, "wineexample", followers=1000)
    conn.close()

    mocker.patch("app.apify.fetch_profile_posts", return_value=[])
    mocker.patch("app.Anthropic", return_value=mocker.Mock())
    report_path = tmp_path / "latest.html"

    stats = app.run_daily(config_path=cfg_file, db_path=db_path,
                          report_path=str(report_path))
    assert stats["posts"] == 0
    assert report_path.exists(), "an empty day still produces a report"


def test_ai_limits_are_enforced(tmp_path, cfg_file, mocker, monkeypatch):
    """40 text analyses max, regardless of how many posts came back."""
    monkeypatch.setenv("APIFY_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")
    db_path = str(tmp_path / "test.db")
    conn = db.connect(db_path)
    db.init_schema(conn)
    db.upsert_account(conn, "wineexample", followers=1000)
    conn.close()

    many = [{
        "platform": "instagram", "shortcode": f"S{i}", "username": "wineexample",
        "owner_followers": 1000, "url": "u", "video_url": None,
        "thumbnail_url": None, "caption": "c", "content_type": "Video",
        "posted_at": "2026-09-06T10:00:00+00:00", "duration_sec": 10.0,
        "views": 1000 + i, "likes": 10, "comments": 1, "shares": None,
    } for i in range(100)]
    mocker.patch("app.apify.fetch_profile_posts", return_value=many)
    mocker.patch("app.analyze.analyze_text", return_value=ANALYSIS)
    mocker.patch("app.analyze.analyze_video", return_value=None)
    mocker.patch("app.patterns.detect_patterns", return_value=[])
    mocker.patch("app.ideas.generate_ideas", return_value=[])
    mocker.patch("app.Anthropic", return_value=mocker.Mock())

    stats = app.run_daily(config_path=cfg_file, db_path=db_path,
                          report_path=str(tmp_path / "r.html"))
    assert stats["text_analyzed"] == 40


def _one_post(shortcode="S1", username="wineexample", owner_followers=82000):
    return {
        "platform": "instagram", "shortcode": shortcode, "username": username,
        "owner_followers": owner_followers, "url": "u", "video_url": None,
        "thumbnail_url": None, "caption": "c", "content_type": "Video",
        "posted_at": "2026-09-06T10:00:00+00:00", "duration_sec": 10.0,
        "views": 5000, "likes": 100, "comments": 10, "shares": None,
    }


def test_collect_refreshes_account_followers_from_post(tmp_path, cfg_file, mocker,
                                                        monkeypatch):
    """A seeded account's followers are NULL forever unless the collect loop
    refreshes them from what Apify actually reports per post."""
    monkeypatch.setenv("APIFY_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")
    db_path = str(tmp_path / "test.db")
    conn = db.connect(db_path)
    db.init_schema(conn)
    db.upsert_account(conn, "wineexample")  # seeded: followers left NULL
    conn.close()

    mocker.patch("app.apify.fetch_profile_posts", return_value=[_one_post()])
    mocker.patch("app.analyze.analyze_text", return_value=None)
    mocker.patch("app.analyze.analyze_video", return_value=None)
    mocker.patch("app.patterns.detect_patterns", return_value=[])
    mocker.patch("app.ideas.generate_ideas", return_value=[])
    mocker.patch("app.Anthropic", return_value=mocker.Mock())

    app.run_daily(config_path=cfg_file, db_path=db_path,
                 report_path=str(tmp_path / "r.html"))

    conn = db.connect(db_path)
    row = conn.execute("SELECT followers FROM accounts WHERE username = ?",
                       ("wineexample",)).fetchone()
    conn.close()
    assert row["followers"] == 82000


def test_collect_warns_when_no_post_reports_followers(tmp_path, cfg_file, mocker,
                                                       monkeypatch, caplog):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")
    db_path = str(tmp_path / "test.db")
    conn = db.connect(db_path)
    db.init_schema(conn)
    db.upsert_account(conn, "wineexample")
    conn.close()

    mocker.patch("app.apify.fetch_profile_posts",
                 return_value=[_one_post(owner_followers=None)])
    mocker.patch("app.analyze.analyze_text", return_value=None)
    mocker.patch("app.analyze.analyze_video", return_value=None)
    mocker.patch("app.patterns.detect_patterns", return_value=[])
    mocker.patch("app.ideas.generate_ideas", return_value=[])
    mocker.patch("app.Anthropic", return_value=mocker.Mock())

    with caplog.at_level(logging.WARNING, logger="app"):
        app.run_daily(config_path=cfg_file, db_path=db_path,
                      report_path=str(tmp_path / "r.html"))

    assert any(r.levelname == "WARNING" and "owner_followers" in r.message
              for r in caplog.records), (
        "silent degradation is the actual defect — this must be logged, not silent"
    )


def test_collect_binds_real_shortcode_to_posted_idea(tmp_path, cfg_file, mocker,
                                                      monkeypatch):
    """media_publish's id (posted_ref) and the real Instagram shortcode are different
    things; the feedback loop needs the latter bound onto the idea that
    produced it."""
    monkeypatch.setenv("APIFY_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")
    db_path = str(tmp_path / "test.db")
    conn = db.connect(db_path)
    db.init_schema(conn)
    db.upsert_account(conn, "drinktoiletwine", category="own", active=1)
    idea_id = db.save_idea(conn, {"concept": "c", "source_pattern": "P"}, None,
                           "LOW", 80.0)
    db.mark_idea_posted(conn, idea_id, "ig-media-id-1")
    conn.close()

    mocker.patch("app.apify.fetch_profile_posts", return_value=[
        _one_post(shortcode="REALCODE1", username="drinktoiletwine",
                  owner_followers=5000)
    ])
    mocker.patch("app.analyze.analyze_text", return_value=None)
    mocker.patch("app.analyze.analyze_video", return_value=None)
    mocker.patch("app.patterns.detect_patterns", return_value=[])
    mocker.patch("app.ideas.generate_ideas", return_value=[])
    mocker.patch("app.Anthropic", return_value=mocker.Mock())

    app.run_daily(config_path=cfg_file, db_path=db_path,
                 report_path=str(tmp_path / "r.html"))

    conn = db.connect(db_path)
    row = db.get_idea(conn, idea_id)
    conn.close()
    assert row["posted_shortcode"] == "REALCODE1"


def test_collect_never_exceeds_max_accounts(tmp_path, cfg_file, mocker, monkeypatch):
    """max_accounts (75 in config.yaml) is the spend ceiling for collection —
    appending our own account after slicing must never push past it."""
    monkeypatch.setenv("APIFY_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")
    db_path = str(tmp_path / "test.db")
    conn = db.connect(db_path)
    db.init_schema(conn)
    for i in range(75):
        db.upsert_account(conn, f"acct{i}", followers=1000, active=1)
    conn.close()

    mocker.patch("app.apify.fetch_profile_posts", return_value=[])
    mocker.patch("app.Anthropic", return_value=mocker.Mock())
    mocker.patch("app.ideas.generate_ideas", return_value=[])

    stats = app.run_daily(config_path=cfg_file, db_path=db_path,
                          report_path=str(tmp_path / "r.html"))
    assert stats["accounts"] <= 75


def test_daily_run_skips_ideas_on_zero_data_day(tmp_path, cfg_file, mocker,
                                                monkeypatch):
    """A zero-data day must not invent ten ideas from nothing and pollute
    previous_ideas."""
    monkeypatch.setenv("APIFY_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")
    db_path = str(tmp_path / "test.db")
    conn = db.connect(db_path)
    db.init_schema(conn)
    db.upsert_account(conn, "wineexample", followers=1000)
    conn.close()

    mocker.patch("app.apify.fetch_profile_posts", return_value=[])
    mocker.patch("app.Anthropic", return_value=mocker.Mock())
    generate = mocker.patch("app.ideas.generate_ideas", return_value=[])

    app.run_daily(config_path=cfg_file, db_path=db_path,
                 report_path=str(tmp_path / "r.html"))
    generate.assert_not_called()


def test_save_analysis_includes_our_performance_score(tmp_path, cfg_file, mocker,
                                                       monkeypatch):
    """patterns.py reads performance_score back out of the stored analysis
    JSON; the strategist schema never produces that field, so it must be
    merged in here or every pattern's avg_performance is fabricated."""
    monkeypatch.setenv("APIFY_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")
    db_path = str(tmp_path / "test.db")
    conn = db.connect(db_path)
    db.init_schema(conn)
    db.upsert_account(conn, "wineexample", followers=82000)
    conn.close()

    mocker.patch("app.apify.fetch_profile_posts", return_value=[_one_post()])
    mocker.patch("app.analyze.analyze_text", return_value=ANALYSIS)
    mocker.patch("app.analyze.analyze_video", return_value=None)
    mocker.patch("app.patterns.detect_patterns", return_value=[])
    mocker.patch("app.ideas.generate_ideas", return_value=[])
    mocker.patch("app.Anthropic", return_value=mocker.Mock())

    app.run_daily(config_path=cfg_file, db_path=db_path,
                 report_path=str(tmp_path / "r.html"))

    conn = db.connect(db_path)
    row = conn.execute("SELECT json FROM analyses WHERE tier = 'text'").fetchone()
    conn.close()
    payload = json.loads(row["json"])
    assert payload.get("performance_score") is not None


def test_daily_run_fills_missing_follower_counts(tmp_path, cfg_file, mocker, monkeypatch):
    """Post results carry no follower count, so without the details call the
    per-follower metrics (40% of the score) never switch on."""
    monkeypatch.setenv("APIFY_TOKEN", "t")
    db_path = str(tmp_path / "test.db")
    conn = db.connect(db_path)
    db.init_schema(conn)
    db.upsert_account(conn, "wineexample", category="wine")  # followers unknown
    conn.close()

    from src import apify
    posts = [p for p in (apify.normalize_post(i) for i in json.loads(FIXTURE.read_text())) if p]
    for p in posts:
        p["owner_followers"] = None
    mocker.patch("app.apify.fetch_profile_posts", return_value=posts)
    fetch = mocker.patch("app.apify.fetch_follower_counts",
                         return_value={"wineexample": 82000})
    mocker.patch("app.Anthropic").return_value.messages.create.side_effect = Exception("off")
    mocker.patch("app.analyze.analyze_video", return_value=None)
    scored = mocker.spy(app.score, "score_posts")

    app.run_daily(config_path=cfg_file, db_path=db_path,
                  report_path=str(tmp_path / "latest.html"))

    assert "wineexample" in fetch.call_args.args[1]
    assert {p["owner_followers"] for p in scored.call_args.args[0]
            if p["username"] == "wineexample"} == {82000}
    conn = db.connect(db_path)
    row = conn.execute("SELECT followers FROM accounts WHERE username='wineexample'").fetchone()
    assert row["followers"] == 82000
