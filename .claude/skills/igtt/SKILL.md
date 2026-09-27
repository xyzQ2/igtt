---
name: igtt
description: Use when working in the igtt project — the daily Instagram content-intelligence system (currently @jaquelinebycie, a female fashion model; formerly @drinktoiletwine). Covers the pipeline stages, the None-never-0 data rule, the cost ceilings, the prompt-formatting traps, and the publish guardrails. Invoke before editing src/score.py, src/apify.py, app.py, post.py, discover.py, or anything under prompts/.
---

# igtt

Daily Instagram content intelligence, currently for [@jaquelinebycie](https://www.instagram.com/jaquelinebycie/)
(female fashion model, North and South America; previously @drinktoiletwine, whose wine
accounts are deactivated in the DB, not deleted). Finds high-performing posts in the niche, works out why they
worked, abstracts each into a reusable format, generates original briefs, and measures how
the published results perform.

## The pipeline

```
discover.py (weekly)      app.py (daily)                     post.py (on dispatch)
hashtag search        →   Apify: recent posts, tracked accts
Claude scores 0-100       → sqlite: posts + snapshots
≥60 keep / <50 drop       → numeric rank (all posts, free)
                          → Claude text tier   (top 40)
                          → Gemini video tier  (top 15)
                          → pattern clustering (7/30/90d)
                          → 10 DTW briefs
                          → reports/latest.html + email
                               ↓ operator picks one
                                            GH Actions dispatch
                                            → IG Graph API → mark posted
                                            → track our own metrics
```

**Video tier is OFF** (`candidate_posts_for_video_ai: 0`, 2026-09-27, user's cost call —
do not re-enable unasked). Two AI vendors on purpose: Claude does all text, Gemini watches video because Claude has
no native video input. Splitting them was cheaper than frame extraction plus transcription.

**Media hosting.** The Graph API has no upload endpoint — Instagram fetches the `media_url`
itself. A `media_url` without a scheme is resolved against `posting.media_base_url`, which
points at this repository's raw URLs; that works only because the repo is **public**. Make
it private and publishing breaks silently. Absolute URLs pass through untouched.

## Non-negotiables

**`None` never becomes `0`.** A metric the platform does not report stores `None`, and
scoring skips it rather than ranking it low. Four separate truthiness bugs violated this
during the build — always at points where values are *aggregated* and a default made the
arithmetic easier. Before touching `post_metrics`, `score_posts`, or anything combining
counts, write the test that distinguishes a measured zero from an unmeasured value.

Two truthiness guards are deliberate and carry comments saying so: `engagement_rate`'s
`if views` and `vs_baseline`'s `and baseline` — division by zero is undefined, not missing.

**Cost ceilings are enforced by truncation in code, not by trust.** 75 accounts, 30-day
lookback, 40 text analyses/day, 0 video analyses/day (off; 15 when on), 25 top posts, 10 ideas/day,
1 post/day. All live in `config.yaml`; each has a call site that actually slices. If you
add a ceiling, enforce it — `posting.max_per_day` sat unenforced for a whole build while
the README claimed otherwise.

**Publish guardrails.** `post.py` refuses on: unknown id, already posted, HIGH
`similarity_risk`, no `media_url`, a `media_url` that fails a HEAD check, missing
credentials, daily cap reached, and a repost whose `repost_candidates` row lacks
`permission_granted = 1` AND a non-empty `credit_handle`. Every refusal precedes any network call. The repost gate is a copyright
guardrail — a strike costs the account the system exists to grow. Each guard has a test
that fails when the guard is removed; keep it that way.

**XSS.** `src/report.py` renders scraped captions into HTML. `autoescape=True` is
mandatory. Reaching for `|safe`, `Markup`, or `autoescape=False` is a stop-and-ask.

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
- **State lives in git.** Both workflows commit `data/intelligence.db` back, because
  Actions has no persistent disk and the 30/90-day windows need the history. All three
  workflows share `concurrency: group: igtt-db` — a workflow that writes the DB without
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
- **Green runs hide empty pipelines.** Every stage catches and logs, so a run with 0
  accounts, 0 videos or no patterns still exits 0. After any change, read the
  `daily run complete` / `discovery complete` stats line, not the run status.
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
| `src/instagram.py` | Instagram Graph API container + publish |
| `prompts/*.md` | tuned without touching code |
| `app.py` / `discover.py` / `post.py` | the three entry points |
| `docs/how-it-works.md` | operator guide: discovery, metrics, pattern clustering, the knobs |

## Commands

```
python app.py                    one full daily run
python discover.py               re-evaluate the account pool
python post.py <idea_id>         publish one approved idea
python seed_accounts.py          load seeds.txt
.venv/bin/python -m pytest tests/ -q
```

Tests never touch the network — Apify, Anthropic, Gemini and the Graph API are all mocked at
their boundary, and fixtures live in `tests/fixtures/`.
