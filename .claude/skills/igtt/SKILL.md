---
name: igtt
description: Use when working in the igtt project — the daily Instagram content-intelligence system (currently @jaquelinebycie, a female fashion model; formerly @drinktoiletwine). Covers the pipeline stages, the None-never-0 data rule, the cost ceilings, the prompt-formatting traps, the LLM/data-source switches and the local dashboard. Invoke before editing src/score.py, src/apify.py, src/meta.py, src/llm.py, app.py, serve.py, discover.py, or anything under prompts/.
---

# igtt

Daily Instagram content intelligence, currently for [@jaquelinebycie](https://www.instagram.com/jaquelinebycie/)
(female fashion model, North and South America; previously @drinktoiletwine, whose wine
accounts are deactivated in the DB, not deleted). Finds high-performing posts in the niche, works out why they
worked, abstracts each into a reusable format, generates original briefs, and measures how
the operator's own posts perform — suggested vs other. Since 2026-10-12 it is brand- and
provider-agnostic; Toilet Wine runs its own local copy (see *Shipping the local copy*).

## The pipeline

```
discover.py (manual)      app.py (daily locally / Mon+Thu on Actions)
hashtag search (Apify) →  collect: Apify OR Meta Business Discovery (monitoring.source)
LLM scores 0-100          → sqlite: posts + snapshots + runs
≥60 keep / <50 drop       → numeric rank (all posts, free)
                          → LLM text tier   (top 40, caption + cover image)
                          → Gemini video tier (top 15; OFF)
                          → pattern clustering (7/30/90d)
                          → 10 briefs → reports/latest.html + email
                          → reports/dashboard.html (src/dashboard.py, no AI)
                               ↓ operator posts from phone, links post → idea
                          serve.py dropdown / link.py / link.yml
```

**Universal since 2026-10-12.** Brand, AI provider and data source are all config.
`src/llm.py` gives every call site the Anthropic `client.messages.create` shape; OpenAI
(raw HTTP) and Google (google-genai) are shims that translate Anthropic image blocks.
Blank `models.text_analysis`/`strategy` → provider defaults (`resolve_models`, applied in
`load_config`). Publishing (post.py, src/instagram.py, raw-GitHub media hosting) was
removed: the operator posts from their phone and links the post to its idea; the
dashboard compares suggested vs other posts against our median engagement.

**Video tier is OFF** (`candidate_posts_for_video_ai: 0`, 2026-09-27, user's cost call —
do not re-enable unasked). Video stays Gemini-only whatever `models.provider` says.

**Meta source** (`src/meta.py`, graph.facebook.com, Page token from Facebook Login —
NOT the graph.instagram.com Instagram-Login token): Business Discovery sees only
Business/Creator accounts and never reports views, so `engagement_per_follower` carries
the ranking there. Our own posts come from `/{ig-user-id}/media` + insights (views,
shares). `meta.connect` turns a Graph API Explorer token into a non-expiring Page token.
Hashtag discovery has no Meta equivalent (hashtag media carries no username).

**Local install** (`Install.command` → `~/Instagram Analyzer`, launchd `com.igtt.daily`
at 08:00; `Start.command` → `serve.py` on 127.0.0.1:8765). It lives outside Downloads
because macOS TCC blocks background jobs from reading Downloads/Desktop/Documents.
`serve.py` rejects foreign Host/Origin (DNS rebinding/CSRF), never renders secrets
back, and writes secrets to `.env` via `set_key`.

## Non-negotiables

**`None` never becomes `0`.** A metric the platform does not report stores `None`, and
scoring skips it rather than ranking it low. Four separate truthiness bugs violated this
during the build — always at points where values are *aggregated* and a default made the
arithmetic easier. Before touching `post_metrics`, `score_posts`, or anything combining
counts, write the test that distinguishes a measured zero from an unmeasured value.

Two truthiness guards are deliberate and carry comments saying so: `engagement_rate`'s
`if views` and `vs_baseline`'s `and baseline` — division by zero is undefined, not missing.

**Cost ceilings are enforced by truncation in code, not by trust.** 75 accounts, 30-day
lookback, 8 posts/account, 40 text analyses/day, 0 video analyses/day (off; 15 when on), 25 top posts, 10 ideas/day.
All live in `config.yaml`; each has a call site that actually slices. If you add a ceiling,
enforce it — the old `posting.max_per_day` sat unenforced for a whole build while the README
claimed otherwise. The Settings page clamps every number it exposes (`serve.NUMBERS`).

**Apify is on its free $5/month credit and the user will not pay.** That is why
`results_per_account` is 8 (was 20) and `discover.yml` is manual-dispatch only (the weekly
hashtag scrape alone cost ~$2–4/month). Budget: ~16 accounts × 8 posts + 16 `details` items
× ~9 runs/month ≈ $3–3.50. Anything that adds scraped items — more accounts, a higher
`results_per_account`, a discovery cron, more run days — must be priced against that $5
first. When the credit runs out, Apify returns 402 and the run collects 0 posts; `app.py` then
skips every Claude call and exits 1, so the run shows red.

**Idea linking is manual.** `db.link_idea` moves a shortcode between ideas (one post,
at most one idea) and `None` unlinks. Nothing guesses which idea a post came from.

**XSS.** `src/report.py` and `src/dashboard.py` render scraped captions into HTML.
`autoescape=True` is mandatory; `serve.py` escapes with `html.escape`. Reaching for `|safe`, `Markup`, or `autoescape=False` is a stop-and-ask.

## Traps that pass unit tests and break at runtime

- **Prompt brace escaping.** Every prompt passed through `str.format()` — `analyze_text`,
  `patterns`, `ideas`, `discover` — must double every literal JSON brace (`{{`, `}}`).
  `analyze_video.md` is NOT formatted and uses single braces. Getting it wrong raises
  `KeyError` on the first real post while the tests stay green.
- **`extract_json` returns a dict for a single-element array.** It locates the first `{`
  and last `}`, so `[{"a": 1}]` parses as a dict. Any array-parsing fallback must read
  `if data is None or not isinstance(data, list):`. Three files carried this bug.
- **No schema migrations.** `init_schema` is `CREATE TABLE IF NOT EXISTS` with no
  `ALTER TABLE` anywhere. Adding a column means an existing `data/intelligence.db` breaks;
  delete it and let it rebuild.
- **State lives in git (Actions setup).** The daily, discover and link workflows commit
  `data/intelligence.db` back, because Actions has no persistent disk and the 30/90-day
  windows need the history. All three share `concurrency: group: igtt-db` — a workflow that writes the DB without
  it will silently overwrite a day of history, since git cannot merge SQLite.

- **Thinking models eat `max_tokens`.** Sonnet 5 and Opus 5 think by default and
  thinking counts against `max_tokens`. At 2000/4000 the JSON was cut off and
  `extract_json` quietly returned nothing ("pattern detection returned no usable array",
  "bad text analysis"). Every Claude call now uses 16000; only used tokens are billed.
  Opus 5 also **rejects `temperature`** (400), so determinism can't come from sampling.
- **Apify: two actors, three shapes.** Profile posts and profile details come from
  `apify~instagram-scraper` (`directUrls`, `resultsType` `posts` or `details`). Hashtag
  search must use `apify~instagram-hashtag-scraper` with a `hashtags` list — the general
  scraper's `search` field takes ONE query, so joined tags matched nothing and discovery
  found 0 accounts for two weeks while every run was green. Post items never carry
  `ownerFollowersCount`; follower counts come only from the `details` call
  (`fetch_follower_counts`). Items without `shortCode` are per-profile errors and are
  logged, not silently dropped. An auth failure returns a dict, not a list — guard it.
- **Never send `onlyPostsNewerThan` to the profile scraper.** With it, 8 of 14 profiles
  came back `no_items "Empty or private data"` — an old pinned post stops the actor before
  the recent posts. `fetch_profile_posts` filters by `posted_at` in code instead; after the
  fix every account returned items. `Restricted profile` is different: age-restricted
  accounts need a logged-in scraper — drop them.
- **Cover images go to Claude as base64**, downloaded only from Instagram's CDN over https
  (`_trusted_https`, shared with the video tier). Any download failure falls back to
  text-only; conftest blocks `requests.get` so tests never fetch media.
- **Hashtag discovery saturates.** 200 vs 600 sample posts both yielded ~65 distinct
  accounts, mostly tiny or off-target. Broad tags (`ootd`, `moda`) return shops. Operator
  seed handles beat hashtags; discovery logs the top 25 scores so near misses are visible.
- **Report delivery is email, not a public page.** Publishing `reports/latest.html` via
  GitHub Pages was blocked as a data leak — do not retry. An unset `SMTP_PORT` secret
  arrives as `""`, hence `or 587`.
- **Green runs hide empty pipelines.** Every stage catches and logs, so a run with 0
  accounts, 0 videos or no patterns still exits 0. After any change, read the
  `daily run complete` / `discovery complete` stats line, not the run status.
- **Meta tokens come in two kinds.** Business Discovery and insights need a Facebook-Login
  Page token on graph.facebook.com. The old `IG_ACCESS_TOKEN` secret in xyzQ2/igtt is an
  Instagram-Login token (graph.instagram.com) from the publishing era — it will NOT work with
  `monitoring.source: meta`. Business Discovery returns 400 per account for personal/private
  accounts; `fetch_profile_posts` logs and skips them.
- **The dashboard is rebuilt from the DB, never from run memory.** `dashboard.build_context`
  re-scores posts with `score.score_posts`, so a `mocker.spy` on `score_posts` in app tests
  sees two calls — assert on `call_args_list[0]`. New tables (like `runs`) are fine without
  migrations; new columns are not.
- **Our own engagement baseline needs 3 other measured posts.** Below that `vs_normal` is
  None and the tiles show "—". That is correct, not a bug.
- **Tests block every network boundary.** conftest refuses `src.apify.requests.post`,
  `src.meta.requests.get`, `src.llm.requests.post` and media downloads. A new HTTP call site
  needs a matching block.
- **Discovery excludes our own account and damps noise.** `brand.instagram` is never
  scored (app.py always collects it). An active account's new relevance score is averaged
  with its stored one, because the same account scored 88 then 45 minutes apart.

## Layout

| Path | Responsibility |
|---|---|
| `config.yaml` | every tunable. The only file a non-developer edits |
| `src/db.py` | schema and **all** SQL in the project |
| `src/apify.py` | the only module that knows scraping exists |
| `src/score.py` | pure functions: percentiles, velocity, acceleration. No I/O |
| `src/analyze.py` | Claude text tier + Gemini video tier |
| `src/patterns.py`, `src/ideas.py` | clustering and brief generation |
| `src/report.py` | jinja2 render + optional SMTP |
| `src/llm.py` | provider switch: Anthropic SDK or OpenAI/Google shim |
| `src/meta.py` | Meta Graph API source: Business Discovery, own insights, connect |
| `src/dashboard.py` | dashboard context from the DB, no AI |
| `serve.py` | local dashboard + settings + Run now |
| `prompts/*.md` | tuned without touching code |
| `app.py` / `discover.py` / `serve.py` / `link.py` | entry points |
| `docs/how-it-works.md` | operator guide: discovery, metrics, pattern clustering, the knobs |

## Commands

```
python app.py                    one full daily run
python discover.py               re-evaluate the account pool
python serve.py                  local dashboard + settings
python link.py <idea_id> <url>   mark which idea a post came from
python seed_accounts.py          load seeds.txt
python3 -m pytest tests/ -q
```

## Shipping the local copy

Toilet Wine (@drinktoiletwine, non-technical, Mac) runs a standalone snapshot at
`~/Downloads/hft/Toilet Wine Instagram Analyzer`: `app.py serve.py seed_accounts.py src/
prompts/ Install.command Start.command "START HERE.html"`, plus its own `config.yaml`
(wine brand, `source: meta`), wine `seeds.txt`, and `requirements.txt` without pytest. No
tests, workflows, discover.py or link.py. After changing any of those files, re-sync:

```
rsync -a --exclude __pycache__ app.py serve.py seed_accounts.py src prompts \
  Install.command Start.command "START HERE.html" "$HOME/Downloads/hft/Toilet Wine Instagram Analyzer/"
```

Never copy `config.yaml`, `seeds.txt`, `.env` or `data/` over it. `Install.command` is
re-runnable and never overwrites the installed `config.yaml`, `.env`, `data/` or `logs/`.
It installs to `~/Instagram Analyzer`, because macOS blocks launchd jobs from reading
Downloads, Desktop and Documents. Test the installer with a fake `HOME` and stubbed
`launchctl`/`open` on PATH, never against the real home.

Tests never touch the network — Apify, Meta, Anthropic, OpenAI and Gemini are all mocked at
their boundary, and fixtures live in `tests/fixtures/`.
