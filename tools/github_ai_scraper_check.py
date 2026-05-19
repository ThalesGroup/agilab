#!/usr/bin/env python3
"""Check whether AGILAB remains discoverable by github-ai-scraper."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agilab.github_ai_scraper_check.v1"
AGILAB_URL = "https://github.com/ThalesGroup/agilab"
LIVE_ENV = "AGILAB_GITHUB_AI_SCRAPER_LIVE"
SCRAPER_PACKAGE = "github-ai-scraper"
SCRAPER_EXECUTABLE = "ai-scraper"
SCRAPER_PACKAGE_URL = "https://pypi.org/project/github-ai-scraper/"
SCRAPER_BADGE_URL = "https://img.shields.io/badge/github--ai--scraper-discoverable-0F766E"
DEFAULT_OUTPUT = "test-results/github-ai-scraper-discoverability.json"

PUBLIC_GITHUB_TOPICS = (
    "agentic-ai",
    "ai",
    "ai-agents",
    "ai-engineering",
    "codex",
    "cython",
    "dask",
    "data-science",
    "distributed-computing",
    "experiment-tracking",
    "free-threaded-python",
    "jupyter-notebook",
    "machine-learning",
    "mlflow",
    "mlops",
    "python",
    "reproducibility",
    "reproducible-research",
    "streamlit",
    "workflow-orchestration",
)


@dataclass(frozen=True, slots=True)
class ScraperContract:
    min_stars: int = 10
    topics: tuple[str, ...] = (
        "ai-engineering",
        "ai",
        "machine-learning",
        "mlops",
        "ai-agents",
        "reproducibility",
        "reproducible-research",
        "jupyter-notebook",
        "mlflow",
        "workflow-orchestration",
        "data-science",
    )
    keywords: tuple[str, ...] = (
        "ai",
        "ai/ml",
        "machine learning",
        "mlops",
        "reproducibility",
        "reproducible",
        "agent",
        "notebook",
        "mlflow",
    )


DEFAULT_CONTRACT = ScraperContract()


def github_ai_scraper_query(contract: ScraperContract = DEFAULT_CONTRACT) -> str:
    primary_topic = contract.topics[0] if contract.topics else "ai"
    return f"stars:>{contract.min_stars} topic:{primary_topic}"


def github_ai_scraper_would_keep_repo(
    *,
    name: str,
    description: str,
    topics: Sequence[str],
    contract: ScraperContract = DEFAULT_CONTRACT,
) -> bool:
    """Mirror github-ai-scraper 0.1.2's public topic/keyword AI filter."""

    text_to_check = f"{name} {description}".lower()
    repo_topics = {topic.lower() for topic in topics}

    if any(topic.lower() in repo_topics for topic in contract.topics):
        return True

    for keyword in contract.keywords:
        keyword_lower = keyword.lower()
        keyword_normalized = keyword_lower.replace("-", " ")
        if keyword_normalized in text_to_check or keyword_lower in text_to_check:
            return True

    return False


def static_contract_report(repo_root: Path = REPO_ROOT, contract: ScraperContract = DEFAULT_CONTRACT) -> dict[str, Any]:
    project = _load_project(repo_root)
    readme = _read_text(repo_root / "README.md")
    pypi_readme = _read_text(repo_root / "README.pypi.md")
    keywords = {str(keyword).lower() for keyword in project.get("keywords", [])}
    urls = project.get("urls", {})
    description = str(project.get("description", ""))
    checks = [
        _check("query", github_ai_scraper_query(contract) == "stars:>10 topic:ai-engineering"),
        _check("core_keywords", {"ai", "ai-engineering", "machine-learning", "mlops", "ai-agents"} <= keywords),
        _check("evidence_keywords", {"reproducibility", "reproducible-research", "jupyter-notebook", "mlflow"} <= keywords),
        _check("repository_url", urls.get("Repository") == AGILAB_URL and urls.get("Source") == AGILAB_URL),
        _check("description", "reproducible ai/ml" in description.lower()),
        _check("public_topics", "ai-engineering" in PUBLIC_GITHUB_TOPICS and "ai" in PUBLIC_GITHUB_TOPICS),
        _check("public_topics_no_vendor_noise", "claude" not in PUBLIC_GITHUB_TOPICS),
        _check(
            "scraper_filter",
            github_ai_scraper_would_keep_repo(
                name="agilab",
                description=(
                    "Open-source platform for reproducible AI/ML workflows, from local experimentation "
                    "to distributed workers and long-lived services."
                ),
                topics=PUBLIC_GITHUB_TOPICS,
                contract=contract,
            ),
        ),
        _check("readme_badge", SCRAPER_PACKAGE_URL in readme and SCRAPER_BADGE_URL in readme),
        _check("pypi_readme_badge", SCRAPER_PACKAGE_URL in pypi_readme and SCRAPER_BADGE_URL in pypi_readme),
    ]
    return {
        "query": github_ai_scraper_query(contract),
        "min_stars": contract.min_stars,
        "topics": list(contract.topics),
        "keywords": list(contract.keywords),
        "public_topics": list(PUBLIC_GITHUB_TOPICS),
        "checks": checks,
        "success": all(check["passed"] for check in checks),
    }


