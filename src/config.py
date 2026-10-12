"""Loads config.yaml and .env. The only place either is read."""

import logging
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.llm import resolve_models

logger = logging.getLogger(__name__)


def load_config(path: str = "config.yaml") -> dict:
    """Read config.yaml and load .env into the environment."""
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"config not found: {cfg_path}")
    load_dotenv()
    with cfg_path.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    cfg["models"] = resolve_models(cfg.get("models") or {})
    logger.debug("loaded config from %s", cfg_path)
    return cfg
