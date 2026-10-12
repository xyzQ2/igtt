# How igtt works

An operator's guide to the intelligence loop: how accounts are found, how performance is
measured, how formats are identified, and how the daily ideas are produced.

Every number below lives in `config.yaml`, which is the only file you need to edit.

---

## 1. Finding comparable accounts

Two ways in, both via `discover.py`, run by manual dispatch only (the weekly schedule was dropped to keep Apify in its free tier).

**Hashtag search.** Apify searches the hashtags in `discovery.hashtags` — currently
`fashionmodel`, `femalemodel`, `modellife`, `editorialmodel`, `instamodel`, `latinamodel`,
`modelobrasileira`, `modelocolombiana`, `modelomexicana`, `modelpolaroids` (English, Spanish and Portuguese, for
North and South America) — and returns up to 600 posts
across them, split evenly per tag.

**The accounts already tracked.** These are put at the front of the candidate list so they
always survive the 100-candidate cap; a new hashtag hit can never push an established
account out of the evaluation.

Every candidate is then scored 0–100 by Claude (`prompts/discover.md`) for how useful it is
to monitor, judged against `brand.voice` and the `categories` list. Two thresholds decide
what happens:

| Score | Effect |
|---|---|
| ≥ `discovery.activate_above` (60) | Activated — starts being collected daily |
| 50–59 | Score updated, status unchanged |
| < `discovery.deactivate_below` (50) | Deactivated — stops being collected |

The pool is capped at `monitoring.max_accounts` (75). At the cap, new accounts are not
added, but existing ones can still be deactivated — so the pool drifts toward quality
rather than growing without limit.

**To search a different niche:** change `discovery.hashtags` and `categories`, then run
`python3 discover.py`. To force a specific account in regardless of score, add it to
`seeds.txt` and run `python3 seed_accounts.py`.

---

## 2. Measuring likes and engagement

Twice weekly (`app.py`, Mondays and Thursdays 11:00 UTC), Apify pulls the last `monitoring.posts_lookback_days` (30) days
of posts from every active account, up to `results_per_account` (8) each.

Each post is stored, and a **snapshot** of its counts is appended every run. That history is
what makes velocity possible — a post is measured repeatedly, not once.

Five metrics are derived per post (`src/score.py`):

| Metric | Meaning | Weight |
|---|---|---|
| `views_per_follower` | Reach relative to audience size — catches small accounts punching up | 0.30 |
| `engagement_rate` | (likes + comments + shares) ÷ views | 0.25 |
| `total_engagement` | Raw sum of interactions | 0.20 |
| `raw_views` | Absolute reach | 0.15 |
| `comments_per_follower` | Comment pull specifically — the strongest conversation signal | 0.10 |

Each metric is converted to a 0–100 **percentile rank against that day's cohort**, not an
absolute threshold. "Good" is defined by what the niche actually did that day.

**The rule that matters:** a metric the platform does not report stays `None`. It is never
folded into zero. Weights belonging to missing metrics are redistributed across the metrics
a post does have, so a carousel with no view count is not punished for failing to be a
video. A measured zero is real data and is treated as such.

**Velocity and acceleration.** With two snapshots the system computes views per hour; with
three it compares the latest window against the previous one. A post whose ratio is at or
above `scoring.acceleration_threshold` (1.5) is flagged as accelerating — catching a post
on the way up rather than after it peaked.

---

## 3. Identifying what actually works

Numeric ranking is free, so it runs over everything. AI is metered, so it runs only over
the top of the pile. That is the whole cost-control design.

