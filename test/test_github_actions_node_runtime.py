from __future__ import annotations

import re
from pathlib import Path

import yaml

AUTOMATION_GLOBS = ("*.yml", "*.yaml")
AUTOMATION_DIRS = (Path(".github/workflows"), Path(".github/actions"))
SETUP_UV_SHA = "c771a70e6277c0a99b617c7a806ffedaca235ff9"

NODE24_COMPATIBLE_ACTIONS = {
    "actions/cache/restore": {"v5"},
    "actions/cache/save": {"v5"},
    "actions/checkout": {"v5", "v6", "v7"},
    "actions/setup-python": {"v7"},
    "actions/upload-artifact": {"v6", "v7"},
    "actions/download-artifact": {"v7", "v8"},
    "actions/configure-pages": {"v6"},
    "actions/upload-pages-artifact": {"v5"},
    "actions/deploy-pages": {"v5"},
    "actions/github-script": {"v8", "v9"},
    "astral-sh/setup-uv": {"v7", "v8", "v9"},
    "codecov/codecov-action": {"v6"},
}


def _automation_files() -> list[Path]:
    files: list[Path] = []
    for directory in AUTOMATION_DIRS:
        for pattern in AUTOMATION_GLOBS:
            files.extend(directory.rglob(pattern))
    return sorted(files)


def _step_mappings(value: object):
    if isinstance(value, dict):
        if "uses" in value:
            yield value
        for child in value.values():
            yield from _step_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _step_mappings(child)


def test_github_actions_use_node24_compatible_major_versions() -> None:
    failures: list[str] = []
    uses_pattern = re.compile(r"uses:\s+([\w.-]+/[\w.-]+(?:/[\w.-]+)*)@([^\s#]+)")
    pinned_sha_pattern = re.compile(r"^[0-9a-f]{40}$")

    for workflow in _automation_files():
        for line_no, line in enumerate(
            workflow.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = uses_pattern.search(line)
            if not match:
                continue
            action, ref = match.groups()
            allowed_refs = NODE24_COMPATIBLE_ACTIONS.get(action)
            if allowed_refs is None:
                continue
            effective_ref = ref
            if pinned_sha_pattern.fullmatch(ref):
                comment_match = re.search(r"#\s*(v\d+)\b", line)
                if not comment_match:
                    failures.append(
                        f"{workflow}:{line_no}: {action}@{ref} should include a '# vN' major comment"
                    )
                    continue
                effective_ref = comment_match.group(1)
            if effective_ref not in allowed_refs:
                failures.append(
                    f"{workflow}:{line_no}: {action}@{effective_ref} should use one of {sorted(allowed_refs)}"
                )

    assert failures == []


def test_setup_uv_v9_preserves_cache_pruning() -> None:
    failures: list[str] = []
    setup_steps = 0
    expected_use = f"astral-sh/setup-uv@{SETUP_UV_SHA}"

    for automation_file in _automation_files():
        document = yaml.safe_load(automation_file.read_text(encoding="utf-8"))
        for step in _step_mappings(document):
            uses = str(step["uses"])
            if not uses.startswith("astral-sh/setup-uv@"):
                continue
            setup_steps += 1
            if uses != expected_use:
                failures.append(
                    f"{automation_file}: expected {expected_use}, found {uses}"
                )
            if step.get("with", {}).get("prune-cache") is not True:
                failures.append(
                    f"{automation_file}: setup-uv must set prune-cache: true"
                )

    assert setup_steps > 0
    assert failures == []
