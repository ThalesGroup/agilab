from __future__ import annotations

import json
import os
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "github_ai_scraper_check.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("github_ai_scraper_check_test_module", TOOL_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_agilab_metadata_stays_discoverable_by_github_ai_scraper_contract() -> None:
    tool = _load_tool()
    report = tool.static_contract_report(REPO_ROOT)

    assert report["success"]
    assert report["query"] == "stars:>10 topic:ai-engineering"
    assert {check["name"] for check in report["checks"]} >= {
        "query",
        "core_keywords",
        "evidence_keywords",
        "repository_url",
        "description",
        "scraper_filter",
        "readme_badge",
        "pypi_readme_badge",
    }
    assert tool.github_ai_scraper_would_keep_repo(
        name="agilab",
        description="Open-source platform for reproducible AI/ML workflows, from local experimentation to distributed workers and long-lived services.",
        topics=tool.PUBLIC_GITHUB_TOPICS,
    )


def test_scraper_discoverability_badge_is_publicly_visible() -> None:
    tool = _load_tool()
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    pypi_readme = (REPO_ROOT / "README.pypi.md").read_text(encoding="utf-8")

    for text in (readme, pypi_readme):
        assert tool.SCRAPER_PACKAGE_URL in text
        assert tool.SCRAPER_BADGE_URL in text
        assert "github--ai--scraper-discoverable" in text


def test_github_ai_scraper_tool_static_json_output(tmp_path: Path) -> None:
    output_path = tmp_path / "github-ai-scraper.json"

    completed = subprocess.run(
        [
            sys.executable,
            "tools/github_ai_scraper_check.py",
            "--json",
            "--output",
            str(output_path),
        ],
        check=True,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    stdout_payload = json.loads(completed.stdout)
    file_payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert stdout_payload == file_payload
    assert file_payload["schema"] == "agilab.github_ai_scraper_check.v1"
    assert file_payload["mode"] == "static"
    assert file_payload["success"]
    assert "live" not in file_payload


def test_github_ai_scraper_tool_print_only_plans_live_without_running(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["GITHUB_TOKEN"] = "ghp_test_secret_should_be_redacted"

    completed = subprocess.run(
        [
            sys.executable,
            "tools/github_ai_scraper_check.py",
            "--live",
            "--print-only",
            "--json",
            "--work-dir",
            str(tmp_path),
            "--max-results",
            "17",
        ],
        check=True,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )

    payload = json.loads(completed.stdout)
    assert payload["success"]
    assert payload["mode"] == "live"
    assert payload["print_only"] is True
    assert "live" not in payload
    assert payload["live_plan"]["commands"][0][:3] == ["uvx", "--from", "github-ai-scraper"]
    assert payload["live_plan"]["commands"][0][-2:] == ["--max-results", "17"]
    assert "max_results: 17" in payload["live_plan"]["config_text"]
    assert "ghp_test_secret_should_be_redacted" not in payload["live_plan"]["config_text"]
    assert "token: ***" in payload["live_plan"]["config_text"]


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("AGILAB_GITHUB_AI_SCRAPER_LIVE") != "1",
    reason="set AGILAB_GITHUB_AI_SCRAPER_LIVE=1 to run the live github-ai-scraper discovery check",
)
def test_live_github_ai_scraper_collects_agilab(tmp_path: Path) -> None:
    output_path = tmp_path / "github-ai-scraper-live.json"
    completed = subprocess.run(
        [
            sys.executable,
            "tools/github_ai_scraper_check.py",
            "--live",
            "--json",
            "--work-dir",
            str(tmp_path / "work"),
            "--output",
            str(output_path),
        ],
        check=True,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )

    payload = json.loads(completed.stdout)
    assert payload == json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["live"]["agilab_found"]
