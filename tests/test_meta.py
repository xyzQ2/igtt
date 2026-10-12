import pytest

from src import meta


def media(i, likes=10, comments=2, ts="2099-01-01T00:00:00+0000", **kw):
    return {"id": f"m{i}", "permalink": f"https://www.instagram.com/p/CODE{i}/",
            "media_type": "IMAGE", "media_url": "https://scontent.cdninstagram.com/x.jpg",
            "timestamp": ts, "like_count": likes, "comments_count": comments,
            "caption": "c", **kw}


class Resp:
    def __init__(self, data, ok=True):
        self.data, self.ok, self.status_code, self.text = data, ok, 200 if ok else 400, "err"

    def json(self):
        return self.data


def test_normalize_keeps_unreported_metrics_none():
    m = media(1)
    del m["like_count"]  # owner hid likes
    p = meta.normalize_media(m, "acct", 500)
    assert p["shortcode"] == "CODE1"
    assert p["likes"] is None, "hidden likes are unknown, not zero"
    assert p["views"] is None
    assert p["comments"] == 2
    assert p["thumbnail_url"].startswith("https://")


def test_normalize_rejects_non_https_permalink():
    p = meta.normalize_media(media(1, permalink="javascript:alert(1)"), "a", 1)
    assert p["url"] is None


def test_business_discovery_skips_failing_accounts_and_old_posts(mocker):
    def fake_get(url, params, timeout):
        if "username(bad)" in params["fields"]:
            return Resp({}, ok=False)
        return Resp({"business_discovery": {"followers_count": 900, "media": {"data": [
            media(1), media(2, ts="2001-01-01T00:00:00+0000")]}}})
    mocker.patch("src.meta.requests.get", side_effect=fake_get)

    posts = meta.fetch_profile_posts("t", "1", ["good", "bad"], 30, 8)

    assert [p["shortcode"] for p in posts] == ["CODE1"]
    assert posts[0]["owner_followers"] == 900
    assert posts[0]["username"] == "good"


def test_own_posts_read_views_and_shares_from_insights(mocker):
    def fake_get(url, params, timeout):
        if url.endswith("/1"):
            return Resp({"followers_count": 1200})
        if url.endswith("/1/media"):
            return Resp({"data": [media(1), media(2)]})
        if url.endswith("m1/insights"):
            return Resp({"data": [{"name": "views", "values": [{"value": 0}]},
                                  {"name": "shares", "total_value": {"value": 4}}]})
        return Resp({}, ok=False)  # m2 insights unavailable
    mocker.patch("src.meta.requests.get", side_effect=fake_get)

    posts = {p["shortcode"]: p for p in meta.fetch_own_posts("t", "1", "me", 30, 8)}

    assert posts["CODE1"]["views"] == 0, "a measured zero stays zero"
    assert posts["CODE1"]["shares"] == 4
    assert posts["CODE2"]["views"] is None
    assert posts["CODE1"]["username"] == "me"


def test_connect_picks_the_page_linked_to_our_handle(mocker):
    pages = {"data": [
        {"access_token": "pageA", "instagram_business_account": {"id": "A", "username": "other"}},
        {"access_token": "pageB", "instagram_business_account": {"id": "B", "username": "me"}},
        {"access_token": "pageC"}]}
    mocker.patch("src.meta.requests.get", side_effect=[
        Resp({"access_token": "long"}), Resp(pages)])
    assert meta.connect("app", "secret", "short", "me") == {
        "token": "pageB", "ig_user_id": "B", "username": "me"}


def test_connect_explains_a_missing_instagram_link(mocker):
    mocker.patch("src.meta.requests.get", side_effect=[
        Resp({"access_token": "long"}), Resp({"data": [{"access_token": "p"}]})])
    with pytest.raises(ValueError, match="linked Instagram"):
        meta.connect("app", "secret", "short")
