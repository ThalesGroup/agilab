#!/usr/bin/env python3
"""Fail locally when coverage badge SVGs are stale.

The coverage workflow regenerates badges from Cobertura XML artifacts and then
fails if ``badges/`` differs. This local guard mirrors that final gate and can
also require XML inputs to be newer than coverage-sensitive files changed since
the upstream branch.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]

COVERAGE_COMPONENTS = ("agi-env", "agi-node", "agi-cluster", "agi-gui")
AGGREGATE_COMPONENTS = ("agi-core", "agilab")
ALL_COMPONENTS = (*COVERAGE_COMPONENTS, *AGGREGATE_COMPONENTS)
CORE_COMPONENTS = {"agi-env", "agi-node", "agi-cluster"}

COMPONENT_XML = {
    "agi-env": "coverage-agi-env.xml",
    "agi-node": "coverage-agi-node.xml",
    "agi-cluster": "coverage-agi-cluster.xml",
    "agi-gui": "coverage-agi-gui.xml",
}

COVERAGE_TOOLING_TESTS = {
    "test/test_coverage_badge_guard.py",
    "test/test_generate_component_coverage_badges.py",
    "test/test_coverage_workflow.py",
}
NON_GUI_ROOT_TESTS = {
    *COVERAGE_TOOLING_TESTS,
    "test/conftest.py",
    "test/test_connector_registry.py",
    "test/test_beta_readiness.py",
    "test/test_public_demo_links.py",
    "test/test_pypi_distribution_state.py",
    "test/test_pypi_publish.py",
    "test/test_pypi_publish_workflow.py",
    "test/test_impact_validate.py",
    "test/test_workflow_parity.py",
}


def _is_workflow_policy_test(path: str) -> bool:
    return path.startswith("test/test_") and path.endswith("_workflow.py")


class GuardError(RuntimeError):
    """Coverage badge guard failure."""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        help=(
            "Git ref used to discover changed files with --changed-only. "
            "Defaults to the current branch upstream, then origin/main."
        ),
    )
    parser.add_argument(
        "--changed-only",
        action="store_true",
        help="Only check badge components affected by files changed since --base.",
    )
    parser.add_argument(
        "--components",
        nargs="+",
        choices=ALL_COMPONENTS,
        help="Explicit component badges to check. Aggregates are added automatically.",
    )
    parser.add_argument(
        "--require-fresh-xml",
        action="store_true",
        help="Require component XML files to be newer than changed files that affect them.",
    )
    parser.add_argument(
        "--allow-badge-only",
        action="store_true",
        help=(
            "Allow a push that only changes coverage badge SVGs. Prefer this only "
            "when the badges were regenerated from current CI coverage artifacts."
        ),
    )
    parser.add_argument(
        "--include-untracked",
        action="store_true",
        help="Include untracked files when discovering changed files.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a compact JSON-like diagnostic payload for automation.",
    )
    return parser


def _run_git(args: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and proc.returncode != 0:
        raise GuardError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc


def _default_base() -> str:
    upstream = _run_git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        check=False,
    )
    if upstream.returncode == 0 and upstream.stdout.strip():
        return upstream.stdout.strip()
    return "origin/main"


def _normalize_paths(paths: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        path = raw.strip()
        if not path or path in seen:
            continue
        normalized.append(path)
        seen.add(path)
    return sorted(normalized)


def changed_files(base: str | None, *, include_untracked: bool = False) -> list[str]:
    resolved_base = base or _default_base()
    changed: list[str] = []
    diff_base = _run_git(["diff", "--name-only", "--diff-filter=ACMR", f"{resolved_base}...HEAD"], check=False)
    if diff_base.returncode == 0:
        changed.extend(diff_base.stdout.splitlines())
    else:
        diff_base = _run_git(["diff", "--name-only", "--diff-filter=ACMR", resolved_base], check=False)
        if diff_base.returncode == 0:
            changed.extend(diff_base.stdout.splitlines())

    changed.extend(_run_git(["diff", "--name-only", "--diff-filter=ACMR"], check=False).stdout.splitlines())
    changed.extend(_run_git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"], check=False).stdout.splitlines())
    if include_untracked:
        changed.extend(_run_git(["ls-files", "--others", "--exclude-standard"], check=False).stdout.splitlines())
    return _normalize_paths(changed)


def _is_gui_coverage_path(path: str) -> bool:
    if path in NON_GUI_ROOT_TESTS or _is_workflow_policy_test(path):
        return False
    if path == "pyproject.toml" or path.endswith("/pyproject.toml"):
        return False
    if path.startswith("src/agilab/core/"):
        return False
    if path.startswith("src/agilab/test/"):
        return True
    if path.startswith("src/agilab/"):
        return True
    if path.startswith("test/"):
        return True
    return path == ".coveragerc.agi-gui"


def changed_coverage_components(paths: Sequence[str]) -> dict[str, list[str]]:
    by_component: dict[str, list[str]] = {component: [] for component in COVERAGE_COMPONENTS}
    for path in paths:
        if path == "pyproject.toml" or path.endswith("/pyproject.toml"):
            continue
        if path.startswith("src/agilab/core/agi-env/") or path == ".coveragerc.agi-env":
            by_component["agi-env"].append(path)
        if path.startswith("src/agilab/core/agi-node/"):
            by_component["agi-node"].append(path)
        if path.startswith("src/agilab/core/agi-cluster/"):
            by_component["agi-cluster"].append(path)
        if path.startswith("src/agilab/core/test/"):
            by_component["agi-node"].append(path)
            by_component["agi-cluster"].append(path)
        if _is_gui_coverage_path(path):
            by_component["agi-gui"].append(path)
        if (
            path == "tools/generate_component_coverage_badges.py"
            or path.startswith("badges/coverage-")
        ):
            for component in COVERAGE_COMPONENTS:
                by_component[component].append(path)
    return {component: _normalize_paths(files) for component, files in by_component.items() if files}


def _is_coverage_badge_output(path: str) -> bool:
    return path.startswith("badges/coverage-") and path.endswith(".svg")


def expand_with_aggregates(components: Iterable[str]) -> list[str]:
    selected = set(components)
    if selected & CORE_COMPONENTS:
        selected.add("agi-core")
    if selected & set(COVERAGE_COMPONENTS):
        selected.add("agilab")
    return [component for component in ALL_COMPONENTS if component in selected]


def _load_badge_generator() -> ModuleType:
    module_path = REPO_ROOT / "tools" / "generate_component_coverage_badges.py"
    spec = importlib.util.spec_from_file_location("coverage_badge_generator", module_path)
    if spec is None or spec.loader is None:
        raise GuardError(f"Unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _expected_svg(generator: ModuleType, component: str) -> str:
    config = generator.COMPONENTS[component]
    combined_xml = REPO_ROOT / "coverage-agilab.combined.xml"
    percent = None
    if "aggregate" in config:
        policy = str(config.get("aggregate_policy", "weighted"))
        percent = generator.compute_aggregate_percent(config["aggregate"], combined_xml, policy=policy)
    else:
        counts = generator.resolve_component_counts(component, combined_xml)
        if counts is not None:
            covered, total = counts
            percent = covered * 100.0 / total
    if percent is None:
        raise GuardError(f"Missing coverage XML data for {component}")
    value = generator.format_percent(percent)
    return generator.render_badge(config["label"], value, generator.badge_color(percent))


def _badge_path(generator: ModuleType, component: str) -> Path:
    return Path(generator.COMPONENTS[component]["badge"])


def stale_xml_messages(
    changed_by_component: dict[str, list[str]],
    *,
    repo_root: Path = REPO_ROOT,
) -> list[str]:
    messages: list[str] = []
    now = time.time()
    for component, paths in sorted(changed_by_component.items()):
        freshness_paths = [path for path in paths if not _is_coverage_badge_output(path)]
        if not freshness_paths:
            continue
        xml_path = repo_root / COMPONENT_XML[component]
        if not xml_path.exists():
            messages.append(f"{component}: missing {xml_path.relative_to(repo_root)}")
            continue
        xml_mtime = xml_path.stat().st_mtime
        newest_path: str | None = None
        newest_mtime = 0.0
        for path in freshness_paths:
            candidate = repo_root / path
            if not candidate.exists():
                continue
            candidate_mtime = candidate.stat().st_mtime
            if candidate_mtime > newest_mtime:
                newest_path = path
                newest_mtime = candidate_mtime
        if newest_path and xml_mtime + 1e-6 < newest_mtime:
            messages.append(
                f"{component}: {xml_path.relative_to(repo_root)} is older than changed input {newest_path}"
            )
        elif xml_mtime > now + 60:
            messages.append(f"{component}: {xml_path.relative_to(repo_root)} has a future timestamp")
    return messages


def badge_only_update_messages(
    changed_by_component: dict[str, list[str]],
    *,
    allow: bool = False,
) -> list[str]:
    if allow:
        return []

    badge_paths = sorted(
        {
            path
            for paths in changed_by_component.values()
            for path in paths
            if _is_coverage_badge_output(path)
        }
    )
    if not badge_paths:
        return []

    non_badge_coverage_paths = sorted(
        {
            path
            for paths in changed_by_component.values()
            for path in paths
            if not _is_coverage_badge_output(path)
        }
    )
    if non_badge_coverage_paths:
        return []

    return [
        (
            "badge-only coverage update blocked: local coverage XML can diverge from CI. "
            "Include the source/test/workflow change that produced the new coverage, or set "
            "AGILAB_ALLOW_BADGE_ONLY_UPDATE=1 only after regenerating from current CI artifacts "
            f"({', '.join(badge_paths)})"
        )
    ]


def badge_mismatch_messages(components: Sequence[str]) -> list[str]:
    generator = _load_badge_generator()
    messages: list[str] = []
    for component in components:
        badge_path = _badge_path(generator, component)
        if not badge_path.exists():
            messages.append(f"{component}: missing {badge_path.relative_to(REPO_ROOT)}")
            continue
        expected = _expected_svg(generator, component)
        actual = badge_path.read_text(encoding="utf-8")
        if actual != expected:
            messages.append(f"{component}: stale {badge_path.relative_to(REPO_ROOT)}")
    return messages


def _guard_commands(components: Sequence[str]) -> list[str]:
    component_flags = " ".join(components)
    commands: list[str] = []
    if "agi-env" in components:
        commands.append("uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile agi-env")
    if "agi-node" in components or "agi-cluster" in components:
        commands.append(
            "uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile agi-core-combined"
        )
    if "agi-gui" in components:
        commands.append("uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile agi-gui")
    if components:
        commands.append(
            "uv --preview-features extra-build-dependencies run python "
            f"tools/generate_component_coverage_badges.py --components {component_flags}"
        )
    else:
        commands.append(
            "uv --preview-features extra-build-dependencies run python tools/generate_component_coverage_badges.py"
        )
    commands.append("git add badges/coverage-*.svg")
    return commands


def run_guard(args: argparse.Namespace) -> tuple[bool, list[str], list[str], list[str]]:
    paths = changed_files(args.base, include_untracked=args.include_untracked) if args.changed_only else []
    changed_by_component = changed_coverage_components(paths)
    if args.components:
        components = expand_with_aggregates(args.components)
    elif args.changed_only:
        components = expand_with_aggregates(changed_by_component)
    else:
        components = list(ALL_COMPONENTS)

    if args.changed_only and not components:
        return True, paths, components, ["No coverage-sensitive changed files; coverage badge guard skipped."]

    failures: list[str] = []
    if args.require_fresh_xml:
        failures.extend(stale_xml_messages(changed_by_component))
    allow_badge_only = args.allow_badge_only or os.environ.get("AGILAB_ALLOW_BADGE_ONLY_UPDATE") == "1"
    failures.extend(badge_only_update_messages(changed_by_component, allow=allow_badge_only))
    failures.extend(badge_mismatch_messages(components))
    return not failures, paths, components, failures


def _render_result(success: bool, paths: list[str], components: list[str], messages: list[str]) -> str:
    if success:
        checked = ", ".join(components) if components else "none"
        return "\n".join([*messages, f"Coverage badge guard passed for: {checked}"])

    lines = [
        "Coverage badge guard failed.",
        "Changed files considered:",
        *(f"- {path}" for path in paths[:40]),
        "Affected badge components:",
        *(f"- {component}" for component in components),
        "Failures:",
        *(f"- {message}" for message in messages),
        "Refresh locally before pushing:",
        *(_guard_commands(components)),
        "Set AGILAB_SKIP_LOCAL_GUARDS=1 only when intentionally bypassing this local guard.",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        success, paths, components, messages = run_guard(args)
    except GuardError as exc:
        print(f"coverage_badge_guard: {exc}", file=sys.stderr)
        return 2

    if args.json:
        import json

        print(
            json.dumps(
                {
                    "success": success,
                    "changed_files": paths,
                    "components": components,
                    "messages": messages,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        output = _render_result(success, paths, components, messages)
        if output:
            print(output)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
