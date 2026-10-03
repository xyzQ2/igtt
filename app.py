"""Daily run: collect, snapshot, score, analyze, cluster, generate, report."""

import argparse
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

from anthropic import Anthropic

from src import analyze, apify, db, ideas, patterns, report, score
from src.config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("app")

REPO_URL = "https://github.com/xyzQ2/igtt"


def run_daily(config_path: str = "config.yaml", db_path: str | None = None,
              report_path: str = "reports/latest.html") -> dict:
    cfg = load_config(config_path)
    mon = cfg["monitoring"]
    conn = db.connect(db_path or "data/intelligence.db")
    db.init_schema(conn)

    stats = {"accounts": 0, "posts": 0, "text_analyzed": 0, "video_analyzed": 0,
             "failures": 0}

    # 1. Collect ---------------------------------------------------------
    # Reserve one slot for our own account so appending it below can never push
    # the total past max_accounts.
    accounts = db.get_active_accounts(conn)[: mon["max_accounts"] - 1]
    # Our own account is collected and measured exactly like a competitor's.
    own_handle = cfg["brand"]["instagram"]
    own_id = db.upsert_account(conn, own_handle, category="own", active=1)
    if own_handle not in [a["username"] for a in accounts]:
        accounts = list(accounts) + [db.get_account(conn, own_id)]
    stats["accounts"] = len(accounts)
    # ponytail: only accounts with no count, so this costs ~nothing after day one;
    # discover.py refreshes every active account's count weekly.
    missing = [a["username"] for a in accounts if a["followers"] is None]
    counts = apify.fetch_follower_counts(os.environ.get("APIFY_TOKEN", ""), missing)
    for username, n in counts.items():
        db.upsert_account(conn, username, followers=n)
    accounts = [db.get_account(conn, a["id"]) if a["username"] in counts else a
                for a in accounts]
    account_id_by_username = {a["username"]: a["id"] for a in accounts}
    followers_by_username = {a["username"]: a["followers"] for a in accounts}

    raw_posts = apify.fetch_profile_posts(
        os.environ.get("APIFY_TOKEN", ""),
        [a["username"] for a in accounts],
        mon["posts_lookback_days"],
        mon["results_per_account"],
    )
    stats["posts"] = len(raw_posts)
    logger.info("collected %d posts from %d accounts", len(raw_posts), len(accounts))
    if not raw_posts:
        # 0 posts across every account means Apify failed (credit out, auth) —
        # skip the paid Claude calls; main() exits 1 so the run shows red.
        logger.error("collected 0 posts — skipping analysis, patterns, ideas, report")
        conn.close()
        return stats

    # 2. Store and snapshot ----------------------------------------------
    posts = []
    for p in raw_posts:
        username = p.get("username")
        account_id = account_id_by_username.get(username)
        if account_id is None:
            account_id = db.upsert_account(conn, username,
                                           followers=p.get("owner_followers"))
            account_id_by_username[username] = account_id
        is_ours = username == own_handle
        post_id = db.upsert_post(conn, {
            "platform": p["platform"], "shortcode": p["shortcode"],
            "account_id": account_id, "url": p["url"], "video_url": p["video_url"],
            "thumbnail_url": p["thumbnail_url"], "caption": p["caption"],
            "content_type": p["content_type"], "posted_at": p["posted_at"],
            "duration_sec": p["duration_sec"], "is_ours": 1 if is_ours else 0,
        })
        if is_ours:
            db.bind_idea_shortcode(conn, p["shortcode"])
        db.add_snapshot(conn, post_id, p["views"], p["likes"], p["comments"],
                        p["shares"])
        if p.get("owner_followers") is not None:
            db.upsert_account(conn, username, followers=p["owner_followers"])
        enriched = dict(p)
        enriched["post_id"] = post_id
        enriched["owner_followers"] = (p.get("owner_followers")
                                       or followers_by_username.get(username))
        vel = score.velocity(
            [dict(s) for s in db.get_snapshots(conn, post_id)],
            cfg["scoring"]["acceleration_threshold"],
        )
        enriched.update(vel)
        posts.append(enriched)

    if posts and all(p.get("owner_followers") is None for p in posts):
        logger.warning("no post reported owner_followers this run — 40%s of the "
                       "scoring weight (views_per_follower + comments_per_follower) "
                       "is inactive", "%")

    # 3. Rank for free ---------------------------------------------------
    ranked = score.score_posts(posts, cfg["scoring"])

    # 4. Tier 1: text ----------------------------------------------------
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    text_candidates = ranked[: mon["candidate_posts_for_text_ai"]]
    for post in text_candidates:
        result = analyze.analyze_text(client, post, cfg["brand"],
                                      cfg["models"]["text_analysis"])
        if not result:
            stats["failures"] += 1
            continue
        post["analysis"] = result
        post["ai_virality_score"] = result.get("ai_virality_score")
        # The strategist schema has no performance_score field — it's ours, not
        # the model's. patterns.py reads it back out of this saved JSON, so it
        # must be merged in here or every pattern's avg_performance is fabricated.
        payload = {**result, "performance_score": post["performance_score"]}
        db.save_analysis(conn, post["post_id"], "text", payload,
                         result.get("ai_virality_score"),
                         cfg["models"]["text_analysis"])
        stats["text_analyzed"] += 1

    for post in ranked:
        post["final_score"] = score.final_score(
            post["performance_score"], post.get("ai_virality_score"),
            cfg["scoring"]["ai_weight"],
        )
    ranked.sort(key=lambda p: p["final_score"], reverse=True)

    # 5. Tier 2: video ---------------------------------------------------
    video_candidates = [p for p in ranked if p.get("video_url")][
        : mon["candidate_posts_for_video_ai"]]
    for post in video_candidates:
        blueprint = analyze.analyze_video(os.environ.get("GEMINI_API_KEY", ""),
                                          post["video_url"], cfg["models"]["video"])
        if not blueprint:
            stats["failures"] += 1
            continue
        post["blueprint"] = blueprint
        db.save_analysis(conn, post["post_id"], "video", blueprint, None,
                         cfg["models"]["video"])
        stats["video_analyzed"] += 1

    # 6. Patterns --------------------------------------------------------
    windows = {
        w: [json.loads(r["json"]) for r in db.get_analyses_since(conn, int(w))
            if r["tier"] == "text"]
        for w in ("7", "30", "90")
    }
    for pat in patterns.detect_patterns(client, windows, cfg["models"]["strategy"],
                                        cfg["brand"]):
        db.save_pattern(conn, pat)
    stored_patterns = [dict(r) for r in db.get_patterns(conn)]

    # 7. Ideas -----------------------------------------------------------
    top_posts = ranked[: mon["daily_top_posts"]]
    our_results = build_our_results(conn, cfg)
    if not ranked and not stored_patterns:
        logger.info("no ranked posts and no patterns — skipping idea generation")
        briefs = []
    else:
        briefs = ideas.generate_ideas(
            client,
            {
                "brand": cfg["brand"],
                "top_posts": [{k: p.get(k) for k in
                               ("username", "caption", "final_score", "analysis")}
                              for p in top_posts],
                "patterns": stored_patterns,
                "previous_ideas": [json.loads(r["brief_json"])["concept"]
                                   for r in db.get_recent_ideas(conn, 20)],
                "our_results": our_results,
            },
            cfg["models"]["strategy"],
            cfg["ideas"]["daily_count"],
        )
    idea_rows = []
    for brief in briefs:
        idea_id = db.save_idea(conn, brief, None, brief.get("similarity_risk"),
                               brief.get("confidence"))
        idea_rows.append({**brief, "id": idea_id})

    # 8. Report ----------------------------------------------------------
    fastest = next((p for p in ranked if p.get("accelerating")),
                   ranked[0] if ranked else None)
    context = {
        "report_date": date.today().isoformat(),
        "brand": cfg["brand"], "stats": stats,
        "fastest_rising": fastest, "top_posts": top_posts,
        "patterns": stored_patterns, "ideas": idea_rows,
        "our_results": our_results, "repo_url": REPO_URL,
    }
    report.render_report(context, report_path)

    email_cfg = dict(cfg.get("email", {}))
    email_cfg.update({
        "host": os.environ.get("SMTP_HOST"), "port": os.environ.get("SMTP_PORT") or 587,
        "user": os.environ.get("SMTP_USER"),
        "password": os.environ.get("SMTP_PASSWORD"),
        "to": os.environ.get("SMTP_TO"),
    })
    report.send_email(Path(report_path).read_text(encoding="utf-8"),
                      f"{cfg['brand']['name']} Intelligence — {context['report_date']}",
                      email_cfg)

    conn.close()
    logger.info("daily run complete: %s", stats)
    return stats