**Text tier** — top `candidate_posts_for_text_ai` (40) posts/day, Claude
(`prompts/analyze_text.md`). Claude reads the caption and metrics **and the post's cover
image** (downloaded from Instagram's CDN; if that fails, the analysis runs on text alone).
For each post it extracts:

- **Hook** and **hook type** — curiosity / controversy / relatability / surprise / identity
  / aspiration / humor / disgust / status
- **Payoff**, **emotional driver**, **humor mechanism**
- **Social driver** (why someone sends it to a friend), **comment driver**,
  **rewatch driver**
- **Visual structure**, **caption role**, **audience**, **timing**
- **Why it overperformed** — the three strongest explanations
- **Reusable pattern** — the post abstracted into a formula, e.g. *"Highly recognizable
  situation + escalating frustration + absurd visual payoff"*
- Scores 0–100 for hook, shareability, originality, relatability, rewatchability, cultural
  relevance, plus an overall `ai_virality_score`

**Video tier** — currently **off** (`candidate_posts_for_video_ai: 0`; 15 when on), Gemini
(`prompts/analyze_video.md`). Gemini watches the actual video, because Claude has no native
video input. This is where pacing, cuts, on-screen text timing and audio get read — things
invisible in a caption.

**Final ranking** = 80% numeric performance + 20% `ai_virality_score`
(`scoring.ai_weight`). A post with no AI score keeps its numeric score alone rather than
being penalised.

**Pattern clustering** (`prompts/patterns.md`) runs across three windows — 7, 30 and 90 days
— and groups the reusable patterns into named recurring formats. Each gets occurrence counts
per window, average performance, a `trend_direction` of rising/flat/falling, and a
`dtw_relevance` 0–100 for fit to the brand. Up to 12 patterns, most significant first.

This is the answer to "what kind of post works": a **format**, not a topic. The prompt
explicitly demands *"Service-industry confessionals"*, not *"wine"*.

---

## 4. Getting content suggestions

`ideas.daily_count` (10) briefs are generated daily (`prompts/ideas.md`) from four inputs:

1. Today's top posts in the niche
2. The clustered patterns across 7/30/90 days
3. Ideas already generated recently — so it does not repeat itself
4. **How our own published posts actually performed** — the feedback loop; formats that work
   for this account specifically get weighted up

Each brief contains: concept, why now, the source pattern it builds on, hook, opening frame,
full script, on-screen text, shot list, caption, CTA, format, difficulty, confidence 0–100,
and a `similarity_risk` of LOW/MEDIUM/HIGH.

`similarity_risk` is a guardrail, not a label. An idea that would be recognisably the same
video as a single source post is marked HIGH and is **dropped before you ever see it**.
The system is built to abstract formats, never to clone posts.

Output lands in `reports/latest.html` (and email, if `email.enabled` is turned on).

---

## 5. Posting and measuring

You post from your phone; nothing posts by itself. Then tell the system which idea
the post came from:

- **Local install:** in the dashboard's *Your recent posts* table, pick the idea in
  the dropdown next to the post.
- **GitHub Actions:** run the **Link a post to the idea it came from** workflow with
  the idea number and the post's link (or `python link.py <idea_id> <url>`).

Our own posts are collected every run like everyone else's. The dashboard compares
each one with the median engagement (likes + comments + shares) of our other posts,
then splits "suggested" from "other", day by day and week by week. That comparison,
plus the views-vs-baseline results fed back into idea generation (input 4 above),
closes the loop.

---

## The knobs worth turning

| Want | Change |
|---|---|
| A different niche or audience | `brand.industry`, `brand.target_market`, `discovery.hashtags`, `categories`, `brand.voice` |
| Wider account net | `monitoring.max_accounts`, `discovery.activate_above` |
| More/fewer AI analyses (cost) | `candidate_posts_for_text_ai`, `candidate_posts_for_video_ai` |
| Reward reach over engagement | `scoring.*` weights |
| Catch trends earlier | lower `scoring.acceleration_threshold` |
| More ideas per day | `ideas.daily_count` |
| A different AI company | `models.provider` (anthropic / openai / google) + its key |
| Free data instead of Apify | `monitoring.source: meta` (no view counts for other accounts) |
| Trust the AI verdict more | raise `scoring.ai_weight` |

Costs scale with the AI candidate counts and the account pool, not with how many posts
exist. Numeric ranking over everything is free; only the top slice is ever sent to a model.
