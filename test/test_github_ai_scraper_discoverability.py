from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
import tomllib

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
README = REPO_ROOT / "README.md"
PYPI_README = REPO_ROOT / "README.pypi.md"
AGILAB_URL = "https://github.com/ThalesGroup/agilab"
LIVE_ENV = "AGILAB_GITHUB_AI_SCRAPER_LIVE"
SCRAPER_PACKAGE_URL = "https://pypi.org/project/github-ai-scraper/"
SCRAPER_BADGE_URL = "https://img.shields.io/badge/github--ai--scraper-discoverable-0F766E"

SCRAPER_MIN_STARS = 10
SCRAPER_TOPICS = (
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
SCRAPER_KEYWORDS = (
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


def _load_root_project() -> dict:
    with PYPROJECT.open("rb") as stream:
        return tomllib.load(stream)["project"]


def _github_ai_scraper_query() -> str:
    primary_topic = SCRAPER_TOPICS[0] if SCRAPER_TOPICS else "ai"
    return f"stars:>{SCRAPER_MIN_STARS} topic:{primary_topic}"


def _github_ai_scraper_would_keep_repo(*, name: str, description: str, topics: tuple[str, ...]) -> bool:
    """Mirror github-ai-scraper 0.1.2's topic/keyword AI filter."""

    text_to_check = f"{name} {description}".lower()
    repo_topics = {topic.lower() for topic in topics}

    if any(topic.lower() in repo_topics for topic in SCRAPER_TOPICS):
        return True

    for keyword in SCRAPER_KEYWORDS:
        keyword_lower = keyword.lower()
        keyword_normalized = keyword_lower.replace("-", " ")
        if keyword_normalized in text_to_check or keyword_lower in text_to_check:
            return True

    return False


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


def test_agilab_metadata_stays_discoverable_by_github_ai_scraper_contract() -> None:
    project = _load_root_project()
    keywords = {str(keyword).lower() for keyword in project["keywords"]}
    urls = project["urls"]

    assert _github_ai_scraper_query() == "stars:>10 topic:ai-engineering"
    assert {"ai", "ai-engineering", "machine-learning", "mlops", "ai-agents"} <= keywords
    assert {"reproducibility", "reproducible-research", "jupyter-notebook", "mlflow"} <= keywords
    assert urls["Repository"] == AGILAB_URL
    assert urls["Source"] == AGILAB_URL
    assert "reproducible ai/ml" in project["description"].lower()
    assert "ai-engineering" in PUBLIC_GITHUB_TOPICS
    assert "ai" in PUBLIC_GITHUB_TOPICS
    assert "claude" not in PUBLIC_GITHUB_TOPICS

    assert _github_ai_scraper_would_keep_repo(
        name="agilab",
        description="Open-source platform for reproducible AI/ML workflows, from local experimentation to distributed workers and long-lived services.",
        topics=PUBLIC_GITHUB_TOPICS,
    )


def test_scraper_discoverability_badge_is_publicly_visible() -> None:
    readme = README.read_text(encoding="utf-8")
    pypi_readme = PYPI_README.read_text(encoding="utf-8")

    for text in (readme, pypi_readme):
        assert SCRAPER_PACKAGE_URL in text
        assert SCRAPER_BADGE_URL in text
        assert "github--ai--scraper-discoverable" in text


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get(LIVE_ENV) != "1",
    reason=f"set {LIVE_ENV}=1 to run the live github-ai-scraper discovery check",
)
def test_live_github_ai_scraper_collects_agilab(tmp_path: Path) -> None:
    uvx = shutil.which("uvx")
    if uvx is None:
        pytest.skip("uvx is required for the live github-ai-scraper check")

    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    output_dir.mkdir()
    config_path = tmp_path / "ai-scraper.yaml"
    export_path = tmp_path / "export.json"
    config_path.write_text(
        "\n".join(
            [
                "github:",
                f"  token: {os.environ.get('GITHUB_TOKEN', '')}",
                "  cache_ttl: 3600",
                "filter:",
                f"  min_stars: {SCRAPER_MIN_STARS}",
                "  keywords:",
                *[f"    - {keyword}" for keyword in SCRAPER_KEYWORDS],
                "  topics:",
                *[f"    - {topic}" for topic in SCRAPER_TOPICS],
                "scrape:",
                "  max_results: 100",
                "  concurrency: 5",
                "database:",
                f"  path: {data_dir / 'ai_scraper.db'}",
                "keywords:",
                f"  file: {tmp_path / 'keywords.txt'}",
                "  max_keywords: 100",
                "output:",
                f"  dir: {output_dir}",
                "  filename: repositories.md",
                "",
            ]
        ),
        encoding="utf-8",
    )

    subprocess.run(
        [
            uvx,
            "--from",
            "github-ai-scraper",
            "ai-scraper",
            "-c",
            str(config_path),
            "scrape",
            "--no-progress",
            "--max-results",
            "100",
        ],
        check=True,
        env=_subprocess_env(),
        text=True,
        timeout=120,
    )
    subprocess.run(
        [
            uvx,
            "--from",
            "github-ai-scraper",
            "ai-scraper",
            "-c",
            str(config_path),
            "db",
            "export",
            "--format",
            "json",
            "--output",
            str(export_path),
        ],
        check=True,
        env=_subprocess_env(),
        text=True,
        timeout=60,
    )

    payload = json.loads(export_path.read_text(encoding="utf-8"))
    scraped_urls = {repo["url"] for repo in payload["repositories"]}
    assert AGILAB_URL in scraped_urls
