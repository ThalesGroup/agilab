#!/usr/bin/env python3
"""Analyze changed files and suggest AGILAB-specific validation gates."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]

SHARED_CORE_PREFIXES = (
    "src/agilab/core/agi-env/",
    "src/agilab/core/agi-node/",
    "src/agilab/core/agi-cluster/",
    "src/agilab/core/agi-core/",
)
SHARED_TOOLING_PATHS = {
    "install.sh",
    "src/agilab/install_apps.sh",
    "src/agilab/apps/install.py",
}
SHELL_CHECK_FILES = {"install.sh", "src/agilab/install_apps.sh"}
RUNCONFIG_PREFIXES = (".idea/runConfigurations/", "tools/run_configs/")
SKILL_PREFIXES = (".claude/skills/", ".codex/skills/")
BADGE_PATH_PREFIXES = ("badges/",)
DOCS_PREFIXES = ("docs/source/",)
GUI_PREFIXES = (
    "src/agilab/apps-pages/",
    "src/agilab/lib/",
    "src/agilab/pages/",
)
GUI_TOP_LEVEL_PREFIXES = (
    "src/agilab/orchestrate_",
    "src/agilab/pipeline_",
    "src/agilab/main_page.py",
)
TEST_PREFIXES = (
    "test/",
    "src/agilab/test/",
    "src/agilab/lib/agi-gui/test/",
    "src/agilab/core/test/",
    "src/agilab/core/agi-env/test/",
)
NON_GUI_ROOT_TESTS = {
    "test/test_coverage_badge_guard.py",
    "test/test_coverage_workflow.py",
    "test/test_generate_component_coverage_badges.py",
    "test/test_impact_validate.py",
    "test/test_workflow_parity.py",
}


@dataclass
class Action:
    key: str
    summary: str
    commands: list[str] = field(default_factory=list)


@dataclass
class RiskZone:
    key: str
    summary: str
    files: list[str] = field(default_factory=list)


@dataclass
class ImpactReport:
    files: list[str]
    overall_risk: str
    risk_zones: list[RiskZone]
    push_gates: list[Action]
    artifact_actions: list[Action]
    required_validations: list[Action]
    guessed_tests: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "files": self.files,
            "overall_risk": self.overall_risk,
            "risk_zones": [asdict(zone) for zone in self.risk_zones],
            "push_gates": [asdict(action) for action in self.push_gates],
            "artifact_actions": [asdict(action) for action in self.artifact_actions],
            "required_validations": [asdict(action) for action in self.required_validations],
            "guessed_tests": self.guessed_tests,
        }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect changed files and report AGILAB-specific risk zones, push gates, "
            "artifact refreshes, and suggested validation commands."
        )
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--files", nargs="+", help="Explicit repo-relative files to analyze.")
    group.add_argument(
        "--staged",
        action="store_true",
        help="Analyze staged files from `git diff --cached --name-only`.",
    )
    parser.add_argument(
        "--base",
        default="origin/main",
        help=(
            "Git ref to diff against when --files/--staged are not provided. "
            "Default: origin/main."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human summary.",
    )
    return parser


def _run_git(args: Sequence[str]) -> list[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _collect_changed_files(args: argparse.Namespace) -> list[str]:
    if args.files:
        return _normalize_paths(args.files)
    if args.staged:
        return _normalize_paths(_run_git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"]))
    tracked = _run_git(["diff", "--name-only", "--diff-filter=ACMR", args.base])
    untracked = _run_git(["ls-files", "--others", "--exclude-standard"])
    return _normalize_paths([*tracked, *untracked])


def _normalize_paths(paths: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        candidate = raw.strip()
        if not candidate:
            continue
        normalized_path = Path(candidate)
        if normalized_path.is_absolute():
            try:
                candidate = str(normalized_path.resolve().relative_to(REPO_ROOT))
            except ValueError:
                candidate = normalized_path.name
        else:
            candidate = str(normalized_path.as_posix())
        if candidate not in seen:
            normalized.append(candidate)
            seen.add(candidate)
    return sorted(normalized)


def _matches_prefix(path: str, prefixes: Sequence[str]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)


def _is_shared_core(path: str) -> bool:
    return _matches_prefix(path, SHARED_CORE_PREFIXES) or path in SHARED_TOOLING_PATHS


def _is_gui_file(path: str) -> bool:
    return _matches_prefix(path, GUI_PREFIXES) or any(path.startswith(prefix) for prefix in GUI_TOP_LEVEL_PREFIXES)


def _is_workflow_policy_test(path: str) -> bool:
    return path.startswith("test/test_") and path.endswith("_workflow.py")


def _is_non_gui_root_test(path: str) -> bool:
    return path in NON_GUI_ROOT_TESTS or _is_workflow_policy_test(path)


def _risk_zones(paths: list[str]) -> list[RiskZone]:
    zones: list[RiskZone] = []
    builders = (
        ("shared-core", "Protected shared core or shared tooling touched.", _is_shared_core),
        ("installer", "Installer or deployment contract touched.", lambda p: p in SHELL_CHECK_FILES or p == "src/agilab/apps/install.py"),
        ("runconfig", "Run configuration or generated launcher touched.", lambda p: _matches_prefix(p, RUNCONFIG_PREFIXES)),
        ("skills", "Shared agent skill trees touched.", lambda p: _matches_prefix(p, SKILL_PREFIXES)),
        ("badges", "Coverage badge inputs or generated badge artifacts touched.", lambda p: _matches_prefix(p, BADGE_PATH_PREFIXES) or "coverage-" in Path(p).name or p == "tools/generate_component_coverage_badges.py"),
        ("gui", "GUI/page/runtime surface touched.", _is_gui_file),
        ("docs", "Docs source touched.", lambda p: _matches_prefix(p, DOCS_PREFIXES)),
    )
    for key, summary, predicate in builders:
        matched = [path for path in paths if predicate(path)]
        if matched:
            zones.append(RiskZone(key=key, summary=summary, files=matched))
    return zones


def _guess_tests_for_file(path: str) -> list[str]:
    repo = REPO_ROOT
    workflow_tests = {
        ".github/workflows/ci.yml": "test/test_ci_workflow.py",
        ".github/workflows/coverage.yml": "test/test_coverage_workflow.py",
        ".github/workflows/docs-source-guard.yaml": "test/test_ci_workflow.py",
        ".github/workflows/docs-publish.yaml": "test/test_ci_workflow.py",
        ".github/workflows/ui-robot-matrix.yml": "test/test_ci_workflow.py",
    }
    if path in workflow_tests:
        return [workflow_tests[path]]

    candidate_tests: list[Path] = []
    rel = Path(path)
    stem = rel.stem

    if _matches_prefix(path, TEST_PREFIXES):
        if (repo / path).exists():
            return [path]
        return []

    if path.startswith("src/agilab/apps-pages/"):
        parts = rel.parts
        if len(parts) >= 4:
            page_name = parts[3]
            candidate_tests.extend(sorted((repo / "test").glob(f"test_{page_name}.py")))
            candidate_tests.extend(sorted((repo / "test").glob(f"test_{page_name}_*.py")))

    if path.startswith("src/agilab/pages/"):
        ui_pages = repo / "test" / "test_ui_pages.py"
        if ui_pages.exists():
            candidate_tests.append(ui_pages)

    if path.startswith("src/agilab/apps/"):
        parts = rel.parts
        project_root: Path | None = None
        for index, part in enumerate(parts):
            if part.endswith("_project"):
                project_root = Path(*parts[: index + 1])
                break
        if project_root is not None:
            app_test = repo / project_root / "app_test.py"
            if app_test.exists():
                candidate_tests.append(app_test)

    for root in (
        repo / "test",
        repo / "src" / "agilab" / "test",
        repo / "src" / "agilab" / "core" / "test",
        repo / "src" / "agilab" / "core" / "agi-env" / "test",
    ):
        candidate_tests.extend(sorted(root.glob(f"test_{stem}.py")))
        candidate_tests.extend(sorted(root.glob(f"test_{stem}_*.py")))

    normalized = []
    seen: set[str] = set()
    for candidate in candidate_tests:
        if not candidate.exists():
            continue
        relative = str(candidate.relative_to(repo))
        if relative not in seen:
            normalized.append(relative)
            seen.add(relative)
    return normalized


def _guess_targeted_tests(paths: list[str]) -> list[str]:
    guessed: list[str] = []
    seen: set[str] = set()
    for path in paths:
        for candidate in _guess_tests_for_file(path):
            if candidate not in seen:
                guessed.append(candidate)
                seen.add(candidate)
    return guessed


def _component_hints(paths: list[str]) -> list[str]:
    components: list[str] = []
    seen: set[str] = set()
    for path in paths:
        hints = []
        if path.startswith("src/agilab/core/agi-env/") or "coverage-agi-env" in path:
            hints.append("agi-env")
        if path.startswith("src/agilab/core/agi-node/") or "coverage-agi-node" in path:
            hints.append("agi-node")
        if path.startswith("src/agilab/core/agi-cluster/") or "coverage-agi-cluster" in path:
            hints.append("agi-cluster")
        if (
            _is_gui_file(path)
            or path.startswith("src/agilab/test/")
            or (path.startswith("test/") and not _is_non_gui_root_test(path))
            or "coverage-agi-gui" in path
            or path == "tools/generate_component_coverage_badges.py"
        ):
            hints.append("agi-gui")
        if path == "tools/generate_component_coverage_badges.py":
            hints.extend(["agi-env", "agi-node", "agi-cluster"])
        for hint in hints:
            if hint not in seen:
                components.append(hint)
                seen.add(hint)
    return components


def _skill_names(paths: list[str]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for path in paths:
        rel = Path(path)
        if len(rel.parts) >= 3 and rel.parts[0] in {".claude", ".codex"} and rel.parts[1] == "skills":
            name = rel.parts[2]
            if name.startswith(".") or name == "README.md":
                continue
            if name not in seen:
                names.append(name)
                seen.add(name)
    return names


def _dedupe_actions(actions: Iterable[Action]) -> list[Action]:
    merged: dict[str, Action] = {}
    for action in actions:
        current = merged.get(action.key)
        if current is None:
            merged[action.key] = Action(action.key, action.summary, list(action.commands))
            continue
        for command in action.commands:
            if command not in current.commands:
                current.commands.append(command)
    return list(merged.values())


def analyze_paths(paths: list[str]) -> ImpactReport:
    zones = _risk_zones(paths)
    guessed_tests = _guess_targeted_tests(paths)
    actions: list[Action] = []
    artifacts: list[Action] = []
    push_gates: list[Action] = []

    if any(_is_shared_core(path) for path in paths):
        push_gates.append(
            Action(
                key="shared-core-approval",
                summary="Shared core or shared deploy/build tooling was touched; require explicit approval and blast-radius review.",
            )
        )
        if any(path.startswith("src/agilab/core/agi-env/") for path in paths):
            actions.append(
                Action(
                    key="agi-env-tests",
                    summary="Run the focused agi-env test slice.",
                    commands=[
                        "uv --preview-features extra-build-dependencies run --no-sync pytest src/agilab/core/agi-env/test"
                    ],
                )
            )
        if any(
            path.startswith(prefix)
            for path in paths
            for prefix in (
                "src/agilab/core/agi-node/",
                "src/agilab/core/agi-cluster/",
                "src/agilab/core/agi-core/",
            )
        ):
            actions.append(
                Action(
                    key="core-tests",
                    summary="Run the focused shared-core dispatcher/cluster test slice.",
                    commands=[
                        "uv --preview-features extra-build-dependencies run --no-sync pytest src/agilab/core/test"
                    ],
                )
            )

    if any(path in SHELL_CHECK_FILES for path in paths):
        actions.append(
            Action(
                key="shell-syntax",
                summary="Validate installer shell syntax before broader repros.",
                commands=["bash -n install.sh src/agilab/install_apps.sh"],
            )
        )

    if any(path == "src/agilab/apps/install.py" for path in paths):
        push_gates.append(
            Action(
                key="install-contract",
                summary="Installer entrypoint touched; reproduce both plain sync and the real AGILAB install path before push.",
            )
        )
        actions.append(
            Action(
                key="install-contract-check",
                summary="Compare the source app and copied worker manifests before treating the failure as app-local.",
                commands=[
                    "uv --preview-features extra-build-dependencies run python tools/install_contract_check.py --app-path <app-project-path> --worker-copy <copied-worker-path>"
                ],
            )
        )
        actions.append(
            Action(
                key="workflow-parity-installer",
                summary="Run the installer workflow parity profile before push.",
                commands=[
                    "uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile installer --app-path <app-project-path> --worker-copy <copied-worker-path>"
                ],
            )
        )
        actions.append(
            Action(
                key="install-contract-repro",
                summary="Run the installer contract repro commands for an affected app.",
                commands=[
                    "uv sync --project <app-project-path>",
                    "uv --preview-features extra-build-dependencies run python src/agilab/apps/install.py <app-project-path> --verbose 1",
                ],
            )
        )

    if guessed_tests:
        actions.append(
            Action(
                key="targeted-pytest",
                summary="Run the narrow pytest slice inferred from the touched modules.",
                commands=[
                    "uv --preview-features extra-build-dependencies run pytest -q "
                    + " ".join(guessed_tests[:8])
                ],
            )
        )

    if any(_matches_prefix(path, RUNCONFIG_PREFIXES) for path in paths):
        artifacts.append(
            Action(
                key="runconfig-regenerate",
                summary="Regenerate CLI wrappers for PyCharm run configurations.",
                commands=[
                    "uv --preview-features extra-build-dependencies run python tools/generate_runconfig_scripts.py"
                ],
            )
        )

    skill_names = _skill_names(paths)
    if any(_matches_prefix(path, SKILL_PREFIXES) for path in paths):
        commands: list[str] = []
        if skill_names:
            commands.append(
                "python3 tools/sync_agent_skills.py --skills " + " ".join(skill_names)
            )
        commands.extend(
            [
                "python3 tools/codex_skills.py --root .codex/skills validate --strict",
                "python3 tools/codex_skills.py --root .codex/skills generate",
            ]
        )
        artifacts.append(
            Action(
                key="skill-sync",
                summary="Sync the touched shared skills into the repo Codex mirror and rebuild the index.",
                commands=commands,
            )
        )
        artifacts.append(
            Action(
                key="workflow-parity-skills",
                summary="Run the local skills workflow parity profile.",
                commands=[
                    "uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile skills"
                ],
            )
        )

    components = _component_hints(paths)
    if components:
        artifacts.append(
            Action(
                key="coverage-badge-guard",
                summary="Run the local coverage badge guard before push so badge drift is caught before GitHub Actions.",
                commands=[
                    "uv --preview-features extra-build-dependencies run python tools/coverage_badge_guard.py --changed-only --require-fresh-xml"
                ],
            )
        )
    if any(
        _matches_prefix(path, BADGE_PATH_PREFIXES)
        or "coverage-" in Path(path).name
        or path == "tools/generate_component_coverage_badges.py"
        for path in paths
    ):
        commands = [
            "uv --preview-features extra-build-dependencies run pytest -q -o addopts='' test/test_generate_component_coverage_badges.py"
        ]
        if components:
            commands.append(
                "uv --preview-features extra-build-dependencies run python tools/generate_component_coverage_badges.py --components "
                + " ".join(components)
            )
        else:
            commands.append(
                "uv --preview-features extra-build-dependencies run python tools/generate_component_coverage_badges.py"
            )
        commands.append(
            "uv --preview-features extra-build-dependencies run python tools/coverage_badge_guard.py --components "
            + " ".join(components or ["agi-env", "agi-node", "agi-cluster", "agi-gui"])
            + " --changed-only --require-fresh-xml"
        )
        artifacts.append(
            Action(
                key="badge-refresh",
                summary="Refresh coverage badges only after validating the generator path.",
                commands=commands,
            )
        )
        artifacts.append(
            Action(
                key="workflow-parity-badges",
                summary="Run the local badge workflow parity profile.",
                commands=[
                    "uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile badges"
                ],
            )
        )

    if any(path.startswith("docs/source/") for path in paths):
        artifacts.append(
            Action(
                key="docs-build",
                summary="Docs source changed; run the local Sphinx/docs build that matches this checkout before publishing.",
                commands=["# run the repo-local docs build or preview command used for this docs change"],
            )
        )
        artifacts.append(
            Action(
                key="workflow-parity-docs",
                summary="Run the local docs workflow parity profile.",
                commands=[
                    "uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile docs"
                ],
            )
        )

    if any(_is_gui_file(path) for path in paths):
        actions.append(
            Action(
                key="workflow-parity-agi-gui",
                summary="Run the local agi-gui workflow parity profile when UI/runtime surfaces are touched.",
                commands=[
                    "uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile agi-gui"
                ],
            )
        )

    overall_risk = "low"
    if any(zone.key in {"shared-core", "installer"} for zone in zones):
        overall_risk = "high"
    elif any(zone.key in {"runconfig", "skills", "badges", "gui"} for zone in zones):
        overall_risk = "medium"

    return ImpactReport(
        files=paths,
        overall_risk=overall_risk,
        risk_zones=zones,
        push_gates=_dedupe_actions(push_gates),
        artifact_actions=_dedupe_actions(artifacts),
        required_validations=_dedupe_actions(actions),
        guessed_tests=guessed_tests,
    )


def _render_human(report: ImpactReport) -> str:
    lines = [
        f"Overall risk: {report.overall_risk}",
        f"Files analyzed: {len(report.files)}",
    ]
    if report.files:
        lines.append("Changed files:")
        lines.extend(f"- {path}" for path in report.files)
    if report.risk_zones:
        lines.append("")
        lines.append("Risk zones:")
        for zone in report.risk_zones:
            lines.append(f"- {zone.key}: {zone.summary}")
            for path in zone.files:
                lines.append(f"  - {path}")
    if report.push_gates:
        lines.append("")
        lines.append("Push gates:")
        for gate in report.push_gates:
            lines.append(f"- {gate.summary}")
    if report.artifact_actions:
        lines.append("")
        lines.append("Artifact actions:")
        for action in report.artifact_actions:
            lines.append(f"- {action.summary}")
            for command in action.commands:
                lines.append(f"  - {command}")
    if report.required_validations:
        lines.append("")
        lines.append("Required validations:")
        for action in report.required_validations:
            lines.append(f"- {action.summary}")
            for command in action.commands:
                lines.append(f"  - {command}")
    if report.guessed_tests:
        lines.append("")
        lines.append("Guessed tests:")
        lines.extend(f"- {path}" for path in report.guessed_tests)
    if not report.files:
        lines.append("")
        lines.append("No changed files matched the selected input.")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        paths = _collect_changed_files(args)
    except RuntimeError as exc:
        parser.exit(2, f"impact_validate: {exc}\n")

    report = analyze_paths(paths)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(_render_human(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
