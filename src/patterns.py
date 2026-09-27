"""Cluster stored analyses into named recurring content formats."""

import json
import logging

from src.analyze import extract_json, load_prompt

logger = logging.getLogger(__name__)

MAX_PATTERNS = 12


def _summarise(analyses: list) -> list:
    """Trim analyses to the fields the clustering prompt actually needs."""
    out = []
    for a in analyses:
        out.append({
            "reusable_pattern": a.get("reusable_pattern"),
            "hook_type": a.get("hook_type"),
            "audience": a.get("audience"),
            "ai_virality_score": a.get("ai_virality_score"),
            "performance_score": a.get("performance_score"),
        })
    return out


def detect_patterns(client, windows: dict, model: str, brand: dict) -> list:
    """Cluster the 7/30/90-day analyses into patterns. [] on failure or no data."""
    if not any(windows.get(k) for k in ("7", "30", "90")):
        logger.info("no analyses to cluster")
        return []

    prompt = load_prompt("patterns").format(
        brand_name=brand.get("name", ""),
        industry=brand.get("industry", ""),
        target_market=brand.get("target_market", ""),
        window_7=json.dumps(_summarise(windows.get("7", [])), indent=1),
        window_30=json.dumps(_summarise(windows.get("30", [])), indent=1),
        window_90=json.dumps(_summarise(windows.get("90", [])), indent=1),
    )

    try:
        resp = client.messages.create(
            model=model, max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(b.text for b in resp.content if hasattr(b, "text"))
    except Exception as exc:
        logger.error("pattern detection failed: %s", exc)
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
        logger.warning("pattern detection returned no usable array")
        return []

    return [p for p in data if p.get("pattern")][:MAX_PATTERNS]
