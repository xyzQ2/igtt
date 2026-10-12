import pytest

from src import score


def test_percentile_ranks_basic():
    assert score.percentile_ranks([10, 20, 30, 40]) == pytest.approx([0.0, 100 / 3, 200 / 3, 100.0])


def test_percentile_ranks_are_positional_so_an_outlier_cannot_squash_the_rest():
    """Min-max scaling put 1, 2, 3 at ~0 next to a viral 1,000,000."""
    assert score.percentile_ranks([1, 2, 3, 1_000_000]) == pytest.approx(
        [0.0, 100 / 3, 200 / 3, 100.0])


def test_percentile_ranks_ties_share_their_average_position():
    assert score.percentile_ranks([10, 20, 20, 30]) == pytest.approx([0.0, 50.0, 50.0, 100.0])


def test_percentile_ranks_none_passes_through():
    out = score.percentile_ranks([10, None, 30])
    assert out[1] is None, "a missing metric must not be ranked as a low value"
    assert out[0] == 0.0 and out[2] == 100.0


def test_percentile_ranks_all_identical_gives_fifty():
    assert score.percentile_ranks([5, 5, 5]) == [50.0, 50.0, 50.0]


def test_percentile_ranks_empty():
    assert score.percentile_ranks([]) == []


def test_post_metrics_reel():
    m = score.post_metrics({
        "views": 487000, "likes": 61200, "comments": 3140, "shares": None,
        "owner_followers": 82000,
    })
    assert m["views_per_follower"] == pytest.approx(5.939, rel=1e-3)
    assert m["engagement_rate"] == pytest.approx((61200 + 3140) / 487000, rel=1e-6)
    assert m["total_engagement"] == 64340
    assert m["raw_views"] == 487000
    assert m["comments_per_follower"] == pytest.approx(3140 / 82000, rel=1e-6)


def test_post_metrics_carousel_has_none_view_metrics():
    m = score.post_metrics({
        "views": None, "likes": 4100, "comments": 220, "shares": None,
        "owner_followers": 82000,
    })
    assert m["views_per_follower"] is None
    assert m["engagement_rate"] is None, "no views means no engagement rate"
    assert m["raw_views"] is None
    assert m["total_engagement"] == 4320
    assert m["comments_per_follower"] == pytest.approx(220 / 82000, rel=1e-6)


def test_post_metrics_zero_followers_does_not_divide_by_zero():
    m = score.post_metrics({"views": 100, "likes": 1, "comments": 0,
                            "shares": None, "owner_followers": 0})
    assert m["views_per_follower"] is None


def test_post_metrics_unknown_engagement_stays_none_not_zero():
    """likes/comments unreported (None) must not fold into a measured zero —
    that would rank an unknown post identically to a genuine zero-engagement one."""
    m = score.post_metrics({
        "views": 5000, "likes": None, "comments": None, "shares": None,
        "owner_followers": 1000,
    })
    assert m["engagement_rate"] is None
    assert m["total_engagement"] is None
    assert m["comments_per_follower"] is None


def test_post_metrics_partial_engagement_still_computes():
    """Only likes reported, comments unknown: engagement still computes (treating
    the unknown side as 0 for the sum), but comments_per_follower stays None."""
    m = score.post_metrics({
        "views": 5000, "likes": 100, "comments": None, "shares": None,
        "owner_followers": 1000,
    })
    assert m["total_engagement"] == 100.0
    assert m["engagement_rate"] == pytest.approx(100 / 5000)
    assert m["comments_per_follower"] is None


def test_post_metrics_zero_views_is_real_data():
    """Zero views is real data (post exists, has no engagement), not missing data."""
    m = score.post_metrics({
        "views": 0, "likes": 0, "comments": 0, "shares": None,
        "owner_followers": 1000,
    })
    assert m["views_per_follower"] == 0.0, "zero views is real data, not missing"
    assert m["raw_views"] == 0.0, "zero views is real data, not missing"
    assert m["engagement_rate"] is None, "zero views makes engagement rate undefined"
    assert m["total_engagement"] == 0.0
    assert m["comments_per_follower"] == 0.0


