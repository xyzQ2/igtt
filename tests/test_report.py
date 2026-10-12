from pathlib import Path

from src import report


CONTEXT = {
    "report_date": "2026-09-07",
    "brand": {"name": "Drink Toilet Wine", "instagram": "drinktoiletwine"},
    "stats": {"accounts": 67, "posts": 184, "text_analyzed": 40, "video_analyzed": 15},
    "fastest_rising": {
        "username": "wineexample", "url": "https://instagram.com/p/A",
        "views": 487000, "owner_followers": 82000, "views_per_follower": 5.9,
        "final_score": 96.0, "accelerating": True,
        "analysis": {"why_it_overperformed": ["a", "b", "c"],
                     "reusable_pattern": "Insider frustration + setup + reaction"},
    },
    "top_posts": [
        {"username": "wineexample", "url": "https://instagram.com/p/A",
         "caption": "wine", "views": 487000, "likes": 61200, "comments": 3140,
         "final_score": 96.0, "accelerating": True,
         "analysis": {"hook": "POV", "reusable_pattern": "X"}},
    ],
    "patterns": [
        {"pattern": "Service-industry confessionals", "occurrences_7d": 18,
         "occurrences_30d": 40, "trend_direction": "rising", "dtw_relevance": 92},
    ],
    "ideas": [
        {"id": 1, "concept": "The Sommelier Is Watching",
         "hook": "POV: you told the sommelier you actually like $12 wine",
         "script": "...", "caption": "...", "cta": "tag someone",
         "format": "Reel", "difficulty": "easy", "confidence": 88,
         "similarity_risk": "LOW", "shot_list": ["a", "b"]},
    ],
    "our_results": [
        {"shortcode": "OURS1", "views": 12000, "baseline_views": 4000,
         "vs_baseline": 3.0},
    ],
}


def test_render_report_writes_file(tmp_path):
    out = tmp_path / "latest.html"
    report.render_report(CONTEXT, str(out))
    html = out.read_text()
    assert "Drink Toilet Wine" in html
    assert "Service-industry confessionals" in html
    assert "The Sommelier Is Watching" in html
    assert "wineexample" in html


def test_render_report_escapes_captions(tmp_path):
    ctx = dict(CONTEXT)
    ctx["top_posts"] = [{**CONTEXT["top_posts"][0],
                         "caption": "<script>alert(1)</script>"}]
    out = tmp_path / "latest.html"
    report.render_report(ctx, str(out))
    html = out.read_text()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_report_includes_idea_id_for_dispatch(tmp_path):
    out = tmp_path / "latest.html"
    report.render_report(CONTEXT, str(out))
    html = out.read_text()
    assert "idea_id" in html or "#1" in html
    assert "Pick idea #1" in html


def test_render_report_shows_em_dash_for_unmeasured_our_results(tmp_path):
    """None views/baseline is unmeasured, not a genuine zero — showing '0
    views' makes a real post look like a total flop."""
    ctx = dict(CONTEXT)
    ctx["our_results"] = [
        {"shortcode": "UNMEASURED", "views": None, "baseline_views": None,
         "vs_baseline": None},
    ]
    out = tmp_path / "latest.html"
    report.render_report(ctx, str(out))
    html = out.read_text()
    section = html[html.find("UNMEASURED"):]
    assert "— views" in section
    assert "— baseline" in section
    assert "0 views" not in section
    assert "0 baseline" not in section


def test_send_email_returns_false_when_disabled():
    assert report.send_email("<p>hi</p>", "subject", {"enabled": False}) is False


def test_send_email_returns_false_on_smtp_failure(mocker):
    mocker.patch("src.report.smtplib.SMTP", side_effect=Exception("no route"))
    cfg = {"enabled": True, "host": "h", "port": 587, "user": "u",
           "password": "p", "to": "t@example.com"}
    assert report.send_email("<p>hi</p>", "subject", cfg) is False


def test_send_email_sends_when_configured(mocker):
    smtp = mocker.patch("src.report.smtplib.SMTP")
    cfg = {"enabled": True, "host": "h", "port": 587, "user": "u",
           "password": "p", "to": "t@example.com"}
    assert report.send_email("<p>hi</p>", "subject", cfg) is True
    smtp.return_value.__enter__.return_value.send_message.assert_called_once()
