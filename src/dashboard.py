"""The dashboard: top posts, traction, and how our suggested content performs.

Read-only over the database and free (no AI calls), so it can be rebuilt at any
time — by the daily run, and live by serve.py on every page load.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median

from jinja2 import Environment, FileSystemLoader

from src import db, score

TEMPLATE_DIR = Path(__file__).parent / "templates"
MIN_SAMPLE = 5  # fewer posts than this and an average multiple is noise, not evidence
SHOW = 10  # rows per dashboard list; the daily report keeps monitoring.daily_top_posts


def engagement(m: dict):
    """likes + comments + shares. None when nothing was measured — never 0."""
    return score.post_metrics(m)["total_engagement"]


def _avg(values):
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _day(posted_at) -> date | None:
    try:
        return datetime.fromisoformat(posted_at).date()
    except (TypeError, ValueError):
        return None


def _traction(snaps: list):
    """Engagement gained per day between the last two snapshots. None without two."""
    usable = [s for s in snaps if engagement(s) is not None]
    if len(usable) < 2:
        return None
    a, b = usable[-2], usable[-1]
    days = (datetime.fromisoformat(b["captured_at"])
            - datetime.fromisoformat(a["captured_at"])).total_seconds() / 86400
    return (engagement(b) - engagement(a)) / days if days > 0 else None


def build_context(conn, cfg: dict, today: date | None = None) -> dict:
    today = today or date.today()
    mon = cfg["monitoring"]
    analyses = db.analyses_by_post(conn)

    rows = []
    for r in db.posts_since(conn, 90):
        snaps = [dict(s) for s in db.get_snapshots(conn, r["id"])]
        latest = snaps[-1] if snaps else {}
        rows.append({**dict(r), **{k: score.count(latest.get(k)) for k in
                                   ("views", "likes", "comments", "shares")},
                     "engagement": engagement(latest) if latest else None,
                     "traction": _traction(snaps), "analysis": analyses.get(r["id"]),
                     # The benchmark-comparable figure: (likes + comments + shares) / followers.
                     "er": score.post_metrics({**latest, "owner_followers": r["owner_followers"]})
                     ["engagement_per_follower"] if latest else None,
                     "day": _day(r["posted_at"])})

    window_start = today - timedelta(days=mon["posts_lookback_days"])
    theirs = [p for p in rows if not p["is_ours"] and p["username"] != cfg["brand"]["instagram"]
              and p["day"] and p["day"] >= window_start]
    ranked = score.score_posts(theirs, cfg["scoring"])
    for p in ranked:
        ai = (p["analysis"] or {}).get("ai_virality_score")
        p["final_score"] = score.final_score(p["performance_score"], ai,
                                             cfg["scoring"]["ai_weight"])
    ranked.sort(key=lambda p: p["final_score"], reverse=True)
    rising = sorted([p for p in theirs if p["traction"]],
                    key=lambda p: p["traction"], reverse=True)[:SHOW]

    # Our posts, each against the median engagement of our other posts.
    ideas = [dict(i, brief=json.loads(i["brief_json"]))
             for i in db.get_recent_ideas(conn, 60)]
    idea_by_code = {i["posted_shortcode"]: i for i in ideas if i["posted_shortcode"]}
    # is_ours outlives a brand change; only the current handle's posts are ours.
    own = cfg["brand"]["instagram"]
    ours = [p for p in rows if p["is_ours"] and p["username"] == own]
    for p in ours:
        others = [o["engagement"] for o in ours
                  if o is not p and o["engagement"] is not None]
        base = median(others) if len(others) >= 3 else None
        p["vs_normal"] = (p["engagement"] / base
                          if p["engagement"] is not None and base else None)
        p["idea"] = idea_by_code.get(p["shortcode"])

    def multiple(posts):
        """Average multiple of normal and how many measured posts it rests on.
        The multiple is None below MIN_SAMPLE — the count is still shown."""
        vals = [p["vs_normal"] for p in posts if p["vs_normal"] is not None]
        return (_avg(vals) if len(vals) >= MIN_SAMPLE else None), len(vals)

    def summary(posts):
        sug = [p for p in posts if p["idea"]]
        other = [p for p in posts if not p["idea"]]
        sug_x, sug_n = multiple(sug)
        other_x, other_n = multiple(other)
        return {"posts": len(posts), "suggested": len(sug),
                "engagement": _avg(p["engagement"] for p in posts),
                "er": _avg(p["er"] for p in posts),
                "suggested_vs_normal": sug_x, "suggested_n": sug_n,
                "other_vs_normal": other_x, "other_n": other_n}

    daily = []
    for n in range(13, -1, -1):
        d = today - timedelta(days=n)
        daily.append({"label": d.strftime("%a %d %b"),
                      **summary([p for p in ours if p["day"] == d])})
    weekly = []
    monday = today - timedelta(days=today.weekday())
    for n in range(7, -1, -1):
        start = monday - timedelta(weeks=n)
        weekly.append({"label": "Week of " + start.strftime("%d %b"),
                       **summary([p for p in ours
                                  if p["day"] and start <= p["day"] < start + timedelta(7)])})
    peak = max((d["engagement"] or 0 for d in daily), default=0)

    run = db.last_run(conn)
    return {
        "brand": cfg["brand"], "today": today.isoformat(),
        "last_run": dict(run, stats=json.loads(run["stats"])) if run else None,
        "top_posts": ranked[:SHOW], "rising": rising,
        "ours": ours, "daily": daily, "weekly": weekly, "peak": peak or 1,
        "overall": summary([p for p in ours if p["day"] and p["day"] >= today - timedelta(30)]),
        "ideas": ideas[: cfg["ideas"]["daily_count"] * 3], "min_sample": MIN_SAMPLE,
    }


def render(context: dict, interactive: bool = False, message: str = "") -> str:
    """HTML for the dashboard. Autoescape is on: captions are hostile input."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    return env.get_template("dashboard.html").render(
        **context, interactive=interactive, message=message)
