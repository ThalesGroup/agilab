from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_front_matter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, f"Missing front matter in {path}"
    return yaml.safe_load(match.group(1))


def test_aider_repo_config_exposes_local_aliases_and_repo_reads() -> None:
    cfg = yaml.safe_load((REPO_ROOT / ".aider.conf.yml").read_text(encoding="utf-8"))

    assert cfg["no-auto-commits"] is True
    assert "AGENT_CONVENTIONS.md" in cfg["read"]
    assert "qwen-local:ollama_chat/qwen2.5-coder:latest" in cfg["alias"]
    assert "deepseek-local:ollama_chat/deepseek-coder:latest" in cfg["alias"]
    assert "gpt-oss-local:ollama_chat/gpt-oss:20b" in cfg["alias"]
    assert "qwen3-local:ollama_chat/qwen3:30b-a3b-instruct-2507-q4_K_M" in cfg["alias"]
    assert "qwen3-coder-local:ollama_chat/qwen3-coder:30b-a3b-q4_K_M" in cfg["alias"]
    assert "ministral-local:ollama_chat/ministral-3:14b-instruct-2512-q4_K_M" in cfg["alias"]
    assert "phi4-mini-local:ollama_chat/phi4-mini:3.8b-q4_K_M" in cfg["alias"]
    assert not any("mistral-local" in alias for alias in cfg["alias"])


def test_opencode_project_config_and_agents_use_agilab_defaults() -> None:
    cfg = json.loads((REPO_ROOT / "opencode.json").read_text(encoding="utf-8"))
    build = _load_front_matter(REPO_ROOT / ".opencode" / "agents" / "agilab-build.md")
    review = _load_front_matter(REPO_ROOT / ".opencode" / "agents" / "agilab-review.md")

    assert cfg["$schema"] == "https://opencode.ai/config.json"
    assert cfg["share"] == "disabled"
    assert cfg["default_agent"] == "agilab-build"

    assert build["mode"] == "primary"
    assert build["permission"]["*"] == "ask"
    assert build["permission"]["webfetch"] == "deny"
    assert build["permission"]["bash"]["git diff*"] == "allow"

    assert review["mode"] == "primary"
    assert review["permission"]["edit"] == "deny"
    assert review["permission"]["write"] == "deny"
    assert review["permission"]["webfetch"] == "deny"


def test_agent_workflow_wrappers_are_shell_valid_and_reference_repo_defaults() -> None:
    aider = REPO_ROOT / "tools" / "aider_workflow.sh"
    opencode = REPO_ROOT / "tools" / "opencode_workflow.sh"

    subprocess.run(["bash", "-n", str(aider), str(opencode)], check=True)

    aider_text = aider.read_text(encoding="utf-8")
    opencode_text = opencode.read_text(encoding="utf-8")

    assert ".aider.conf.yml" in aider_text
    assert "AGILAB_AIDER_MODEL" in aider_text
    assert "qwen-local" in aider_text

    assert "AGILAB_OPENCODE_MODEL" in opencode_text
    assert "AGILAB_OPENCODE_AGENT" in opencode_text
    assert "agilab-build" in opencode_text
    assert "agilab-review" in opencode_text
