"""Meta Graph API data source: free, uses the brand's own Meta developer app.

Other accounts come from Business Discovery, which only sees Business and Creator
accounts and reports likes and comments but never views. Our own account comes
from its media list plus per-post insights, which do include views and shares.
Both live on graph.facebook.com and need a token from Facebook Login (a Page
token), not the Instagram-Login token on graph.instagram.com.

Returns posts in the same shape as apify.normalize_post. A metric Meta does not
report stays None; it never becomes 0.
"""

import logging
import re
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v23.0"
TIMEOUT = 60
MEDIA_FIELDS = ("id,caption,media_type,media_product_type,media_url,thumbnail_url,"
                "permalink,timestamp,like_count,comments_count")
_SHORTCODE = re.compile(r"instagram\.com/(?:p|reel|tv)/([^/?#]+)")


def _get(path: str, token: str, **params) -> dict:
    resp = requests.get(f"{GRAPH}/{path}", params={**params, "access_token": token},
                        timeout=TIMEOUT)
    if not resp.ok:
        # Graph errors are opaque without the body.
        raise RuntimeError(f"{resp.status_code} {resp.text[:300]}")
    return resp.json()


def _https_or_none(url):
    return url if isinstance(url, str) and url.lower().startswith("https://") else None


def normalize_media(m: dict, username: str, followers) -> dict | None:
    permalink = _https_or_none(m.get("permalink"))
    match = _SHORTCODE.search(permalink or "")
    shortcode = match.group(1) if match else m.get("id")
    if not shortcode:
        return None
    is_video = m.get("media_type") == "VIDEO"
    media_url = _https_or_none(m.get("media_url"))
    return {
        "platform": "instagram",
        "shortcode": shortcode,
        "username": username,
        "owner_followers": followers,
        "url": permalink,
        "video_url": media_url if is_video else None,
        "thumbnail_url": _https_or_none(m.get("thumbnail_url")) or (
            None if is_video else media_url),
        "caption": m.get("caption"),
        "content_type": m.get("media_product_type") or m.get("media_type"),
        "posted_at": m.get("timestamp"),
        "duration_sec": None,
        "views": None,  # Business Discovery never reports views
        "likes": m.get("like_count"),  # absent when the owner hides likes
        "comments": m.get("comments_count"),
        "shares": None,
    }


def _recent(posts: list, lookback_days: int) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    return [p for p in posts if not p["posted_at"]
            or datetime.fromisoformat(p["posted_at"]) >= cutoff]


def fetch_profile_posts(token: str, ig_user_id: str, usernames: list,
                        lookback_days: int, results_limit: int) -> tuple:
    """(recent posts, usernames Meta could not read) via Business Discovery.
    An account that answered with no recent posts is not a failure."""
    posts, failed = [], []
    for username in usernames:
        field = (f"business_discovery.username({username})"
                 f"{{followers_count,media.limit({results_limit}){{{MEDIA_FIELDS}}}}}")
        try:
            bd = _get(ig_user_id, token, fields=field)["business_discovery"]
        except Exception as exc:
            # Personal (non-Business/Creator) and private accounts land here.
            logger.warning("meta: no posts for %s: %s", username, exc)
            failed.append(username)
            continue
        followers = bd.get("followers_count")
        for m in bd.get("media", {}).get("data", []):
            p = normalize_media(m, username, followers)
            if p:
                posts.append(p)
    posts = _recent(posts, lookback_days)
    logger.info("meta returned %d usable posts from %d accounts (%d unreadable)",
                len(posts), len(usernames), len(failed))
    return posts, failed


def _insight(data: list, name: str):
    for row in data:
        if row.get("name") == name:
            if "total_value" in row:
                return row["total_value"].get("value")
            values = row.get("values") or [{}]
            return values[0].get("value")
    return None


def fetch_own_posts(token: str, ig_user_id: str, handle: str, lookback_days: int,
                    results_limit: int) -> list:
    """Our own recent posts, with views and shares from insights. None on failure,
    so the caller can tell "unreadable" from "posted nothing lately"."""
    try:
        me = _get(ig_user_id, token, fields="followers_count")
        media = _get(f"{ig_user_id}/media", token, fields=MEDIA_FIELDS,
                     limit=results_limit).get("data", [])
    except Exception as exc:
        logger.error("meta: own account fetch failed: %s", exc)
        return None
    posts = []
    for m in media:
        p = normalize_media(m, handle, me.get("followers_count"))
        if not p:
            continue
        try:
            data = _get(f"{m['id']}/insights", token, metric="views,shares")["data"]
            p["views"], p["shares"] = _insight(data, "views"), _insight(data, "shares")
        except Exception as exc:
            logger.warning("meta: no insights for %s: %s", p["shortcode"], exc)
        posts.append(p)
    return _recent(posts, lookback_days)


def connect(app_id: str, app_secret: str, short_token: str, handle: str = "") -> dict:
    """Turn a Graph API Explorer token into a Page token that does not expire.

    Short user token -> 60-day user token -> Page token (no expiry when derived
    from a long-lived user token). Returns {token, ig_user_id, username}.
    Raises ValueError with a message a non-developer can act on.
    """
    try:
        long_user = _get("oauth/access_token", short_token,
                         grant_type="fb_exchange_token", client_id=app_id,
                         client_secret=app_secret,
                         fb_exchange_token=short_token)["access_token"]
        pages = _get("me/accounts", long_user,
                     fields="name,access_token,instagram_business_account{id,username}")
    except Exception as exc:
        raise ValueError(f"Meta rejected the App ID, App Secret or token: {exc}")
    linked = [p for p in pages.get("data", []) if p.get("instagram_business_account")]
    if not linked:
        raise ValueError("No Facebook Page with a linked Instagram Business or Creator "
                         "account was found for this token.")
    pick = next((p for p in linked
                 if p["instagram_business_account"].get("username") == handle), linked[0])
    ig = pick["instagram_business_account"]
    return {"token": pick["access_token"], "ig_user_id": ig["id"],
            "username": ig.get("username")}
