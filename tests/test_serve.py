import pytest
import yaml
from dotenv import dotenv_values

import serve
from src import db


@pytest.fixture()
def home(tmp_path, monkeypatch):
    cfg = yaml.safe_load(open("config.yaml"))
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg))
    monkeypatch.setattr(serve, "CONFIG", tmp_path / "config.yaml")
    monkeypatch.setattr(serve, "ENV", tmp_path / ".env")
    monkeypatch.setattr(serve, "DB", str(tmp_path / "t.db"))
    return tmp_path


def form(**kw):
    base = {"brand.name": "Toilet Wine", "brand.instagram": "@DrinkToiletWine",
            "provider": "openai", "api_key": "sk-1", "source": "meta",
            "monitoring.posts_lookback_days": "500", "monitoring.results_per_account": "8",
            "monitoring.candidate_posts_for_text_ai": "40", "monitoring.daily_top_posts": "25",
            "ideas.daily_count": "10", "accounts": "a\n@B\n", "email": "x@gmail.com",
            "email_password": "abcd efgh ijkl mnop", "email_enabled": "on"}
    base.update(kw)
    return {k: [v] for k, v in base.items()}


def test_save_settings_writes_config_secrets_and_watchlist(home):
    msg = serve.save_settings(form())
    assert msg.startswith("Settings saved")

    cfg = yaml.safe_load((home / "config.yaml").read_text())
    assert cfg["brand"]["instagram"] == "drinktoiletwine"
    assert cfg["monitoring"]["posts_lookback_days"] == 90, "clamped to the max"
    assert cfg["monitoring"]["source"] == "meta"
    assert cfg["models"]["provider"] == "openai"
    assert cfg["models"]["text_analysis"] is None, "old provider's model must not stick"
    assert cfg["email"]["enabled"] is True

    env = dotenv_values(home / ".env")
    assert env["OPENAI_API_KEY"] == "sk-1"
    assert env["SMTP_PASSWORD"] == "abcdefghijklmnop"
    assert env["SMTP_HOST"] == "smtp.gmail.com"

    conn = db.connect(serve.DB)
    active = {r["username"] for r in db.get_active_accounts(conn)}
    assert active == {"a", "b", "drinktoiletwine"}


def test_blank_secret_keeps_the_saved_one(home):
    serve.save_settings(form())
    serve.save_settings(form(api_key="", email_password=""))
    env = dotenv_values(home / ".env")
    assert env["OPENAI_API_KEY"] == "sk-1"
    assert env["SMTP_PASSWORD"] == "abcdefghijklmnop"


def test_bad_number_is_refused_without_saving(home):
    before = (home / "config.yaml").read_text()
    assert "must be a number" in serve.save_settings(form(**{"ideas.daily_count": "ten"}))
    assert (home / "config.yaml").read_text() == before


def test_failed_meta_connect_is_reported_not_raised(home, mocker):
    mocker.patch("serve.meta.connect", side_effect=ValueError("bad secret"))
    msg = serve.save_settings(form(app_id="1", app_secret="s", explorer_token="t"))
    assert "NOT connected: bad secret" in msg
    assert "IG_ACCESS_TOKEN" not in dotenv_values(home / ".env")


def test_secrets_never_render_into_the_settings_page(home):
    serve.save_settings(form())
    page = serve.settings_page()
    assert "sk-1" not in page and "abcdefghijklmnop" not in page
    assert "✓ saved" in page


@pytest.mark.parametrize("host,origin,ok", [
    ("127.0.0.1:8765", None, True),
    ("localhost:8765", "http://localhost:8765", True),
    ("evil.com", None, False),                        # DNS rebinding
    ("127.0.0.1:8765", "https://evil.com", False),    # cross-site form post
])
def test_only_this_server_may_call_it(host, origin, ok):
    h = object.__new__(serve.Handler)
    h.headers = {"Host": host, **({"Origin": origin} if origin else {})}
    assert h._trusted() is ok