def run_check(
    *,
    repo_root: Path = REPO_ROOT,
    live: bool = False,
    print_only: bool = False,
    output: Path | None = None,
    work_dir: Path | None = None,
    max_results: int = 100,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    static_report = static_contract_report(repo_root=repo_root)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "repository": AGILAB_URL,
        "mode": "live" if live else "static",
        "print_only": print_only,
        "static": static_report,
        "success": static_report["success"],
    }

    if live:
        with _managed_work_dir(work_dir) as resolved_work_dir:
            live_plan = live_discovery_plan(resolved_work_dir, max_results=max_results)
            payload["live_plan"] = _redacted_plan(live_plan)
            if print_only:
                payload["success"] = static_report["success"]
            else:
                live_report = run_live_discovery(live_plan, timeout_seconds=timeout_seconds)
                payload["live"] = live_report
                payload["success"] = static_report["success"] and live_report["success"]
    elif print_only:
        payload["static_command"] = [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "python",
            "tools/github_ai_scraper_check.py",
            "--json",
        ]

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def live_discovery_plan(work_dir: Path, *, max_results: int = 100) -> dict[str, Any]:
    data_dir = work_dir / "data"
    output_dir = work_dir / "output"
    data_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    keywords_path = work_dir / "keywords.txt"
    keywords_path.write_text("\n".join(DEFAULT_CONTRACT.keywords) + "\n", encoding="utf-8")
    config_path = work_dir / "ai-scraper.yaml"
    export_path = work_dir / "export.json"
    config_text = _config_text(
        data_dir=data_dir,
        output_dir=output_dir,
        keywords_path=keywords_path,
        max_results=max_results,
        token=os.environ.get("GITHUB_TOKEN", ""),
    )
    config_path.write_text(config_text, encoding="utf-8")
    scrape_command = [
        "uvx",
        "--from",
        SCRAPER_PACKAGE,
        SCRAPER_EXECUTABLE,
        "-c",
        str(config_path),
        "scrape",
        "--no-progress",
        "--max-results",
        str(max_results),
    ]
    export_command = [
        "uvx",
        "--from",
        SCRAPER_PACKAGE,
        SCRAPER_EXECUTABLE,
        "-c",
        str(config_path),
        "db",
        "export",
        "--format",
        "json",
        "--output",
        str(export_path),
    ]
    return {
        "work_dir": work_dir,
        "config_path": config_path,
        "export_path": export_path,
        "config_text": config_text,
        "commands": [scrape_command, export_command],
    }


