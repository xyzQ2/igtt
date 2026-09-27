"""Generate original content briefs from patterns, top posts, and our own results."""

import json
import logging

from src.analyze import extract_json, load_prompt

logger = logging.getLogger(__name__)

REQUIRED_KEYS = {"concept", "hook", "script", "caption", "similarity_risk"}


def generate_ideas(client, context: dict, model: str, count: int) -> list:
    """Return up to `count` briefs. HIGH similarity_risk ideas are dropped."""
    brand = context.get("brand", {})
    prompt = load_prompt("ideas").format(
        brand_name=brand.get("name", ""),
        brand_voice=brand.get("voice", ""),
        industry=brand.get("industry", ""),
        target_market=brand.get("target_market", ""),
        count=count,
        top_posts=json.dumps(context.get("top_posts", []), indent=1, default=str),
        patterns=json.dumps(context.get("patterns", []), indent=1, default=str),
        previous_ideas=json.dumps(context.get("previous_ideas", []), indent=1, default=str),
        our_results=json.dumps(context.get("our_results", []), indent=1, default=str),
    )

    try:
        resp = client.messages.create(
            model=model, max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(b.text for b in resp.content if hasattr(b, "text"))
    except Exception as exc:
        logger.error("idea generation failed: %s", exc)
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
        logger.warning("idea generation returned no usable array")
        return []

    kept = []
    for item in data:
        if not isinstance(item, dict) or not REQUIRED_KEYS <= set(item):
            continue
        if str(item.get("similarity_risk", "")).upper() == "HIGH":
            logger.info("rejected idea for HIGH similarity risk: %s",
                        item.get("concept"))
            continue
        kept.append(item)

    return kept[:count]