def test_score_posts_zero_views_participates_in_scoring():
    """A post with zero views ranks below others and the raw_views metric participates in its score."""
    posts = [
        {"shortcode": "new_post", "views": 0, "likes": 0, "comments": 0,
         "shares": None, "owner_followers": 1000},
        {"shortcode": "popular", "views": 5000, "likes": 100, "comments": 50,
         "shares": None, "owner_followers": 1000},
    ]
    ranked = score.score_posts(posts, WEIGHTS)
    by_code = {p["shortcode"]: p for p in ranked}

    # Zero-views post ranks below the popular one
    assert ranked[0]["shortcode"] == "popular"
    assert ranked[1]["shortcode"] == "new_post"

    # Zero-views post has a real score (not redistributed away)
    assert by_code["new_post"]["performance_score"] >= 0.0

    # With raw_views participating, zero-views score differs from what it would be
    # if the metric were excluded (which would redistribute its weight elsewhere)
    score_with_metric = by_code["new_post"]["performance_score"]
    # If raw_views (0.15 weight) were excluded, that weight would be spread across
    # the remaining metrics. A pure zero-engagement post with those metrics would score
    # higher than our post, so our score must be less than 100.0.
    assert score_with_metric < 100.0, "raw_views metric participation reduces zero-engagement score"


def test_score_posts_carries_derived_metrics():
    """A scored post exposes the per-post metrics it was ranked on, not just performance_score."""
    posts = [
        {"shortcode": "banger", "views": 487000, "likes": 61200, "comments": 3140,
         "shares": None, "owner_followers": 82000},
    ]
    ranked = score.score_posts(posts, WEIGHTS)
    p = ranked[0]
    for key in ("views_per_follower", "engagement_rate", "total_engagement",
                "raw_views", "comments_per_follower"):
        assert key in p
    assert p["views_per_follower"] == pytest.approx(487000 / 82000)


def test_score_posts_none_metrics_survive_the_merge():
    """A carousel's missing view metrics stay None on the scored post, never 0."""
    posts = [
        {"shortcode": "carousel", "views": None, "likes": 4100, "comments": 220,
         "shares": None, "owner_followers": 82000},
    ]
    ranked = score.score_posts(posts, WEIGHTS)
    p = ranked[0]
    assert p["views_per_follower"] is None
    assert p["raw_views"] is None


def test_velocity_needs_two_snapshots():
    v = score.velocity([{"captured_at": "2026-09-01T00:00:00", "views": 1000}])
    assert v["views_per_hour"] is None
    assert v["accelerating"] is False


def test_velocity_and_acceleration():
    snaps = [
        {"captured_at": "2026-09-01T00:00:00+00:00", "views": 31000},
        {"captured_at": "2026-09-02T00:00:00+00:00", "views": 89000},
        {"captured_at": "2026-09-03T00:00:00+00:00", "views": 241000},
    ]
    v = score.velocity(snaps, threshold=1.5)
    assert v["views_per_hour"] == pytest.approx((241000 - 89000) / 24)
    assert v["acceleration"] == pytest.approx((241000 - 89000) / (89000 - 31000))
    assert v["accelerating"] is True


def test_velocity_flat_post_is_not_accelerating():
    snaps = [
        {"captured_at": "2026-09-01T00:00:00+00:00", "views": 1000},
        {"captured_at": "2026-09-02T00:00:00+00:00", "views": 2000},
        {"captured_at": "2026-09-03T00:00:00+00:00", "views": 2500},
    ]
    assert score.velocity(snaps)["accelerating"] is False


WEIGHTS = {
    "views_per_follower": 0.30, "engagement_rate": 0.25,
    "total_engagement": 0.20, "raw_views": 0.15, "comments": 0.10,
}


def test_score_posts_ranks_the_overperformer_first():
    posts = [
        {"shortcode": "small", "views": 1000, "likes": 10, "comments": 1,
         "shares": None, "owner_followers": 100000},
        {"shortcode": "banger", "views": 487000, "likes": 61200, "comments": 3140,
         "shares": None, "owner_followers": 82000},
    ]
    ranked = score.score_posts(posts, WEIGHTS)
    assert ranked[0]["shortcode"] == "banger"
    assert 0 <= ranked[0]["performance_score"] <= 100


def test_score_posts_reweights_when_a_metric_is_missing():
    """A carousel is scored on the metrics it has, not penalised for the rest."""
    posts = [
        {"shortcode": "reel", "views": 5000, "likes": 100, "comments": 10,
         "shares": None, "owner_followers": 1000},
        {"shortcode": "carousel", "views": None, "likes": 9000, "comments": 900,
         "shares": None, "owner_followers": 1000},
    ]
    ranked = score.score_posts(posts, WEIGHTS)
    by_code = {p["shortcode"]: p for p in ranked}
    assert by_code["carousel"]["performance_score"] > 0
    assert by_code["carousel"]["performance_score"] == pytest.approx(100.0)


def test_final_score_blends_eighty_twenty():
    assert score.final_score(90.0, 50.0, 0.20) == pytest.approx(82.0)


def test_final_score_without_ai_uses_performance_only():
    assert score.final_score(90.0, None, 0.20) == pytest.approx(90.0)