def run_live_discovery(plan: dict[str, Any], *, timeout_seconds: int = 120) -> dict[str, Any]:
    uvx = shutil.which("uvx")
    if uvx is None:
        return {"success": False, "error": "uvx is required for the live github-ai-scraper check"}

    command_reports = []
    env = _subprocess_env()
    for raw_command in plan["commands"]:
        command = [uvx if part == "uvx" else str(part) for part in raw_command]
        completed = subprocess.run(
            command,
            check=False,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        command_reports.append(_command_report(command, completed))
        if completed.returncode != 0:
            return {
                "success": False,
                "commands": command_reports,
                "error": f"command failed with exit code {completed.returncode}",
            }

    export_path = Path(plan["export_path"])
    try:
        exported = json.loads(export_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"success": False, "commands": command_reports, "error": f"failed to read export: {exc}"}
    repositories = exported.get("repositories", [])
    scraped_urls = {str(repo.get("url", "")) for repo in repositories if isinstance(repo, dict)}
    found = AGILAB_URL in scraped_urls
    return {
        "success": found,
        "commands": command_reports,
        "repository_count": len(repositories) if isinstance(repositories, list) else 0,
        "agilab_found": found,
        "export_path": export_path.as_posix(),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Run github-ai-scraper through uvx and inspect the export.")
    parser.add_argument("--print-only", action="store_true", help="Print planned static/live work without running live commands.")
    parser.add_argument("--json", action="store_true", help="Write the report as JSON to stdout.")
    parser.add_argument("--output", type=Path, help=f"Optional report path. Suggested default: {DEFAULT_OUTPUT}")
    parser.add_argument("--work-dir", type=Path, help="Optional live-run workspace. Defaults to a temporary directory.")
    parser.add_argument("--max-results", type=int, default=100, help="Maximum repositories requested from github-ai-scraper.")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout in seconds for each live scraper command.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload = run_check(
        live=args.live,
        print_only=args.print_only,
        output=args.output,
        work_dir=args.work_dir,
        max_results=args.max_results,
        timeout_seconds=args.timeout,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_human_report(payload)
    return 0 if payload.get("success") else 1


def _load_project(repo_root: Path) -> dict[str, Any]:
    with (repo_root / "pyproject.toml").open("rb") as stream:
        return tomllib.load(stream)["project"]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _check(name: str, passed: bool) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed)}


def _config_text(*, data_dir: Path, output_dir: Path, keywords_path: Path, max_results: int, token: str) -> str:
    lines = [
        "github:",
        f"  token: {token}",
        "  cache_ttl: 3600",
        "filter:",
        f"  min_stars: {DEFAULT_CONTRACT.min_stars}",
        "  keywords:",
        *[f"    - {keyword}" for keyword in DEFAULT_CONTRACT.keywords],
        "  topics:",
        *[f"    - {topic}" for topic in DEFAULT_CONTRACT.topics],
        "scrape:",
        f"  max_results: {max_results}",
        "  concurrency: 5",
        "database:",
        f"  path: {data_dir / 'ai_scraper.db'}",
        "keywords:",
        f"  file: {keywords_path}",
        "  max_keywords: 100",
        "output:",
        f"  dir: {output_dir}",
        "  filename: repositories.md",
        "",
    ]
    return "\n".join(lines)


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    if not env.get("SSL_CERT_FILE"):
        try:
            import certifi
        except ImportError:
            return env
        env["SSL_CERT_FILE"] = certifi.where()
        env.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    return env


def _command_report(command: Sequence[str], completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {
        "argv": list(command),
        "returncode": completed.returncode,
        "stdout_tail": _tail(completed.stdout),
        "stderr_tail": _tail(completed.stderr),
    }


def _tail(value: str, *, max_chars: int = 4000) -> str:
    return value[-max_chars:] if len(value) > max_chars else value


def _redacted_plan(plan: dict[str, Any]) -> dict[str, Any]:
    config_text = str(plan["config_text"])
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        config_text = config_text.replace(token, "***")
    return {
        "work_dir": Path(plan["work_dir"]).as_posix(),
        "config_path": Path(plan["config_path"]).as_posix(),
        "export_path": Path(plan["export_path"]).as_posix(),
        "config_text": config_text,
        "commands": plan["commands"],
    }


class _managed_work_dir:
    def __init__(self, path: Path | None):
        self._path = path
        self._tmp: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> Path:
        if self._path is not None:
            self._path.mkdir(parents=True, exist_ok=True)
            return self._path
        self._tmp = tempfile.TemporaryDirectory(prefix="agilab-github-ai-scraper-")
        return Path(self._tmp.name)

    def __exit__(self, *_exc: object) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()


def _print_human_report(payload: dict[str, Any]) -> None:
    status = "PASS" if payload.get("success") else "FAIL"
    print(f"{status} github-ai-scraper {payload['mode']} discoverability check")
    for check in payload["static"]["checks"]:
        marker = "ok" if check["passed"] else "fail"
        print(f"- {marker}: {check['name']}")
    if payload.get("live_plan"):
        print("Planned live commands:")
        for command in payload["live_plan"]["commands"]:
            print("  " + " ".join(map(str, command)))
    if payload.get("live"):
        live = payload["live"]
        print(f"- live agilab_found: {live.get('agilab_found')}")
        print(f"- live repository_count: {live.get('repository_count')}")


if __name__ == "__main__":
    raise SystemExit(main())
