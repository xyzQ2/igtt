"""Weekly: find new accounts worth monitoring, retire the ones that stopped fitting."""

import argparse
import json
import logging
import os
import sys

from anthropic import Anthropic

from src import apify, db
from src.analyze import extract_json, load_prompt
from src.config import load_config

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    stream=sys.stdout)
logger = logging.getLogger("discover")

MAX_CANDIDATES = 100


def score_candidates(client, candidates: list, brand: dict, model: str,
                     categories: list) -> list:
    """Score candidate accounts 0-100 for monitoring value. [] on failure."""
    if not candidates:
        return []

    prompt = load_prompt("discover").format(
        brand_name=brand.get("name", ""),
        brand_voice=brand.get("voice", ""),
        industry=brand.get("industry", ""),
        target_market=brand.get("target_market", ""),
        categories=", ".join(categories),
        candidates=json.dumps(candidates, indent=1, default=str),
    )
    try:
        resp = client.messages.create(
            model=model, max_tokens=16000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(b.text for b in resp.content if hasattr(b, "text"))
    except Exception as exc:
        logger.error("candidate scoring failed: %s", exc)
        return []

    data = extract_json(raw)
    if data is None or not isinstance(data, list):
        start, end = raw.find("["), raw.rfind("]")
        if start != -1 and end != -1:
            try:
                data = json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                data = None
    if not isinstance(data, list):
        # candidates is non-empty here (checked above) — a silent [] would let
        # the weekly run no-op while still exiting 0, so this is an error.
        logger.error("candidate scoring returned no usable array")
        return []

    return [c for c in data
            if isinstance(c, dict) and c.get("username")
            and c.get("relevance_score") is not None]


def run_discovery(config_path: str = "config.yaml",
                  db_path: str = "data/intelligence.db") -> dict:
    cfg = load_config(config_path)
    conn = db.connect(db_path)
    db.init_schema(conn)

    disc = cfg["discovery"]
    max_accounts = cfg["monitoring"]["max_accounts"]

    # Our own account is always collected by app.py; scoring it as a competitor
    # only produced noise (it swung between 5 and 100).
    own = cfg["brand"]["instagram"]
    existing = {r["username"]: r for r in db.get_active_accounts(conn)
                if r["username"] != own}
    hashtag_candidates = apify.search_hashtag_accounts(
        os.environ.get("APIFY_TOKEN", ""), disc["hashtags"], limit=200)

    # Build candidate list: existing accounts first (must survive cap), then new ones
    candidates = [{"username": username,
                   "followers": row["followers"],
                   "sample_captions": []}
                  for username, row in existing.items()]
    for cand in hashtag_candidates:
        if cand["username"] not in existing and cand["username"] != own:
            candidates.append(cand)

    candidates = candidates[:MAX_CANDIDATES]

    counts = apify.fetch_follower_counts(os.environ.get("APIFY_TOKEN", ""),
                                         [c["username"] for c in candidates])
    for cand in candidates:
        cand["followers"] = counts.get(cand["username"], cand["followers"])
    for username in existing:
        if username in counts:
            db.upsert_account(conn, username, followers=counts[username])

    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    scored = score_candidates(client, candidates, cfg["brand"],
                              cfg["models"]["strategy"], cfg["categories"])

    # Only activations are stored, so log the near misses: without them there
    # is no way to tell whether the hashtags or the threshold need changing.
    for cand in sorted(scored, key=lambda c: -(c.get("relevance_score") or 0))[:25]:
        logger.info("scored %s: %s (%s)", cand.get("username"),
                    cand.get("relevance_score"), (cand.get("reason") or "")[:100])

    stats = {"evaluated": len(scored), "activated": 0, "deactivated": 0}
    active_count = len(existing)

    for cand in scored:
        username = cand["username"]
        raw_score = cand.get("relevance_score")
        try:
            relevance = float(raw_score)
        except (TypeError, ValueError):
            logger.warning("skipping %s: unusable relevance_score %r",
                           username, raw_score)
            continue
        is_active = username in existing
        # The model can't be run at temperature 0 (Opus 5 rejects it), and the
        # same account scored 88 then 45 minutes apart. Averaging with the stored
        # score damps that, so one bad draw can't flip an account on or off.
        prev = existing[username]["relevance_score"] if is_active else None
        if prev is not None:
            relevance = (prev + relevance) / 2

        if relevance < disc["deactivate_below"]:
            if is_active:
                db.set_account_score(conn, existing[username]["id"], relevance, 0)
                stats["deactivated"] += 1
                active_count -= 1
                logger.info("deactivated %s (score %.0f)", username, relevance)
            continue

        if relevance >= disc["activate_above"] and not is_active:
            if active_count >= max_accounts:
                logger.info("at max_accounts (%d), not adding %s",
                            max_accounts, username)
                continue
            db.upsert_account(conn, username, category=cand.get("category"),
                              followers=counts.get(username),
                              relevance_score=relevance, active=1)
            stats["activated"] += 1
            active_count += 1
            logger.info("activated %s (score %.0f)", username, relevance)
        elif is_active:
            db.set_account_score(conn, existing[username]["id"], relevance, 1)

    conn.close()
    logger.info("discovery complete: %s", stats)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="igtt weekly account discovery")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--db", default="data/intelligence.db")
    args = parser.parse_args()
    run_discovery(args.config, args.db)


if __name__ == "__main__":
    main()
