import json
from pathlib import Path

from src import apify

FIXTURE = Path(__file__).parent / "fixtures" / "apify_instagram.json"


def raw_items():
    return json.loads(FIXTURE.read_text())


def test_normalize_reel_maps_every_field():
    post = apify.normalize_post(raw_items()[0])
    assert post["shortcode"] == "DAbc123"
    assert post["username"] == "wineexample"
    assert post["owner_followers"] == 82000
    assert post["content_type"] == "Video"
    assert post["video_url"] == "https://scontent.cdninstagram.com/v/reel1.mp4"
    assert post["views"] == 487000
    assert post["likes"] == 61200
    assert post["comments"] == 3140
    assert post["duration_sec"] == 14.3
    assert post["posted_at"].startswith("2026-09-05T14:02:11")


def test_carousel_views_stay_none_not_zero():
    post = apify.normalize_post(raw_items()[1])
    assert post["views"] is None, "a carousel has no view count; None is not zero"
    assert post["shares"] is None
    assert post["video_url"] is None
    assert post["likes"] == 4100


def test_item_without_shortcode_is_dropped():
    assert apify.normalize_post(raw_items()[2]) is None


def test_fetch_profile_posts_builds_expected_request(mocker):
    mock_post = mocker.patch("src.apify.requests.post")
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = raw_items()

    posts = apify.fetch_profile_posts("tok", ["wineexample"], lookback_days=7,
                                      results_limit=20)

    assert len(posts) == 2, "the junk item must be dropped"
    url, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
    assert "apify~instagram-scraper" in url
    assert "token" not in url, "token belongs in the header, not the query string"
    assert kwargs["headers"]["Authorization"] == "Bearer tok"
    body = kwargs["json"]
    assert body["directUrls"] == ["https://www.instagram.com/wineexample/"]
    assert body["onlyPostsNewerThan"] == "7 days"
    assert body["resultsLimit"] == 20
    assert body["resultsType"] == "posts"


def test_fetch_profile_posts_returns_empty_on_http_error(mocker):
    mock_post = mocker.patch("src.apify.requests.post")
    mock_post.side_effect = Exception("connection reset")
    assert apify.fetch_profile_posts("tok", ["a"], 7, 20) == []


def test_videoplaycount_zero_not_treated_as_absent():
    """Regression: views=0 on brand-new reels must not fall through to viewCount."""
    raw = {
        "shortCode": "NEW001",
        "videoPlayCount": 0,
        "type": "Video",
    }
    post = apify.normalize_post(raw)
    assert post["views"] == 0, "zero views must stay zero, not become None"


def test_videoviewcount_fallback_when_playcount_absent():
    """Test fallback precedence: if playCount is absent, use viewCount."""
    raw = {
        "shortCode": "OLD001",
        "videoViewCount": 12345,
        "type": "Video",
    }
    post = apify.normalize_post(raw)
    assert post["views"] == 12345


def test_normalize_post_rejects_non_https_url_and_video_url():
    """A javascript: URL must never land in an <a href> in the report."""
    raw = {
        "shortCode": "BAD1", "type": "Video",
        "url": "javascript:alert(1)", "videoUrl": "javascript:alert(2)",
    }
    post = apify.normalize_post(raw)
    assert post["url"] is None
    assert post["video_url"] is None


def test_fetch_profile_posts_returns_empty_on_malformed_response(mocker):
    """Regression: malformed response body (e.g. error dict) must not raise."""
    mock_post = mocker.patch("src.apify.requests.post")
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"error": "rate limited"}
    assert apify.fetch_profile_posts("tok", ["a"], 7, 20) == []


def test_fetch_follower_counts_asks_for_profile_details(mocker):
    m = mocker.patch("src.apify.requests.post")
    m.return_value.json.return_value = [
        {"username": "a", "followersCount": 1200},
        {"username": "b", "followersCount": 0},       # a measured zero is real
        {"username": "c", "followersCount": None},    # unmeasured stays out
        "junk",
    ]
    assert apify.fetch_follower_counts("tok", ["a", "b", "c"]) == {"a": 1200, "b": 0}
    body = m.call_args.kwargs["json"]
    assert body["resultsType"] == "details"
    assert body["directUrls"] == ["https://www.instagram.com/a/",
                                  "https://www.instagram.com/b/",
                                  "https://www.instagram.com/c/"]


def test_fetch_follower_counts_empty_on_error_payload(mocker):
    m = mocker.patch("src.apify.requests.post")
    m.return_value.json.return_value = {"error": {"type": "user-or-token-not-found"}}
    assert apify.fetch_follower_counts("tok", ["a"]) == {}
