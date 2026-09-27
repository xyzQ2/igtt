import pytest


@pytest.fixture(autouse=True)
def isolate_credentials(monkeypatch):
    """Keep real credentials out of every test.

    load_config() calls load_dotenv(), which re-reads the developer's .env — so a
    test that deletes a credential to check a guard would have it handed straight
    back, and post.py would go on to make a live API call. Neutralise the load and
    clear the names; tests that need a credential set it themselves.
    """
    monkeypatch.setattr("src.config.load_dotenv", lambda *a, **k: None)
    for name in ("IG_ACCESS_TOKEN", "IG_USER_ID", "APIFY_TOKEN",
                 "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def block_apify_network(monkeypatch):
    """A test that forgets to mock an Apify call fails closed instead of going
    to the network. Tests that exercise the adapter patch requests.post over this."""
    def _refuse(*a, **k):
        raise RuntimeError("tests must not call Apify")
    monkeypatch.setattr("src.apify.requests.post", _refuse)


@pytest.fixture(autouse=True)
def block_media_downloads(monkeypatch):
    """Same for thumbnail and video downloads. Tests that need one patch
    requests.get over this."""
    def _refuse(*a, **k):
        raise RuntimeError("tests must not download media")
    monkeypatch.setattr("src.analyze.requests.get", _refuse)
