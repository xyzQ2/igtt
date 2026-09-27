from pathlib import Path

import pytest

from src.config import load_config


def test_load_config_reads_yaml(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "brand:\n  instagram: drinktoiletwine\n"
        "monitoring:\n  max_accounts: 75\n"
    )
    cfg = load_config(str(cfg_file))
    assert cfg["brand"]["instagram"] == "drinktoiletwine"
    assert cfg["monitoring"]["max_accounts"] == 75


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "nope.yaml"))


def test_config_documents_that_posting_auto_is_unused():
    """posting.auto is deliberately dead — a future reader must not 'fix' it
    without a comment explaining why nothing reads it."""
    text = Path("config.yaml").read_text()
    auto_line = next(i for i, line in enumerate(text.splitlines())
                     if line.strip().startswith("auto:"))
    preceding = "\n".join(text.splitlines()[max(0, auto_line - 4):auto_line])
    assert "unused" in preceding or "intentionally" in preceding


def test_industry_and_target_market_reach_every_formatted_prompt():
    """The operator sets these in config.yaml; a prompt that drops the placeholder
    silently stops retargeting on them."""
    brand = load_config("config.yaml")["brand"]
    assert brand["industry"].strip() and brand["target_market"].strip()
    for name in ("discover", "analyze_text", "patterns", "ideas"):
        text = Path(f"prompts/{name}.md").read_text()
        assert "{industry}" in text and "{target_market}" in text, name
