from __future__ import annotations

import re
from pathlib import Path


WORKFLOW_GLOBS = ("*.yml", "*.yaml")
WORKFLOW_DIR = Path(".github/workflows")

NODE24_COMPATIBLE_ACTIONS = {
    "actions/checkout": {"v5", "v6"},
    "actions/setup-python": {"v6"},
    "actions/upload-artifact": {"v6", "v7"},
    "actions/download-artifact": {"v7", "v8"},
    "actions/configure-pages": {"v6"},
    "actions/upload-pages-artifact": {"v5"},
    "actions/deploy-pages": {"v5"},
    "actions/github-script": {"v8"},
    "astral-sh/setup-uv": {"v7"},
    "codecov/codecov-action": {"v6"},
}


def _workflow_files() -> list[Path]:
    files: list[Path] = []
    for pattern in WORKFLOW_GLOBS:
        files.extend(WORKFLOW_DIR.glob(pattern))
    return sorted(files)


def test_github_actions_use_node24_compatible_major_versions() -> None:
    failures: list[str] = []
    uses_pattern = re.compile(r"uses:\s+([\w.-]+/[\w.-]+)@([^\s#]+)")

    for workflow in _workflow_files():
        for line_no, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), start=1):
            match = uses_pattern.search(line)
            if not match:
                continue
            action, ref = match.groups()
            allowed_refs = NODE24_COMPATIBLE_ACTIONS.get(action)
            if allowed_refs is None:
                continue
            if ref not in allowed_refs:
                failures.append(
                    f"{workflow}:{line_no}: {action}@{ref} should use one of {sorted(allowed_refs)}"
                )

    assert failures == []
