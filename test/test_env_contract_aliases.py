from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
THIS_FILE = Path(__file__).resolve()
SCAN_TARGETS = (
    "install.sh",
    "install.ps1",
    "README.md",
    "AGENTS.md",
    "src",
    "tools",
    "test",
    "docs/source",
    ".claude/skills",
    ".codex/skills",
)
RETIRED_ENV_SURFACES = (
    "AGI_LOCAL_DIR",
    "AGI_SHARE_DIR",
    "OPENAI_API_BASE",
    "AGILAB_APP",
    "AGI_ROOT",
    "--agi-share-dir",
    "AgiShareDir",
    "AgiLocalDir",
)


def _contains_retired_surface(text: str, retired: str) -> bool:
    if retired.startswith("--"):
        return retired in text
    pattern = rf"(?<![A-Za-z0-9_]){re.escape(retired)}(?![A-Za-z0-9_])"
    return re.search(pattern, text) is not None


def _iter_text_files(root: Path):
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        if path == THIS_FILE or not path.is_file():
            continue
        if any(part in {".git", ".venv", "build", "__pycache__", ".pytest_cache"} for part in path.parts):
            continue
        yield path


def test_retired_environment_aliases_do_not_reappear() -> None:
    findings: list[str] = []
    for target in SCAN_TARGETS:
        root = REPO_ROOT / target
        if not root.exists():
            continue
        for path in _iter_text_files(root):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for retired in RETIRED_ENV_SURFACES:
                if _contains_retired_surface(text, retired):
                    findings.append(f"{path.relative_to(REPO_ROOT)}: contains {retired}")

    assert findings == []


def test_agents_cluster_recovery_does_not_pin_lan_worker_ip() -> None:
    agents_text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "tools/cluster_flight_validation.py" in agents_text
    assert "--discover-lan" in agents_text
    assert re.search(r"\b192\.168\.20\.\d+\b", agents_text) is None
