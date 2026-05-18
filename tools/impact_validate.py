#!/usr/bin/env python3
"""Analyze changed files and suggest AGILAB-specific validation gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
IMPACT_CACHE_SCHEMA = "agilab-impact-validate-cache-v1"
DEFAULT_IMPACT_CACHE_PATH = (
    REPO_ROOT / ".pytest_cache" / "agilab" / "impact_validate.json"
)
IMPACT_REPORT_CACHE_MAX_ENTRIES = 256

SHARED_CORE_PREFIXES = (
    "src/agilab/core/agi-env/",
    "src/agilab/core/agi-node/",
    "src/agilab/core/agi-cluster/",
    "src/agilab/core/agi-core/",
)
SHARED_TOOLING_PATHS = {
    "install.sh",
    "install.ps1",
    "src/agilab/install_apps.sh",
    "src/agilab/install_apps.ps1",
    "src/agilab/apps/install.py",
    "src/agilab/core/install.sh",
    "src/agilab/core/install.ps1",
}
SHELL_CHECK_FILES = ("install.sh", "src/agilab/install_apps.sh", "src/agilab/core/install.sh")
RUNCONFIG_PREFIXES = (".idea/runConfigurations/", "tools/run_configs/")
SKILL_PREFIXES = (".claude/skills/", ".codex/skills/")
COVERAGE_BADGE_PATH_PREFIXES = ("badges/coverage-",)
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
TEST_GUESS_ROOTS = (
    "test",
    "src/agilab/test",
    "src/agilab/core/test",
    "src/agilab/core/agi-env/test",
)
IMPACT_STATIC_INPUTS = (
    "tools/impact_validate.py",
)
NON_GUI_ROOT_TESTS = {
    "test/conftest.py",
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


@dataclass(frozen=True)
class TestIndex:
    roots: tuple[str, ...]
    exact_by_root: tuple[dict[str, tuple[str, ...]], ...]
    prefix_by_root: tuple[dict[str, tuple[str, ...]], ...]
    paths: frozenset[str]

    def contains(self, path: str) -> bool:
        return path in self.paths

    def tests_for_stem(
        self, stem: str, *, roots: Sequence[str] | None = None
    ) -> list[str]:
        selected_roots = set(roots) if roots is not None else None
        matches: list[str] = []
        for index, root in enumerate(self.roots):
            if selected_roots is not None and root not in selected_roots:
                continue
            matches.extend(self.exact_by_root[index].get(stem, ()))
            matches.extend(self.prefix_by_root[index].get(stem, ()))
        return matches


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
    parser.add_argument(
        "--cache-path",
        default=str(DEFAULT_IMPACT_CACHE_PATH),
        help="Path for cached test index metadata and impact reports.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass cached test index metadata and impact reports.",
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


def _append_mapping_value(
    mapping: dict[str, list[str]], key: str, value: str
) -> None:
    current = mapping.setdefault(key, [])
    if value not in current:
        current.append(value)


def _normalized_roots(roots: Sequence[str]) -> tuple[str, ...]:
    return tuple(root.strip("/") for root in roots if root.strip("/"))


def _build_test_index(
    repo: Path | None = None, roots: Sequence[str] = TEST_GUESS_ROOTS
) -> TestIndex:
    effective_repo = repo or REPO_ROOT
    normalized_roots = _normalized_roots(roots)
    exact_by_root: list[dict[str, tuple[str, ...]]] = []
    prefix_by_root: list[dict[str, tuple[str, ...]]] = []
    indexed_paths: set[str] = set()

    for root in normalized_roots:
        root_path = effective_repo / root
        root_exact: dict[str, list[str]] = {}
        root_prefix: dict[str, list[str]] = {}
        if root_path.exists():
            for path in sorted(root_path.glob("test_*.py")):
                if not path.is_file():
                    continue
                relative = path.relative_to(effective_repo).as_posix()
                indexed_paths.add(relative)
                stem = path.stem.removeprefix("test_")
                if not stem:
                    continue
                _append_mapping_value(root_exact, stem, relative)
                parts = stem.split("_")
                for index in range(1, len(parts)):
                    _append_mapping_value(
                        root_prefix, "_".join(parts[:index]), relative
                    )
        exact_by_root.append(
            {key: tuple(values) for key, values in root_exact.items()}
        )
        prefix_by_root.append(
            {key: tuple(values) for key, values in root_prefix.items()}
        )

    return TestIndex(
        roots=normalized_roots,
        exact_by_root=tuple(exact_by_root),
        prefix_by_root=tuple(prefix_by_root),
        paths=frozenset(indexed_paths),
    )


def _empty_impact_cache() -> dict[str, object]:
    return {"schema": IMPACT_CACHE_SCHEMA, "test_index": {}, "reports": {}}


def _load_impact_cache(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_impact_cache()
    if not isinstance(data, dict) or data.get("schema") != IMPACT_CACHE_SCHEMA:
        return _empty_impact_cache()
    test_index = data.get("test_index")
    reports = data.get("reports")
    return {
        "schema": IMPACT_CACHE_SCHEMA,
        "test_index": test_index if isinstance(test_index, dict) else {},
        "reports": reports if isinstance(reports, dict) else {},
    }


def _write_impact_cache(path: Path, state: dict[str, object]) -> None:
    payload = {
        "schema": IMPACT_CACHE_SCHEMA,
        "test_index": (
            state.get("test_index") if isinstance(state.get("test_index"), dict) else {}
        ),
        "reports": (
            state.get("reports") if isinstance(state.get("reports"), dict) else {}
        ),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except OSError:
        return


def _file_signature(repo: Path, rel_path: str) -> dict[str, object]:
    path = repo / rel_path
    try:
        stat_result = path.stat()
    except OSError:
        return {"path": rel_path, "state": "missing"}
    if not path.is_file():
        return {"path": rel_path, "state": "not-file"}
    return {
        "path": rel_path,
        "state": "file",
        "size": stat_result.st_size,
        "mtime_ns": stat_result.st_mtime_ns,
    }


def _test_index_signature(
    repo: Path | None = None, roots: Sequence[str] = TEST_GUESS_ROOTS
) -> list[dict[str, object]]:
    effective_repo = repo or REPO_ROOT
    signature: list[dict[str, object]] = []
    for root in _normalized_roots(roots):
        root_path = effective_repo / root
        if not root_path.exists():
            signature.append({"path": root, "state": "missing-root"})
            continue
        for path in sorted(root_path.glob("test_*.py")):
            if not path.is_file():
                continue
            signature.append(
                _file_signature(
                    effective_repo,
                    path.relative_to(effective_repo).as_posix(),
                )
            )
    return signature


def _static_input_signature(repo: Path | None = None) -> list[dict[str, object]]:
    effective_repo = repo or REPO_ROOT
    return [_file_signature(effective_repo, path) for path in IMPACT_STATIC_INPUTS]


def _test_index_to_payload(index: TestIndex) -> dict[str, object]:
    return {
        "roots": list(index.roots),
        "exact_by_root": [
            {key: list(values) for key, values in root.items()}
            for root in index.exact_by_root
        ],
        "prefix_by_root": [
            {key: list(values) for key, values in root.items()}
            for root in index.prefix_by_root
        ],
        "paths": sorted(index.paths),
    }


def _string_tuple_mapping(value: object) -> dict[str, tuple[str, ...]] | None:
    if not isinstance(value, dict):
        return None
    converted: dict[str, tuple[str, ...]] = {}
    for key, raw_values in value.items():
        if not isinstance(key, str) or not isinstance(raw_values, list):
            return None
        if not all(isinstance(item, str) for item in raw_values):
            return None
        converted[key] = tuple(raw_values)
    return converted


def _test_index_from_payload(payload: object) -> TestIndex | None:
    if not isinstance(payload, dict):
        return None
    roots = payload.get("roots")
    exact_by_root = payload.get("exact_by_root")
    prefix_by_root = payload.get("prefix_by_root")
    paths = payload.get("paths")
    if (
        not isinstance(roots, list)
        or not isinstance(exact_by_root, list)
        or not isinstance(prefix_by_root, list)
        or not isinstance(paths, list)
    ):
        return None
    if not all(isinstance(root, str) for root in roots):
        return None
    if len(exact_by_root) != len(roots) or len(prefix_by_root) != len(roots):
        return None
    exact_maps = [_string_tuple_mapping(item) for item in exact_by_root]
    prefix_maps = [_string_tuple_mapping(item) for item in prefix_by_root]
    if any(item is None for item in exact_maps) or any(
        item is None for item in prefix_maps
    ):
        return None
    if not all(isinstance(path, str) for path in paths):
        return None
    return TestIndex(
        roots=tuple(roots),
        exact_by_root=tuple(item for item in exact_maps if item is not None),
        prefix_by_root=tuple(item for item in prefix_maps if item is not None),
        paths=frozenset(paths),
    )


def _build_cached_test_index(
    *,
    cache_path: Path = DEFAULT_IMPACT_CACHE_PATH,
    use_cache: bool = True,
    signature: list[dict[str, object]] | None = None,
) -> TestIndex:
    if not use_cache:
        return _build_test_index()

    roots = _normalized_roots(TEST_GUESS_ROOTS)
    effective_signature = signature if signature is not None else _test_index_signature()
    state = _load_impact_cache(cache_path)
    cached = state.get("test_index")
    if (
        isinstance(cached, dict)
        and cached.get("roots") == list(roots)
        and cached.get("signature") == effective_signature
        and cached.get("python") == list(sys.version_info[:3])
    ):
        index = _test_index_from_payload(cached.get("index"))
        if index is not None:
            return index

    index = _build_test_index()
    state["test_index"] = {
        "roots": list(roots),
        "signature": effective_signature,
        "python": list(sys.version_info[:3]),
        "index": _test_index_to_payload(index),
    }
    _write_impact_cache(cache_path, state)
    return index


def _test_path_exists(path: str, test_index: TestIndex, *, repo: Path) -> bool:
    return test_index.contains(path) or (repo / path).exists()


def _risk_zones(paths: list[str]) -> list[RiskZone]:
    zones: list[RiskZone] = []
    builders = (
        ("shared-core", "Protected shared core or shared tooling touched.", _is_shared_core),
        ("installer", "Installer or deployment contract touched.", lambda p: p in SHELL_CHECK_FILES or p == "src/agilab/apps/install.py"),
        ("runconfig", "Run configuration or generated launcher touched.", lambda p: _matches_prefix(p, RUNCONFIG_PREFIXES)),
        ("skills", "Shared agent skill trees touched.", lambda p: _matches_prefix(p, SKILL_PREFIXES)),
        (
            "badges",
            "Coverage badge inputs or generated badge artifacts touched.",
            lambda p: _matches_prefix(p, COVERAGE_BADGE_PATH_PREFIXES)
            or "coverage-" in Path(p).name
            or p == "tools/generate_component_coverage_badges.py",
        ),
        ("gui", "GUI/page/runtime surface touched.", _is_gui_file),
        ("docs", "Docs source touched.", lambda p: _matches_prefix(p, DOCS_PREFIXES)),
    )
    for key, summary, predicate in builders:
        matched = [path for path in paths if predicate(path)]
        if matched:
            zones.append(RiskZone(key=key, summary=summary, files=matched))
    return zones


def _guess_tests_for_file(
    path: str, *, test_index: TestIndex | None = None
) -> list[str]:
    repo = REPO_ROOT
    index = test_index or _build_test_index()
    workflow_tests = {
        ".github/workflows/ci.yml": "test/test_ci_workflow.py",
        ".github/workflows/coverage.yml": "test/test_coverage_workflow.py",
        ".github/workflows/docs-source-guard.yaml": "test/test_ci_workflow.py",
        ".github/workflows/docs-publish.yaml": "test/test_ci_workflow.py",
        ".github/workflows/ensure-roadmap-label.yaml": "test/test_ci_workflow.py",
        ".github/workflows/ui-robot-matrix.yml": "test/test_ci_workflow.py",
    }
    if path in workflow_tests:
        return [workflow_tests[path]]
    if path == "test/conftest.py":
        return [
            "test/test_ci_workflow.py",
            "test/test_view_maps_3d.py::test_view_maps_3d_warns_when_no_dataset_exists",
        ]

    candidate_tests: list[Path] = []
    rel = Path(path)
    stem = rel.stem

    if _matches_prefix(path, TEST_PREFIXES):
        if _test_path_exists(path, index, repo=repo):
            return [path]
        return []

    if path.startswith("src/agilab/apps-pages/"):
        parts = rel.parts
        if len(parts) >= 4:
            page_name = parts[3]
            candidate_tests.extend(
                Path(candidate)
                for candidate in index.tests_for_stem(page_name, roots=("test",))
            )

    if path.startswith("src/agilab/pages/"):
        ui_pages = repo / "test" / "test_ui_pages.py"
        if _test_path_exists("test/test_ui_pages.py", index, repo=repo):
            candidate_tests.append(ui_pages)

    if path.startswith("src/agilab/apps/"):
        parts = rel.parts
        project_root: Path | None = None
        for part_index, part in enumerate(parts):
            if part.endswith("_project"):
                project_root = Path(*parts[: part_index + 1])
                break
        if project_root is not None:
            app_test = repo / project_root / "app_test.py"
            if app_test.exists():
                candidate_tests.append(app_test)

    candidate_tests.extend(Path(candidate) for candidate in index.tests_for_stem(stem))

    normalized = []
    seen: set[str] = set()
    for candidate in candidate_tests:
        if candidate.is_absolute():
            if not candidate.exists():
                continue
            relative = candidate.relative_to(repo).as_posix()
        else:
            relative = candidate.as_posix()
        if not _test_path_exists(relative, index, repo=repo):
            continue
        if relative not in seen:
            normalized.append(relative)
            seen.add(relative)
    return normalized


def _guess_targeted_tests(
    paths: list[str], *, test_index: TestIndex | None = None
) -> list[str]:
    index = test_index or _build_test_index()
    guessed: list[str] = []
    seen: set[str] = set()
    for path in paths:
        for candidate in _guess_tests_for_file(path, test_index=index):
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


def _strings(value: object) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return list(value)


def _action_from_payload(payload: object) -> Action | None:
    if not isinstance(payload, dict):
        return None
    key = payload.get("key")
    summary = payload.get("summary")
    commands = _strings(payload.get("commands"))
    if not isinstance(key, str) or not isinstance(summary, str) or commands is None:
        return None
    return Action(key=key, summary=summary, commands=commands)


def _risk_zone_from_payload(payload: object) -> RiskZone | None:
    if not isinstance(payload, dict):
        return None
    key = payload.get("key")
    summary = payload.get("summary")
    files = _strings(payload.get("files"))
    if not isinstance(key, str) or not isinstance(summary, str) or files is None:
        return None
    return RiskZone(key=key, summary=summary, files=files)


def _impact_report_from_payload(payload: object) -> ImpactReport | None:
    if not isinstance(payload, dict):
        return None
    files = _strings(payload.get("files"))
    overall_risk = payload.get("overall_risk")
    guessed_tests = _strings(payload.get("guessed_tests"))
    raw_risk_zones = payload.get("risk_zones")
    raw_push_gates = payload.get("push_gates")
    raw_artifact_actions = payload.get("artifact_actions")
    raw_required_validations = payload.get("required_validations")
    if (
        files is None
        or not isinstance(overall_risk, str)
        or guessed_tests is None
        or not isinstance(raw_risk_zones, list)
        or not isinstance(raw_push_gates, list)
        or not isinstance(raw_artifact_actions, list)
        or not isinstance(raw_required_validations, list)
    ):
        return None
    risk_zones = [_risk_zone_from_payload(item) for item in raw_risk_zones]
    push_gates = [_action_from_payload(item) for item in raw_push_gates]
    artifact_actions = [_action_from_payload(item) for item in raw_artifact_actions]
    required_validations = [
        _action_from_payload(item) for item in raw_required_validations
    ]
    if (
        any(item is None for item in risk_zones)
        or any(item is None for item in push_gates)
        or any(item is None for item in artifact_actions)
        or any(item is None for item in required_validations)
    ):
        return None
    return ImpactReport(
        files=files,
        overall_risk=overall_risk,
        risk_zones=[item for item in risk_zones if item is not None],
        push_gates=[item for item in push_gates if item is not None],
        artifact_actions=[item for item in artifact_actions if item is not None],
        required_validations=[
            item for item in required_validations if item is not None
        ],
        guessed_tests=guessed_tests,
    )


def _impact_report_cache_key(
    paths: Sequence[str],
    *,
    test_signature: list[dict[str, object]],
    static_signature: list[dict[str, object]],
) -> str:
    payload = {
        "schema": IMPACT_CACHE_SCHEMA,
        "kind": "impact-report",
        "python": list(sys.version_info[:3]),
        "paths": list(paths),
        "test_signature": test_signature,
        "static_signature": static_signature,
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cached_impact_report(cache_path: Path, key: str) -> ImpactReport | None:
    reports = _load_impact_cache(cache_path).get("reports")
    if not isinstance(reports, dict):
        return None
    entry = reports.get(key)
    if not isinstance(entry, dict):
        return None
    return _impact_report_from_payload(entry.get("report"))


def _trim_report_cache_entries(entries: dict[str, object]) -> None:
    while len(entries) > IMPACT_REPORT_CACHE_MAX_ENTRIES:
        oldest_key = next(iter(entries))
        entries.pop(oldest_key, None)


def _record_impact_report(cache_path: Path, key: str, report: ImpactReport) -> None:
    state = _load_impact_cache(cache_path)
    reports = state.get("reports")
    if not isinstance(reports, dict):
        reports = {}
    reports[key] = {"report": report.to_dict()}
    _trim_report_cache_entries(reports)
    state["reports"] = reports
    _write_impact_cache(cache_path, state)


def _analyze_paths_uncached(paths: list[str], test_index: TestIndex) -> ImpactReport:
    zones = _risk_zones(paths)
    guessed_tests = _guess_targeted_tests(paths, test_index=test_index)
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
                commands=["bash -n " + " ".join(SHELL_CHECK_FILES)],
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
                    "uv --preview-features extra-build-dependencies run pytest -q -o addopts='' "
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
    if any(
        _matches_prefix(path, COVERAGE_BADGE_PATH_PREFIXES)
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


def analyze_paths(
    paths: list[str],
    *,
    cache_path: Path = DEFAULT_IMPACT_CACHE_PATH,
    use_cache: bool = True,
) -> ImpactReport:
    if not use_cache:
        return _analyze_paths_uncached(paths, _build_test_index())

    test_signature = _test_index_signature()
    static_signature = _static_input_signature()
    cache_key = _impact_report_cache_key(
        paths,
        test_signature=test_signature,
        static_signature=static_signature,
    )
    cached = _cached_impact_report(cache_path, cache_key)
    if cached is not None:
        return cached

    test_index = _build_cached_test_index(
        cache_path=cache_path,
        use_cache=use_cache,
        signature=test_signature,
    )
    report = _analyze_paths_uncached(paths, test_index)
    _record_impact_report(cache_path, cache_key, report)
    return report


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

    report = analyze_paths(
        paths,
        cache_path=Path(args.cache_path),
        use_cache=not args.no_cache,
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(_render_human(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
