from datetime import date, datetime, timedelta, timezone

import pytest

from src import dashboard, db

TODAY = date.today()
CFG = {"brand": {"name": "B", "instagram": "me"},
       "monitoring": {"posts_lookback_days": 30, "daily_top_posts": 25},
       "scoring": {"views_per_follower": 0.3, "engagement_rate": 0.25,
                   "total_engagement": 0.2, "raw_views": 0.15, "comments": 0.1,
                   "engagement_per_follower": 0.25, "ai_weight": 0.2},
       "ideas": {"daily_count": 10}}


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(str(tmp_path / "t.db"))
    db.init_schema(c)
    yield c
    c.close()


def add(conn, username, code, likes, days_ago=1, ours=False, snaps=None):
    aid = db.upsert_account(conn, username, followers=1000)
    posted = datetime.now(timezone.utc) - timedelta(days=days_ago)
    pid = db.upsert_post(conn, {"shortcode": code, "account_id": aid, "is_ours": int(ours),
                                "posted_at": posted.isoformat(), "caption": "<b>x</b>",
                                "url": "https://instagram.com/p/" + code})
    for i, n in enumerate(snaps or [likes]):
        t = (datetime.now(timezone.utc) - timedelta(days=len(snaps or [1]) - i)).isoformat()
        db.add_snapshot(conn, pid, None, n, 0 if n is not None else None, None, captured_at=t)
    return pid


def test_suggested_posts_are_measured_against_our_normal(conn):
    for i in range(5):
        add(conn, "me", f"N{i}", 100, ours=True)
    ideas = [db.save_idea(conn, {"concept": "c", "hook": "h"}, None, "LOW", 80)
             for _ in range(5)]
    for i, idea in enumerate(ideas):
        add(conn, "me", f"HIT{i}", 300, ours=True)
        db.link_idea(conn, idea, f"HIT{i}")

    ctx = dashboard.build_context(conn, CFG)

    hit = next(p for p in ctx["ours"] if p["shortcode"] == "HIT0")
    # normal = median of the 9 other posts (4 others at 300, 5 at 100) = 100
    assert hit["vs_normal"] == 3.0
    assert hit["er"] == 0.3, "300 engagement / 1000 followers"
    assert ctx["overall"]["suggested"] == 5
    assert ctx["overall"]["suggested_vs_normal"] == 3.0
    assert ctx["overall"]["suggested_n"] == 5
    yesterday = next(d for d in ctx["daily"] if d["posts"])
    assert yesterday["posts"] == 10 and yesterday["suggested"] == 5
    assert sum(w["posts"] for w in ctx["weekly"]) == 10


def test_group_multiple_is_blank_below_min_sample_but_counted(conn):
    for i in range(3):
        add(conn, "me", f"N{i}", 100, ours=True)
    add(conn, "me", "HIT", 300, ours=True)
    db.link_idea(conn, db.save_idea(conn, {"concept": "c", "hook": "h"}, None, "LOW", 80), "HIT")
    ctx = dashboard.build_context(conn, CFG)
    assert ctx["overall"]["suggested_vs_normal"] is None, "one post is not evidence"
    assert ctx["overall"]["suggested_n"] == 1
    assert "n=1" in dashboard.render(ctx)


def test_unmeasured_post_is_none_not_zero(conn):
    for i in range(3):
        add(conn, "me", f"N{i}", 100, ours=True)
    add(conn, "me", "BLANK", None, ours=True)
    ctx = dashboard.build_context(conn, CFG)
    blank = next(p for p in ctx["ours"] if p["shortcode"] == "BLANK")
    assert blank["engagement"] is None
    assert blank["vs_normal"] is None
    assert ctx["overall"]["engagement"] == 100.0, "unmeasured must not drag the average"


def test_top_posts_and_traction_exclude_our_own(conn):
    add(conn, "rival", "R1", 50, snaps=[10, 50])
    add(conn, "rival", "R2", 500, snaps=[480, 500])
    add(conn, "me", "MINE", 9999, ours=True)
    ctx = dashboard.build_context(conn, CFG)
    assert [p["shortcode"] for p in ctx["top_posts"]] == ["R2", "R1"]
    assert [p["shortcode"] for p in ctx["rising"]] == ["R1", "R2"]
    assert ctx["rising"][0]["traction"] == pytest.approx(40, rel=0.01)


def test_render_escapes_captions_and_hides_forms_when_static(conn):
    add(conn, "me", "MINE", 10, ours=True)
    ctx = dashboard.build_context(conn, CFG)
    static = dashboard.render(ctx)
    assert "<b>x</b>" not in static and "&lt;b&gt;x&lt;/b&gt;" in static
    assert "/link" not in static
    assert 'action="/link"' in dashboard.render(ctx, interactive=True)


def test_hidden_likes_are_unknown_not_minus_one(conn):
    """Apify reports -1 when the owner hides likes."""
    for i in range(3):
        add(conn, "me", f"N{i}", 100, ours=True)
    add(conn, "me", "HIDDEN", -1, ours=True)
    ctx = dashboard.build_context(conn, CFG)
    hidden = next(p for p in ctx["ours"] if p["shortcode"] == "HIDDEN")
    assert hidden["likes"] is None
    assert hidden["engagement"] == 0, "the measured 0 comments still count"


def test_previous_brand_and_inactive_accounts_are_excluded(conn):
    add(conn, "oldbrand", "OLD", 500, ours=True)  # flagged ours under the last brand
    add(conn, "retired", "R", 900)
    db.upsert_account(conn, "retired", active=0)
    add(conn, "me", "MINE", 10, ours=True)
    ctx = dashboard.build_context(conn, CFG)
    assert [p["shortcode"] for p in ctx["ours"]] == ["MINE"]
    assert ctx["top_posts"] == []


def test_lists_are_capped_at_ten(conn):
    for i in range(15):
        add(conn, "rival", f"R{i}", 100 + i, snaps=[i, 100 + i])
    ctx = dashboard.build_context(conn, {**CFG, "monitoring": {**CFG["monitoring"], "daily_top_posts": 25}})
    assert len(ctx["top_posts"]) == 10
    assert len(ctx["rising"]) == 10
