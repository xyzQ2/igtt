"""Local dashboard + settings page. Start.command runs this and opens the browser.

Listens on 127.0.0.1 only. Rejects any request whose Host or Origin is not this
server, so a web page open in another tab cannot read the dashboard or change
settings (DNS rebinding / CSRF). Secrets are written to .env and never rendered
back into the page.
"""

import html
import os
import subprocess
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import yaml
from dotenv import dotenv_values, set_key

ROOT = Path(__file__).parent
os.chdir(ROOT)

from src import dashboard, db, llm, meta  # noqa: E402
from src.config import load_config  # noqa: E402

PORT = 8765
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
CONFIG, ENV, DB = ROOT / "config.yaml", ROOT / ".env", "data/intelligence.db"
LOG = ROOT / "logs" / "run.log"

# (section, key, label, min, max) — the knobs the settings page exposes.
NUMBERS = [
    ("monitoring", "posts_lookback_days", "Look at posts from the last … days", 1, 90),
    ("monitoring", "results_per_account", "Posts to check per account", 1, 50),
    ("monitoring", "candidate_posts_for_text_ai", "Posts the AI studies each day", 0, 100),
    ("monitoring", "daily_top_posts", "Top posts in the daily report", 5, 100),
    ("ideas", "daily_count", "New ideas per day", 1, 20),
]
TEXTS = [("brand", "name", "Brand name"), ("brand", "instagram", "Your Instagram handle"),
         ("brand", "industry", "What you sell"), ("brand", "target_market", "Who it's for"),
         ("brand", "voice", "Brand voice")]
_run = None  # the "Run now" subprocess