def build_our_results(conn, cfg) -> list:
    """How our own recent posts performed against our own 30-day baseline."""
    import json as _json

    our_posts = db.get_our_posts(conn, days=30)
    if not our_posts:
        return []

    results = []
    for post in our_posts:
        baseline = db.account_baseline(conn, post["account_id"], days=30,
                                       exclude_post_id=post["id"])
        metrics = db.latest_metrics(conn, post["id"])
        views = metrics.get("views")

        source_pattern = None
        idea = conn.execute(
            "SELECT brief_json FROM ideas WHERE posted_shortcode = ?",
            (post["shortcode"],),
        ).fetchone()
        if idea:
            source_pattern = _json.loads(idea["brief_json"]).get("source_pattern")

        results.append({
            "shortcode": post["shortcode"],
            "caption": post["caption"],
            "views": views,
            "baseline_views": baseline,
            # views is not None: measured zero is real data. baseline truthiness: avoid /0.
            "vs_baseline": (views / baseline) if views is not None and baseline else None,
            "source_pattern": source_pattern,
        })
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="igtt daily intelligence run")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--db", default="data/intelligence.db")
    parser.add_argument("--report", default="reports/latest.html")
    args = parser.parse_args()
    if not run_daily(args.config, args.db, args.report)["posts"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
