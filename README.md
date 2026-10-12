# igtt — Instagram Content Intelligence

Daily competitive intelligence, content ideas and a performance dashboard for any
Instagram brand. Set the brand in `config.yaml` (or the Settings page).

## What it does

Every run it collects recent posts from the accounts you track, ranks them
numerically for free, sends only the strongest to an AI model for analysis,
clusters recurring formats across 7/30/90 days, writes ten original content ideas,
and builds:

- `reports/latest.html`: the daily report with ideas (it's also emailed if email is on)
- `reports/dashboard.html`: top posts, traction (who is gaining fastest) and how
  **your** posts made from suggested ideas perform against your normal, daily
  and weekly

You post from your phone as usual. Then you mark which idea a post came from, so the
dashboard can measure suggested content separately.

## Choices

| Setting | Options |
|---|---|
| AI provider (`models.provider`) | `anthropic` (ANTHROPIC_API_KEY), `openai` (OPENAI_API_KEY), `google` (GEMINI_API_KEY) |
| Data source (`monitoring.source`) | `meta` (default): free via your own Meta app (IG_ACCESS_TOKEN + IG_USER_ID, a Facebook-Login Page token). Business/Creator accounts only, no views for other accounts. Accounts Meta can't read (personal ones, or all while Meta isn't connected) fall back to Apify when APIFY_TOKEN is set. `apify`: Apify only, paid, includes views |
| Email | `email.enabled` + SMTP_HOST / SMTP_USER / SMTP_PASSWORD / SMTP_TO |

Blank `models.text_analysis` / `models.strategy` use the provider defaults in
`src/llm.py`. Video analysis is Gemini-only and off by default.

## Two ways to run it

**On a Mac, no technical setup:** double-click `Install.command`, then
`Start.command`. Everything is set from the Settings page in the browser, and the
run happens daily at 8:00. Step-by-step guide: `START HERE.html`.

**On GitHub Actions:** `daily.yml` runs on its cron (currently Mon+Thu, which keeps
Apify inside its free tier). Each run commits `data/intelligence.db` back, because
Actions has no persistent disk. To mark which idea a post came from, run the
**Link a post to the idea it came from** workflow. Repository secrets are the
environment variables named in the table above.

## Commands

| Command | What it does |
|---|---|
| `python app.py` | One full run |
| `python serve.py` | Local dashboard + settings at http://127.0.0.1:8765 (set `DASHBOARD_PASSWORD` in `.env`, or Settings → Phone access, to open it from a phone on the same Wi-Fi) |
| `python link.py <idea_id> <post URL>` | Mark which idea a post came from |
| `python discover.py` | Find new accounts via hashtags (Apify only) |
| `python seed_accounts.py` | Load `seeds.txt` |
| `python -m pytest tests/ -q` | Test suite (no network) |

The database schema has no migrations. New tables are added automatically. If a
column changes, delete `data/intelligence.db` and it will be rebuilt.

## What it will not do

- Copy competitor content. Formats are abstracted, and ideas scored HIGH similarity
  risk are discarded before you see them.
- Post for you. You publish. It measures.
