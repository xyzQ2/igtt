"""AI analysis. Claude handles text; Gemini handles video (see analyze_video)."""

import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from google import genai
from google.genai import types as genai_types

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).parent.parent / "prompts"
MAX_ATTEMPTS = 2

TEXT_REQUIRED_KEYS = {
    "hook", "hook_type", "payoff", "emotional_driver", "humor_mechanism",
    "social_driver", "comment_driver", "rewatch_driver", "visual_structure",
    "caption_role", "audience", "timing", "why_it_overperformed",
    "reusable_pattern", "scores", "ai_virality_score",
}

VIDEO_REQUIRED_KEYS = {
    "core_concept", "target_audience", "hook_analysis",
    "content_structure", "visual_style", "recreation_framework",
}
VIDEO_MAX_BYTES = 20 * 1024 * 1024  # inline upload ceiling
ALLOWED_VIDEO_HOSTS = ("cdninstagram.com", "fbcdn.net")

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def extract_json(text: str):
    """Parse a JSON object out of a model response. None if there isn't one."""
    if not text:
        return None
    candidate = text.strip()
    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1)
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(candidate[start:end + 1])
    except json.JSONDecodeError:
        return None


def _call_claude(client, model: str, prompt: str, max_tokens: int = 2000):
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in resp.content if hasattr(block, "text"))


def analyze_text(client, post: dict, brand: dict, model: str):
    """Tier 1 strategist analysis of one post. None on any failure."""
    payload = {k: post.get(k) for k in (
        "shortcode", "username", "caption", "content_type", "posted_at",
        "duration_sec", "views", "likes", "comments", "owner_followers",
        "performance_score",
    )}
    prompt = load_prompt("analyze_text").format(
        brand_name=brand.get("name", ""),
        brand_voice=brand.get("voice", ""),
        industry=brand.get("industry", ""),
        target_market=brand.get("target_market", ""),
        post_json=json.dumps(payload, indent=2, default=str),
    )

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = _call_claude(client, model, prompt)
        except Exception as exc:
            logger.error("claude text analysis failed for %s: %s",
                         post.get("shortcode"), exc)
            return None
        data = extract_json(raw)
        if data and TEXT_REQUIRED_KEYS <= set(data):
            return data
        logger.warning("bad text analysis for %s (attempt %d/%d)",
                       post.get("shortcode"), attempt, MAX_ATTEMPTS)
    return None


def analyze_video(api_key: str, video_url, model: str):
    """Tier 2 recreation blueprint from the actual video. None on any failure.

    Claude cannot take video input, so Gemini handles this one job.
    """
    if not video_url:
        return None

    parsed = urlparse(video_url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not any(
        host == h or host.endswith("." + h) for h in ALLOWED_VIDEO_HOSTS
    ):
        logger.error("refusing to fetch video_url with untrusted scheme/host: %s",
                     video_url)
        return None

    try:
        resp = requests.get(video_url, timeout=120)
        resp.raise_for_status()
        video_bytes = resp.content
    except Exception as exc:
        logger.error("video download failed for %s: %s", video_url, exc)
        return None

    if len(video_bytes) > VIDEO_MAX_BYTES:
        logger.warning("video too large (%d bytes), skipping: %s",
                       len(video_bytes), video_url)
        return None

    prompt = load_prompt("analyze_video")
    try:
        client = genai.Client(api_key=api_key)
        result = client.models.generate_content(
            model=model,
            contents=[
                genai_types.Part.from_bytes(data=video_bytes, mime_type="video/mp4"),
                prompt,
            ],
        )
        data = extract_json(result.text)
    except Exception as exc:
        logger.error("gemini video analysis failed for %s: %s", video_url, exc)
        return None

    if data and VIDEO_REQUIRED_KEYS <= set(data):
        return data
    logger.warning("incomplete blueprint for %s", video_url)
    return None