def read_cfg() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def page(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title>
<style>
 :root {{ --bg:#fcfcfb; --card:#fff; --ink:#0b0b0b; --muted:#52514e; --line:#e4e3df; --acc:#2a78d6; }}
 @media (prefers-color-scheme: dark) {{ :root {{ --bg:#1a1a19; --card:#232322; --ink:#f0efec;
   --muted:#c3c2b7; --line:#3a3936; --acc:#3987e5; }} }}
 body {{ font:15px/1.5 -apple-system,BlinkMacSystemFont,sans-serif; background:var(--bg);
        color:var(--ink); margin:0; padding:16px; }}
 main {{ max-width:720px; margin:0 auto; }}
 fieldset {{ border:1px solid var(--line); border-radius:8px; background:var(--card);
            margin:16px 0; padding:12px 16px; }}
 legend {{ font-weight:600; }} label {{ display:block; margin:10px 0 2px; font-size:14px; }}
 input, select, textarea {{ font:inherit; width:100%; padding:6px 8px; border:1px solid var(--line);
   border-radius:6px; background:var(--bg); color:var(--ink); box-sizing:border-box; }}
 input[type=checkbox] {{ width:auto; }}
 .hint {{ color:var(--muted); font-size:13px; }} a {{ color:var(--acc); }}
 button {{ font:inherit; padding:8px 18px; border-radius:6px; border:0; background:var(--acc);
          color:#fff; cursor:pointer; }}
 .msg {{ padding:10px 14px; border:1px solid var(--acc); border-radius:6px; }}
</style></head><body><main>{body}</main></body></html>"""


def settings_page(message: str = "") -> str:
    cfg, env = read_cfg(), dotenv_values(ENV) if ENV.exists() else {}
    e = html.escape
    conn = db.connect(DB)
    db.init_schema(conn)
    own = cfg["brand"]["instagram"]
    watch = "\n".join(r["username"] for r in db.get_active_accounts(conn) if r["username"] != own)
    conn.close()

    def saved(key):
        return "✓ saved — leave blank to keep" if env.get(key) else "not set yet"

    provider = cfg["models"].get("provider") or "anthropic"
    source = cfg["monitoring"].get("source", "meta")
    out = ['<p><a href="/">← Back to dashboard</a></p><h1>Settings</h1>']
    if message:
        out.append(f'<p class="msg">{e(message)}</p>')
    out.append('<form method="post" action="/settings">')

    out.append("<fieldset><legend>1. Your brand</legend>")
    for sec, key, label in TEXTS:
        out.append(f'<label>{label}</label><input name="{sec}.{key}" value="{e(str(cfg[sec].get(key) or "").strip())}">')
    out.append("</fieldset>")

    out.append("<fieldset><legend>2. AI provider</legend><label>Which AI company</label>"
               '<select name="provider">')
    for p, name in (("anthropic", "Anthropic (Claude)"), ("openai", "OpenAI (ChatGPT)"),
                    ("google", "Google (Gemini)")):
        out.append(f'<option value="{p}" {"selected" if p == provider else ""}>{name}</option>')
    out.append(f'</select><label>API key for that company</label>'
               f'<input type="password" name="api_key" autocomplete="off">'
               f'<div class="hint">{saved(llm.KEY_ENV[provider])}</div></fieldset>')

    out.append(f"""<fieldset><legend>3. Instagram connection (Meta)</legend>
<div class="hint">Status: {"✓ token saved (account id " + e(env.get("IG_USER_ID") or "") + ")" if env.get("IG_ACCESS_TOKEN") else "not connected"}.
Fill all three only to connect or reconnect — see the START HERE guide.</div>
<label>Meta App ID</label><input name="app_id" autocomplete="off">
<label>Meta App Secret</label><input type="password" name="app_secret" autocomplete="off">
<label>Access token from Graph API Explorer</label><input type="password" name="explorer_token" autocomplete="off">
<label>Where posts come from</label><select name="source">
<option value="meta" {"selected" if source == "meta" else ""}>Meta first (free), Apify for accounts Meta can't read</option>
<option value="apify" {"selected" if source == "apify" else ""}>Apify only (paid — adds view counts)</option></select>
<label>Apify token (optional with Meta; reads personal accounts Meta can't)</label><input type="password" name="apify" autocomplete="off">
<div class="hint">{saved("APIFY_TOKEN")}</div></fieldset>""")

    out.append(f"""<fieldset><legend>4. Daily email</legend>
<label><input type="checkbox" name="email_enabled" {"checked" if cfg.get("email", {}).get("enabled") else ""}> Email me the daily report</label>
<label>Your Gmail address</label><input name="email" value="{e(env.get("SMTP_TO") or "")}">
<label>Gmail app password (16 letters)</label><input type="password" name="email_password" autocomplete="off">
<div class="hint">{saved("SMTP_PASSWORD")}</div></fieldset>""")

    out.append(f"""<fieldset><legend>5. Accounts to watch</legend>
<div class="hint">One Instagram handle per line. With Meta, only Business or Creator accounts work.</div>
<textarea name="accounts" rows="10">{e(watch)}</textarea></fieldset>""")

    out.append("<fieldset><legend>6. Results</legend>")
    for sec, key, label, lo, hi in NUMBERS:
        out.append(f'<label>{label} ({lo}–{hi})</label><input type="number" min="{lo}" max="{hi}" '
                   f'name="{sec}.{key}" value="{cfg[sec][key]}">')
    out.append("</fieldset><button>Save settings</button></form>")
    return page("Settings", "".join(out))


def save_settings(form: dict) -> str:
    cfg = read_cfg()
    f = {k: v[0].strip() for k, v in form.items()}
    for sec, key, _ in TEXTS:
        if f.get(f"{sec}.{key}"):
            cfg[sec][key] = f[f"{sec}.{key}"]
    cfg["brand"]["instagram"] = cfg["brand"]["instagram"].lstrip("@").lower()
    for sec, key, label, lo, hi in NUMBERS:
        try:
            cfg[sec][key] = min(hi, max(lo, int(f.get(f"{sec}.{key}", ""))))
        except ValueError:
            return f"'{label}' must be a number."
    provider = f.get("provider", "anthropic")
    if provider not in llm.PROVIDERS:
        return "Unknown AI provider."
    if provider != cfg["models"].get("provider"):
        # Blank models fall back to the new provider's defaults (src/llm.py).
        cfg["models"].update(provider=provider, text_analysis=None, strategy=None)
    if f.get("source") in ("meta", "apify"):
        cfg["monitoring"]["source"] = f["source"]
    cfg.setdefault("email", {})["enabled"] = "email_enabled" in f

    ENV.touch(exist_ok=True)
    secrets = {llm.KEY_ENV[provider]: f.get("api_key"), "APIFY_TOKEN": f.get("apify"),
               "SMTP_PASSWORD": f["email_password"].replace(" ", "")
               if f.get("email_password") else None}
    if f.get("email"):
        secrets.update(SMTP_TO=f["email"], SMTP_USER=f["email"], SMTP_HOST="smtp.gmail.com",
                       SMTP_PORT="587")
    notes = []
    if f.get("app_id") or f.get("app_secret") or f.get("explorer_token"):
        try:
            got = meta.connect(f.get("app_id", ""), f.get("app_secret", ""),
                               f.get("explorer_token", ""), cfg["brand"]["instagram"])
            secrets.update(IG_ACCESS_TOKEN=got["token"], IG_USER_ID=got["ig_user_id"])
            notes.append(f"Connected to Instagram @{got['username']}.")
        except ValueError as exc:
            notes.append(f"Instagram NOT connected: {exc}")
    for key, value in secrets.items():
        if value:
            set_key(str(ENV), key, value)

    CONFIG.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True),
                      encoding="utf-8")
    conn = db.connect(DB)
    db.init_schema(conn)
    db.set_watchlist(conn, f.get("accounts", "").splitlines(), cfg["brand"]["instagram"])
    conn.close()
    return " ".join(["Settings saved."] + notes)


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: str, status: int = 200, ctype: str = "text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _trusted(self) -> bool:
        origin = self.headers.get("Origin")
        return (self.headers.get("Host") in ALLOWED_HOSTS
                and (origin is None or origin.split("//", 1)[-1] in ALLOWED_HOSTS))

    def _dashboard(self, message: str = ""):
        cfg = load_config(str(CONFIG))
        conn = db.connect(DB)
        db.init_schema(conn)
        try:
            self._send(dashboard.render(dashboard.build_context(conn, cfg),
                                        interactive=True, message=message))
        finally:
            conn.close()

    def do_GET(self):
        if not self._trusted():
            return self._send("forbidden", 403, "text/plain")
        if self.path == "/":
            self._dashboard()
        elif self.path == "/settings":
            self._send(settings_page())
        elif self.path == "/report":
            report = ROOT / "reports" / "latest.html"
            self._send(report.read_text(encoding="utf-8") if report.exists()
                       else page("Report", '<p>No report yet — run the analysis first. '
                                           '<a href="/">Back</a></p>'))
        else:
            self._send("not found", 404, "text/plain")

    def do_POST(self):
        global _run
        if not self._trusted():
            return self._send("forbidden", 403, "text/plain")
        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        if self.path == "/settings":
            self._send(settings_page(save_settings(form)))
        elif self.path == "/link":
            conn = db.connect(DB)
            try:
                raw = form.get("idea_id", [""])[0]
                db.link_idea(conn, int(raw) if raw else None, form["shortcode"][0])
                msg = "Saved — it will count as a suggested post." if raw else "Unlinked."
            except (ValueError, KeyError) as exc:
                msg = f"Could not save: {exc}"
            finally:
                conn.close()
            self._dashboard(msg)
        elif self.path == "/run":
            if _run and _run.poll() is None:
                return self._dashboard("Already running — refresh in a few minutes.")
            LOG.parent.mkdir(exist_ok=True)
            _run = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT,
                                    stdout=LOG.open("a"), stderr=subprocess.STDOUT)
            self._dashboard("Started. It takes 5–15 minutes; refresh this page afterwards.")
        else:
            self._send("not found", 404, "text/plain")

    def log_message(self, format, *args):  # keep the Terminal window quiet
        pass


def main():
    url = f"http://127.0.0.1:{PORT}/"
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:  # already running in another window
        webbrowser.open(url)
        return
    print(f"Dashboard running at {url} — keep this window open; close it to stop.")
    webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
