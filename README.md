# igtt — Instagram Content Intelligence

Daily competitive intelligence and content briefs for
[@drinktoiletwine](https://www.instagram.com/drinktoiletwine/).

## What it does

Every morning it collects recent posts from ~75 tracked Instagram accounts, ranks
them numerically for free, sends only the strongest to Claude for strategist
analysis and the top videos to Gemini for a recreation blueprint, clusters recurring
formats across 7/30/90 days, generates ten original content briefs, and writes
`reports/latest.html`.

Published posts are tracked the same way, so the system learns which formats work
for this account specifically.

## Setup

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in your keys
# put real handles in seeds.txt, then:
python seed_accounts.py
```

## Running

| Command | What it does |
|---|---|
| `python app.py` | One full daily run |
| `python discover.py` | Re-evaluate and evolve the account pool |
| `python post.py <idea_id>` | Publish one approved idea |
| `python -m pytest tests/ -v` | Run the test suite (no network) |

## Day-to-day

You edit two files and nothing else:

- `config.yaml` — accounts, limits, scoring weights, models
- `.env` — API keys

To publish, commit the finished video to `media/` and push it, then open
`reports/latest.html`, pick an idea, and run the **Publish approved idea**
workflow with its `idea_id` and `media/<filename>` as the `media_url` input.
Locally this is `python post.py <idea_id> --media-url media/<filename>`.

Instagram fetches the file itself — there is no upload endpoint — so the URL has
to be publicly reachable. A `media_url` without a scheme is resolved against
`posting.media_base_url` in `config.yaml`, which points at this repository's raw
URLs; that works only because the repository is public. A full `https://` URL is
passed through untouched if you host the video elsewhere. Either way the URL is
checked with a HEAD request before anything is sent to Instagram, because an
unfetchable URL fails inside the media container with an opaque error.

## Scheduling

GitHub Actions runs `daily.yml` Mondays and Thursdays at 11:00 UTC and `discover.yml` Mondays at 10:00 UTC.
Both commit `data/intelligence.db` back to the repository — that is how state survives
between runs, since Actions has no persistent disk.

Required repository secrets: `APIFY_TOKEN`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
`IG_ACCESS_TOKEN`, `IG_USER_ID`, and the `SMTP_*` set if email is
enabled.

The database schema is created on first run and has no migrations. If you upgrade from a
version before a schema change (e.g., a new column was added), delete `data/intelligence.db`
and let it be recreated.

## Cost ceilings

Enforced in code from `config.yaml`: 75 accounts, 7-day lookback, 40 text analyses
per day, 15 video analyses per day, 10 ideas per day, 1 post per day.

## What it will not do

- Copy competitor content. Formats are abstracted; ideas scored HIGH similarity risk
  are discarded before you ever see them.
- Repost anyone's video without recorded permission and a credit handle.
- Post unattended. `posting.auto` is `false`.
