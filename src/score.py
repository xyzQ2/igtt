"""Numeric ranking. Pure functions — no I/O, no network, no database.

This stage runs over every collected post at zero API cost and is what keeps
the AI spend bounded.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

METRIC_KEYS = (
    "views_per_follower",
    "engagement_rate",
    "total_engagement",
    "raw_views",
    "comments_per_follower",
    "engagement_per_follower",
)

# config.yaml names the last weight "comments"; the metric is per-follower.
WEIGHT_KEY_FOR = {
    "views_per_follower": "views_per_follower",
    "engagement_rate": "engagement_rate",
    "total_engagement": "total_engagement",
    "raw_views": "raw_views",
    "comments_per_follower": "comments",
    "engagement_per_follower": "engagement_per_follower",
}


def percentile_ranks(values: list) -> list:
    """Rank values 0-100 by position. None in, None out.

    None means the platform does not report that metric for that post type.
    Ranking it as a low value would penalise carousels for not being videos.
    """
    present = [v for v in values if v is not None]
    if not present:
        return [None] * len(values)
    lo, hi = min(present), max(present)
    if hi == lo:
        return [None if v is None else 50.0 for v in values]
    span = hi - lo
    return [None if v is None else (v - lo) / span * 100.0 for v in values]


def count(v):
    """A platform count, or None. Apify reports -1 when an owner hides likes —
    that is "unknown", never a real number to add up."""
    return None if v is None or v < 0 else v


# Hazard: aggregation. `likes or 0` folds an unmeasured metric into a genuine
# zero — an unknown count must stay None, never become a measured 0. This is
# where that rule keeps getting broken; do not "simplify" it back to `or 0`.
def post_metrics(post: dict) -> dict:
    """Derive the six ranking metrics for one post. Missing stays None."""
    views = count(post.get("views"))
    likes = count(post.get("likes"))
    comments = count(post.get("comments"))
    shares = count(post.get("shares")) or 0
    followers = post.get("owner_followers") or 0

    engagement = (None if (likes is None and comments is None)
                  else (likes or 0) + (comments or 0) + shares)

    return {
        "views_per_follower": (views / followers) if views is not None and followers else None,
        "engagement_rate": (None if engagement is None
                            else (engagement / views) if views else None),  # views == 0 makes this ratio undefined, not missing — None is deliberate
        "total_engagement": None if engagement is None else float(engagement),
        "raw_views": float(views) if views is not None else None,
        "comments_per_follower": (None if comments is None
                                  else (comments / followers) if followers else None),
        # The only reach-normalised metric when views are unknown (Meta source).
        "engagement_per_follower": (None if engagement is None
                                    else (engagement / followers) if followers else None),
    }


def velocity(snapshots: list, threshold: float = 1.5) -> dict:
    """Views per hour in the latest window, and whether the post is speeding up.

    Needs two snapshots for a rate and three for an acceleration. Fewer than
    that returns Nones rather than guessing.
    """
    usable = [s for s in snapshots if s.get("views") is not None]
    if len(usable) < 2:
        return {"views_per_hour": None, "acceleration": None, "accelerating": False}

    def window(a, b):
        t0 = datetime.fromisoformat(a["captured_at"])
        t1 = datetime.fromisoformat(b["captured_at"])
        hours = (t1 - t0).total_seconds() / 3600
        if hours <= 0:
            return None
        return (b["views"] - a["views"]) / hours

    latest = window(usable[-2], usable[-1])
    if len(usable) < 3:
        return {"views_per_hour": latest, "acceleration": None, "accelerating": False}

    previous = window(usable[-3], usable[-2])
    if not previous or previous <= 0 or latest is None:
        return {"views_per_hour": latest, "acceleration": None, "accelerating": False}

    accel = latest / previous
    return {
        "views_per_hour": latest,
        "acceleration": accel,
        "accelerating": accel >= threshold,
    }


def score_posts(posts: list, weights: dict) -> list:
    """Add performance_score (0-100) to each post, sorted best first.

    Weights of metrics that are None for a given post are redistributed across
    the metrics it does have, so post types compete fairly.
    """
    if not posts:
        return []

    metrics = [post_metrics(p) for p in posts]
    ranked = {
        key: percentile_ranks([m[key] for m in metrics]) for key in METRIC_KEYS
    }

    scored = []
    for i, post in enumerate(posts):
        total, weight_used = 0.0, 0.0
        for key in METRIC_KEYS:
            pct = ranked[key][i]
            if pct is None:
                continue
            w = weights.get(WEIGHT_KEY_FOR[key], 0.0)
            total += w * pct
            weight_used += w
        out = dict(post)
        out.update(metrics[i])
        out["performance_score"] = (total / weight_used) if weight_used else 0.0
        scored.append(out)

    scored.sort(key=lambda p: p["performance_score"], reverse=True)
    return scored


def final_score(performance_score: float, ai_virality_score, ai_weight: float) -> float:
    """0.80 * performance + 0.20 * ai virality. No AI score means performance alone."""
    if ai_virality_score is None:
        return performance_score
    return (1 - ai_weight) * performance_score + ai_weight * ai_virality_score
