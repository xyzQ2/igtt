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


def test_blank_models_fall_back_to_provider_defaults(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("models:\n  provider: openai\n  text_analysis:\n  strategy: my-model\n")
    models = load_config(str(p))["models"]
    assert models["text_analysis"] == "gpt-5-mini"
    assert models["strategy"] == "my-model", "an explicit model always wins"


def test_unknown_provider_is_rejected(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("models:\n  provider: mistral\n")
    with pytest.raises(ValueError):
        load_config(str(p))


def test_industry_and_target_market_reach_every_formatted_prompt():
    """The operator sets these in config.yaml; a prompt that drops the placeholder
    silently stops retargeting on them."""
    brand = load_config("config.yaml")["brand"]
    assert brand["industry"].strip() and brand["target_market"].strip()
    for name in ("discover", "analyze_text", "patterns", "ideas"):
        text = Path(f"prompts/{name}.md").read_text()
        assert "{industry}" in text and "{target_market}" in text, name
