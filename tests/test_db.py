import sqlite3

import pytest

from src import db


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(str(tmp_path / "test.db"))
    db.init_schema(c)
    yield c
    c.close()


def test_init_schema_creates_all_tables(conn):
    names = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "accounts", "posts", "post_snapshots", "analyses",
        "patterns", "ideas", "repost_candidates",
    } <= names


def test_upsert_account_is_idempotent(conn):
    a = db.upsert_account(conn, "wineexample", category="wine", followers=82000)
    b = db.upsert_account(conn, "wineexample", category="wine", followers=90000)
    assert a == b
    rows = conn.execute("SELECT followers FROM accounts").fetchall()
    assert len(rows) == 1
    assert rows[0]["followers"] == 90000


def test_upsert_post_is_idempotent_on_shortcode(conn):
    account_id = db.upsert_account(conn, "wineexample")
    post = {
        "platform": "instagram", "shortcode": "ABC123", "account_id": account_id,
        "url": "https://instagram.com/p/ABC123", "video_url": None,
        "thumbnail_url": None, "caption": "hello", "content_type": "Video",
        "posted_at": "2026-09-01T12:00:00", "duration_sec": 14.0, "is_ours": 0,
    }
    first = db.upsert_post(conn, post)
    post["caption"] = "hello edited"
    second = db.upsert_post(conn, post)
    assert first == second
    rows = conn.execute("SELECT caption FROM posts").fetchall()
    assert len(rows) == 1
    assert rows[0]["caption"] == "hello edited"


def test_snapshots_append_and_preserve_null(conn):
    account_id = db.upsert_account(conn, "wineexample")
    post_id = db.upsert_post(conn, {
        "platform": "instagram", "shortcode": "ABC123", "account_id": account_id,
        "url": "u", "video_url": None, "thumbnail_url": None, "caption": "c",
        "content_type": "Sidecar", "posted_at": "2026-09-01T12:00:00",
        "duration_sec": None, "is_ours": 0,
    })
    db.add_snapshot(conn, post_id, views=None, likes=10, comments=2, shares=None,
                    captured_at="2026-09-01T13:00:00")
    db.add_snapshot(conn, post_id, views=None, likes=30, comments=5, shares=None,
                    captured_at="2026-09-02T13:00:00")
    snaps = db.get_snapshots(conn, post_id)
    assert len(snaps) == 2
    assert snaps[0]["likes"] == 10 and snaps[1]["likes"] == 30
    assert snaps[0]["views"] is None
    assert snaps[0]["shares"] is None


def test_get_active_accounts_excludes_inactive(conn):
    db.upsert_account(conn, "keep", active=1)
    db.upsert_account(conn, "drop", active=0)
    names = [r["username"] for r in db.get_active_accounts(conn)]
    assert names == ["keep"]


def test_upsert_account_without_active_preserves_deactivated(conn):
    db.upsert_account(conn, "wineexample", active=0)
    db.upsert_account(conn, "wineexample", followers=1000)
    row = conn.execute(
        "SELECT active FROM accounts WHERE username = ?", ("wineexample",)
    ).fetchone()
    assert row["active"] == 0


def test_upsert_account_new_row_without_active_is_active(conn):
    db.upsert_account(conn, "wineexample")
    row = conn.execute(
        "SELECT active FROM accounts WHERE username = ?", ("wineexample",)
    ).fetchone()
    assert row["active"] == 1


def test_link_idea_moves_a_post_between_ideas_and_unlinks(conn):
    """One post belongs to at most one idea; re-picking moves it, None unlinks."""
    first = db.save_idea(conn, {"concept": "a"}, None, "LOW", 80.0)
    second = db.save_idea(conn, {"concept": "b"}, None, "LOW", 80.0)

    db.link_idea(conn, first, "CODE1")
    assert db.get_idea(conn, first)["posted_shortcode"] == "CODE1"
    assert db.get_idea(conn, first)["status"] == "posted"

    db.link_idea(conn, second, "CODE1")
    assert db.get_idea(conn, first)["posted_shortcode"] is None
    assert db.get_idea(conn, first)["status"] == "new"
    assert db.get_idea(conn, second)["posted_shortcode"] == "CODE1"

    db.link_idea(conn, None, "CODE1")
    assert db.get_idea(conn, second)["posted_shortcode"] is None


def test_link_idea_rejects_unknown_idea(conn):
    with pytest.raises(ValueError):
        db.link_idea(conn, 999, "CODE1")


def test_set_watchlist_activates_exactly_the_list_plus_our_own(conn):
    db.upsert_account(conn, "old", active=1)
    db.upsert_account(conn, "me", active=1)
    db.set_watchlist(conn, ["@New", " kept ", ""], own="me")
    active = {r["username"] for r in db.get_active_accounts(conn)}
    assert active == {"new", "kept", "me"}


def test_upsert_account_explicit_active_reactivates(conn):
    db.upsert_account(conn, "wineexample", active=0)
    db.upsert_account(conn, "wineexample", active=1)
    row = conn.execute(
        "SELECT active FROM accounts WHERE username = ?", ("wineexample",)
    ).fetchone()
    assert row["active"] == 1
