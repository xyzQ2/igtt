"""Apify adapter. The only module in the project that knows scraping exists."""

import logging

import requests

logger = logging.getLogger(__name__)

ACTOR_URL = ("https://api.apify.com/v2/acts/apify~instagram-scraper/"
             "run-sync-get-dataset-items")
TIMEOUT = 600


def _https_or_none(url):
    """Only an https URL is safe to land in an <a href> in the report. Anything
    else (javascript:, missing scheme, ...) becomes None."""
    return url if isinstance(url, str) and url.lower().startswith("https://") else None


def normalize_post(raw: dict) -> dict | None:
    """Map one Apify dataset item to the project's post shape.

    Returns None for items with no shortCode. A metric the platform does not
    report stays None; it never becomes 0.
    """
    shortcode = raw.get("shortCode")
    if not shortcode:
        logger.debug("dropping item with no shortCode")
        return None

    play_count = raw.get("videoPlayCount")
    view_count = raw.get("videoViewCount")
    views = play_count if play_count is not None else view_count

    return {
        "platform": "instagram",
        "shortcode": shortcode,
        "username": raw.get("ownerUsername"),
        "owner_followers": raw.get("ownerFollowersCount"),
        "url": _https_or_none(raw.get("url")),
        "video_url": _https_or_none(raw.get("videoUrl")),
        "thumbnail_url": raw.get("displayUrl"),
        "caption": raw.get("caption"),
        "content_type": raw.get("type"),
        "posted_at": raw.get("timestamp"),
        "duration_sec": raw.get("videoDuration"),
        "views": views,
        "likes": raw.get("likesCount"),
        "comments": raw.get("commentsCount"),
        "shares": None,  # Instagram does not expose share counts publicly
    }


def fetch_profile_posts(token: str, usernames: list[str], lookback_days: int,
                        results_limit: int) -> list[dict]:
    """Fetch recent posts for the given usernames. Returns [] on any failure."""
    if not usernames:
        return []

    body = {
        "directUrls": [f"https://www.instagram.com/{u}/" for u in usernames],
        "resultsType": "posts",
        "resultsLimit": results_limit,
        "onlyPostsNewerThan": f"{lookback_days} days",
        "addParentData": False,
    }
    try:
        resp = requests.post(
            ACTOR_URL,
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json()
        posts = [p for p in (normalize_post(i) for i in items) if p]
        logger.info("apify returned %d items, %d usable posts", len(items), len(posts))
        return posts
    except Exception as exc:
        logger.error("apify fetch failed for %d accounts: %s", len(usernames), exc)
        return []


HASHTAG_ACTOR_URL = ("https://api.apify.com/v2/acts/apify~instagram-hashtag-scraper/"
                     "run-sync-get-dataset-items")


def search_hashtag_accounts(token: str, hashtags: list, limit: int) -> list:
    """Find distinct accounts posting under the given hashtags. [] on failure."""
    if not hashtags:
        return []

    # The general scraper's `search` field takes ONE query, so joining the tags
    # searched for a hashtag that doesn't exist and returned nothing. The hashtag
    # actor takes the list, and resultsLimit is per tag.
    body = {
        "hashtags": hashtags,
        "resultsType": "posts",
        "resultsLimit": max(1, limit // len(hashtags)),
    }
    try:
        resp = requests.post(HASHTAG_ACTOR_URL,
                             headers={"Authorization": f"Bearer {token}"},
                             json=body, timeout=TIMEOUT)
        resp.raise_for_status()
        items = resp.json()
        if not isinstance(items, list):
            raise ValueError(f"expected a list of posts, got {type(items).__name__}")
    except Exception as exc:
        logger.error("apify hashtag search failed: %s", exc)
        return []

    by_username: dict = {}
    for item in items:
        username = item.get("ownerUsername")
        if not username:
            continue
        entry = by_username.setdefault(username, {
            "username": username,
            "followers": item.get("ownerFollowersCount"),
            "sample_captions": [],
        })
        caption = item.get("caption")
        if caption and len(entry["sample_captions"]) < 5:
            entry["sample_captions"].append(caption)

    logger.info("hashtag search found %d distinct accounts", len(by_username))
    return list(by_username.values())
