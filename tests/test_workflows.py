"""Structural checks on the GitHub Actions workflows — no execution, just
parsing, since a broken concurrency guard or a shell-injection pattern here
is a real defect even though nothing in tests/ can run the workflow itself.
"""

from pathlib import Path

import yaml

WORKFLOW_DIR = Path(__file__).parent.parent / ".github" / "workflows"


def _load(name):
    return yaml.safe_load((WORKFLOW_DIR / name).read_text(encoding="utf-8"))


def test_all_workflows_share_the_db_concurrency_group():
    """daily.yml, discover.yml and link.yml all commit data/intelligence.db —
    without a shared concurrency group, an overlapping run silently clobbers it."""
    for name in ("daily.yml", "discover.yml", "link.yml"):
        wf = _load(name)
        concurrency = wf.get("concurrency")
        assert concurrency is not None, f"{name} is missing a concurrency block"
        assert concurrency.get("group") == "igtt-db"
        assert concurrency.get("cancel-in-progress") is False


def test_link_yml_passes_inputs_through_env_not_inline():
    """Dispatch inputs must never be interpolated directly into `run:` —
    that is a shell-injection vector. They must go through env: instead."""
    steps = _load("link.yml")["jobs"]["link"]["steps"]
    step = next(s for s in steps if s.get("name") == "Link")
    assert "${{" not in step["run"], "dispatch inputs must be passed via env:, not inlined"
    assert "inputs.idea_id" in step["env"]["IDEA_ID"]
    assert "inputs.post_url" in step["env"]["POST_URL"]
