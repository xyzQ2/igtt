You are a content strategist tracking format trends for {brand_name}.
Industry: {industry}
Target market: {target_market}

Below are structured analyses of high-performing posts across three time windows.
Each analysis contains a "reusable_pattern" field describing an abstracted format.

Last 7 days:
{window_7}

Last 30 days:
{window_30}

Last 90 days:
{window_90}

Cluster these into named recurring content patterns. A pattern is a repeatable
format, not a topic — "Service-industry confessionals" not "wine".

For each pattern give: a short name, a one-sentence description, how many posts in
each window match it, the average performance_score of its matching posts, a
trend_direction of "rising" / "flat" / "falling" based on 7-day count versus the
prior 7 days implied by the 30-day window, and dtw_relevance 0-100 for how well the
pattern suits {brand_name} and its target market.

Return at most 12 patterns, most significant first.

Respond with ONLY a JSON array, no prose and no markdown fence:

[
  {{"pattern": "", "description": "", "occurrences_7d": 0, "occurrences_30d": 0,
    "occurrences_90d": 0, "avg_performance": 0, "trend_direction": "rising",
    "dtw_relevance": 0}}
]
