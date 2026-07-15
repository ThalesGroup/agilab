#!/usr/bin/env python3
"""Validate AGILAB UI robot action coverage and explicit action dispositions."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
WIDGET_ROBOT_PATH = REPO_ROOT / "tools" / "agilab_widget_robot.py"
MATRIX_PATH = REPO_ROOT / "tools" / "agilab_widget_robot_matrix.py"
SCHEMA = "agilab.ui_robot_action_contract.v1"
DEFAULT_SOURCE_ROOTS = (REPO_ROOT / "src/agilab",)
SHARED_ACTION_LABELS_SOURCE = REPO_ROOT / "src/agilab/orchestrate/orchestrate_page_support.py"
ACTION_CALL_NAMES = {"button", "form_submit_button", "download_button"}
EXCLUDED_PATH_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
    "site-packages",
}


# Each disposition is (disposition, reason, focused_tests). ``focused_tests`` lists the
# repo-relative pytest files that actually exercise the action's behavior. Generic robots
# deliberately do not fire these actions (they mutate state, hit external services, or are
# only reachable behind conditional flows), so the disposition is only honest if the focused
# tests it points at still exist. ``evaluate_contract`` enforces that every listed path is
# present on disk, closing the gap where a deleted/renamed focused test would silently leave
# a high-risk action with zero coverage and a passing contract.
EXPLICIT_ACTION_DISPOSITIONS: Mapping[str, tuple[str, str, tuple[str, ...]]] = {
    "Train autoencoder": (
        "trial-only",
        "starts an explicit local Keras training run in the autoencoder playground; generic robots verify the gate renders without launching training",
        ("test/test_autoencoder_latentspace.py",),
    ),
    "Add argument": (
        "trial-only",
        "mutates the ORCHESTRATE argument editor; covered by focused page tests, not fired by generic robots",
        ("test/test_orchestrate_page_support.py",),
    ),
    "Apply": (
        "trial-only",
        "applies page-local user choices; generic robots verify visibility without firing the callback",
        ("test/test_ui_pages.py",),
    ),
    "Build cluster plan": (
        "trial-only",
        "writes advisory LAN discovery output; focused cluster tests cover the planning logic without mutating user settings",
        ("test/test_orchestrate_cluster.py",),
    ),
    "Clear LAN cache": (
        "trial-only",
        "clears local discovery cache; safe to render, but not a selected release action",
        ("test/test_orchestrate_cluster.py",),
    ),
    "Create": (
        "trial-only",
        "creates project or analysis objects; PROJECT/ANALYSIS robots probe the control without mutating state",
        ("test/test_project_sidebar_support.py",),
    ),
    "Delete": (
        "trial-only",
        "destructive project-level delete action; focused tests cover confirmation behavior",
        ("test/test_project_sidebar_support.py",),
    ),
    "Export promotion decision": (
        "trial-only",
        "apps-page export side effect is covered by page-specific tests and visual robots",
        ("test/test_view_release_decision.py",),
    ),
    "Import": (
        "trial-only",
        "project import is probed through PROJECT import scenarios without firing archive import",
        ("test/test_project_sidebar_support.py",),
    ),
    "Install agi-app": (
        "ignored",
        "installs user-selected PyPI code and requires explicit operator trust; package preflight tests cover validation",
        ("test/test_ui_pages.py",),
    ),
    "Overwrite": (
        "ignored",
        "conditional conflict-resolution action that only appears after an import conflict",
        ("test/test_project_clone_policy.py",),
    ),
    "Overwrite notebook exports from current stages": (
        "trial-only",
        "explicitly replaces edited notebook exports; generic robots verify the control without firing the overwrite",
        ("test/test_notebook_export_overwrite.py",),
    ),
    "Rebuild Universal Offline knowledge base": (
        "ignored",
        "requires a local knowledge-base rebuild outside the deterministic UI robot environment",
        ("test/test_pipeline_ai.py",),
    ),
    "Reset": (
        "trial-only",
        "clears the PyTorch playground local training state; focused playground tests cover state reset behavior",
        ("test/test_pytorch_playground_app.py",),
    ),
    "Rename": (
        "trial-only",
        "project rename is probed through PROJECT rename scenarios without mutating the project",
        ("test/test_project_sidebar_support.py",),
    ),
    "Run instant demo": (
        "trial-only",
        "runs page-local PyTorch training; focused playground tests cover state and evidence without making generic robots train",
        ("test/test_pytorch_playground_app.py",),
    ),
    "Save .env": (
        "ignored",
        "writes local environment configuration and is covered by env-editor helper tests",
        ("test/test_about_agilab_helpers.py",),
    ),
    "Save and retry": (
        "ignored",
        "writes local environment configuration and depends on user-provided settings",
        ("test/test_about_agilab_helpers.py",),
    ),
    "Save classroom uploads": (
        "trial-only",
        "writes classroom intake files; focused TeSciA tests cover upload handling without mutating generic robot state",
        ("test/test_tescia_diagnostic_project.py",),
    ),
    "Start GPT-OSS server": (
        "ignored",
        "starts an external local service and is not deterministic in CI robots",
        ("test/test_pipeline_ai.py",),
    ),
    "Train / refresh": (
        "trial-only",
        "runs page-local PyTorch training; focused playground tests cover state and evidence without making generic robots train",
        ("test/test_pytorch_playground_app.py",),
    ),
    "Undo last delete": (
        "trial-only",
        "stateful recovery action that appears only after selected delete-output flows",
        ("test/test_orchestrate_execute.py",),
    ),
    "Update key": (
        "ignored",
        "updates local secret configuration and is covered by provider-form tests",
        ("test/test_pipeline_openai.py", "test/test_pipeline_mistral.py"),
    ),
}


@dataclass(frozen=True)
class ActionOccurrence:
    label: str
    normalized_label: str
    kind: str
    path: str
    line: int


@dataclass(frozen=True)
class ActionDisposition:
    label: str
    normalized_label: str
    disposition: str
    reason: str
    selected_scenarios: list[str]
    occurrences: list[ActionOccurrence]
    focused_tests: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ActionIssue:
    kind: str
    label: str
    detail: str
    path: str = ""
    line: int = 0


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_PATH_PARTS for part in path.parts)


def _literal_string(
    node: ast.AST,
    constants: Mapping[str, str],
    string_maps: Mapping[str, Mapping[str, str]] | None = None,
) -> str | None:
    string_maps = string_maps or {}
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        source_map = string_maps.get(node.value.id)
        if source_map is None:
            return None
        key = _literal_string(node.slice, constants, string_maps)
        if key is None:
            return None
        return source_map.get(key)
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_string(node.left, constants, string_maps)
        right = _literal_string(node.right, constants, string_maps)
        if left is not None and right is not None:
            return left + right
    return None


def _literal_string_dict(
    node: ast.AST,
    constants: Mapping[str, str],
    string_maps: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, str] | None:
    if not isinstance(node, ast.Dict):
        return None
    result: dict[str, str] = {}
    for key_node, value_node in zip(node.keys, node.values, strict=False):
        if key_node is None:
            return None
        key = _literal_string(key_node, constants, string_maps)
        value = _literal_string(value_node, constants, string_maps)
        if key is None or value is None:
            return None
        result[key] = value
    return result


def _module_string_constants(
    tree: ast.AST,
    string_maps: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, str]:
    constants: dict[str, str] = {}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = _literal_string(node.value, constants, string_maps)
            if value is not None:
                constants[node.targets[0].id] = value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            value = _literal_string(node.value, constants, string_maps) if node.value is not None else None
            if value is not None:
                constants[node.target.id] = value
    return constants


def _module_string_maps(tree: ast.AST) -> dict[str, dict[str, str]]:
    maps: dict[str, dict[str, str]] = {}
    constants = _module_string_constants(tree)
    for node in ast.iter_child_nodes(tree):
        target_name: str | None = None
        value_node: ast.AST | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target_name = node.targets[0].id
            value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value_node = node.value
        if target_name is None or value_node is None:
            continue
        value = _literal_string_dict(value_node, constants)
        if value is not None:
            maps[target_name] = value
    return maps


def _shared_string_maps() -> dict[str, dict[str, str]]:
    try:
        tree = ast.parse(SHARED_ACTION_LABELS_SOURCE.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return {}
    return _module_string_maps(tree)


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return ""


def _call_label(
    node: ast.Call,
    constants: Mapping[str, str],
    string_maps: Mapping[str, Mapping[str, str]] | None = None,
) -> str | None:
    if node.args:
        label = _literal_string(node.args[0], constants, string_maps)
        if label is not None:
            return label
        if len(node.args) > 1:
            label = _literal_string(node.args[1], constants, string_maps)
            if label is not None:
                return label
    for keyword in node.keywords:
        if keyword.arg == "label":
            return _literal_string(keyword.value, constants, string_maps)
    return None


def scan_action_occurrences(
    source_roots: Sequence[Path],
    *,
    widget_robot: Any,
) -> list[ActionOccurrence]:
    occurrences: list[ActionOccurrence] = []
    shared_string_maps = _shared_string_maps()
    for root in source_roots:
        resolved_root = root if root.is_absolute() else REPO_ROOT / root
        if not resolved_root.exists():
            continue
        for path in sorted(resolved_root.rglob("*.py")):
            if _is_excluded(path):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            string_maps = {**shared_string_maps, **_module_string_maps(tree)}
            constants = _module_string_constants(tree, string_maps)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = _call_name(node)
                if name not in ACTION_CALL_NAMES:
                    continue
                label = _call_label(node, constants, string_maps)
                if not label:
                    continue
                try:
                    rel_path = path.resolve().relative_to(REPO_ROOT)
                    path_text = rel_path.as_posix()
                except ValueError:
                    path_text = path.as_posix()
                occurrences.append(
                    ActionOccurrence(
                        label=label,
                        normalized_label=widget_robot._normalized_label(label),
                        kind=name,
                        path=path_text,
                        line=int(getattr(node, "lineno", 0)),
                    )
                )
    return sorted(
        occurrences,
        key=lambda item: (item.normalized_label, item.path, item.line, item.kind),
    )


def _selected_action_scenarios(widget_robot: Any, matrix: Any) -> dict[str, list[str]]:
    scenarios: dict[str, list[str]] = {}
    for scenario in matrix.ALL_SCENARIOS.values():
        if getattr(scenario, "action_button_policy", "") != "click-selected":
            continue
        for label in widget_robot.parse_csv(str(getattr(scenario, "click_action_labels", ""))):
            normalized = widget_robot._normalized_label(label)
            if normalized:
                scenarios.setdefault(normalized, []).append(str(scenario.name))
    return scenarios


def _explicit_dispositions(
    widget_robot: Any,
) -> dict[str, tuple[str, str, str, tuple[str, ...]]]:
    return {
        widget_robot._normalized_label(label): (label, disposition, reason, tuple(focused_tests))
        for label, (disposition, reason, focused_tests) in EXPLICIT_ACTION_DISPOSITIONS.items()
    }


def _missing_focused_tests(focused_tests: Sequence[str]) -> list[str]:
    missing: list[str] = []
    for rel_path in focused_tests:
        candidate = Path(rel_path)
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        if not candidate.is_file():
            missing.append(rel_path)
    return missing


def _is_high_risk_action(widget_robot: Any, occurrence: ActionOccurrence) -> bool:
    if occurrence.kind == "download_button":
        return False
    if widget_robot._action_label_has_safe_prefix(occurrence.label):
        return False
    tokens = widget_robot._action_label_tokens(occurrence.label)
    return bool(tokens & widget_robot.RISKY_ACTION_LABEL_TOKENS)


def _selected_scenarios_for_label(
    normalized_label: str,
    selected_actions: Mapping[str, list[str]],
) -> list[str]:
    return sorted(set(selected_actions.get(normalized_label, [])))


def evaluate_contract(source_roots: Sequence[Path] = DEFAULT_SOURCE_ROOTS) -> dict[str, Any]:
    widget_robot = _load_module("agilab_widget_robot_action_contract", WIDGET_ROBOT_PATH)
    matrix = _load_module("agilab_widget_robot_matrix_action_contract", MATRIX_PATH)
    occurrences = scan_action_occurrences(source_roots, widget_robot=widget_robot)
    high_risk = [occurrence for occurrence in occurrences if _is_high_risk_action(widget_robot, occurrence)]
    by_label: dict[str, list[ActionOccurrence]] = {}
    for occurrence in high_risk:
        by_label.setdefault(occurrence.normalized_label, []).append(occurrence)

    selected_actions = _selected_action_scenarios(widget_robot, matrix)
    explicit = _explicit_dispositions(widget_robot)
    issues: list[ActionIssue] = []
    dispositions: list[ActionDisposition] = []
    for normalized_label, label_occurrences in sorted(by_label.items()):
        selected_scenarios = _selected_scenarios_for_label(normalized_label, selected_actions)
        label = label_occurrences[0].label
        if selected_scenarios:
            dispositions.append(
                ActionDisposition(
                    label=label,
                    normalized_label=normalized_label,
                    disposition="selected-click",
                    reason="covered by one or more selected-click robot scenarios",
                    selected_scenarios=selected_scenarios,
                    occurrences=label_occurrences,
                )
            )
            continue
        explicit_entry = explicit.get(normalized_label)
        if explicit_entry is None:
            first = label_occurrences[0]
            issues.append(
                ActionIssue(
                    kind="unclassified_high_risk_action",
                    label=label,
                    detail="high-risk Streamlit action needs selected-click coverage or an explicit trial-only/ignored reason",
                    path=first.path,
                    line=first.line,
                )
            )
            continue
        _raw_label, disposition, reason, focused_tests = explicit_entry
        first = label_occurrences[0]
        if not reason.strip():
            issues.append(
                ActionIssue(
                    kind="missing_action_reason",
                    label=label,
                    detail=f"{disposition} action must include a non-empty reason",
                    path=first.path,
                    line=first.line,
                )
            )
            continue
        if not focused_tests:
            issues.append(
                ActionIssue(
                    kind="missing_focused_test",
                    label=label,
                    detail=f"{disposition} action must name at least one focused test that exercises its behavior",
                    path=first.path,
                    line=first.line,
                )
            )
            continue
        missing_tests = _missing_focused_tests(focused_tests)
        if missing_tests:
            issues.append(
                ActionIssue(
                    kind="missing_focused_test",
                    label=label,
                    detail=(
                        f"{disposition} action references focused tests that do not exist: "
                        f"{', '.join(missing_tests)}"
                    ),
                    path=first.path,
                    line=first.line,
                )
            )
            continue
        dispositions.append(
            ActionDisposition(
                label=label,
                normalized_label=normalized_label,
                disposition=disposition,
                reason=reason,
                selected_scenarios=[],
                occurrences=label_occurrences,
                focused_tests=list(focused_tests),
            )
        )

    unused_dispositions = [
        {
            "label": raw_label,
            "normalized_label": normalized_label,
            "disposition": disposition,
            "reason": reason,
            "focused_tests": list(focused_tests),
        }
        for normalized_label, (raw_label, disposition, reason, focused_tests) in sorted(explicit.items())
        if normalized_label not in by_label
    ]
    return {
        "schema": SCHEMA,
        "success": not issues,
        "issues": [asdict(issue) for issue in issues],
        "summary": {
            "action_count": len(occurrences),
            "high_risk_action_count": len(high_risk),
            "classified_high_risk_action_count": len(dispositions),
            "unclassified_high_risk_action_count": len(issues),
            "unused_disposition_count": len(unused_dispositions),
        },
        "actions": [asdict(disposition) for disposition in dispositions],
        "unused_dispositions": unused_dispositions,
    }


def render_human(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary", {})
    lines = [
        "AGILAB UI robot action contract",
        f"verdict: {'PASS' if payload.get('success') else 'FAIL'}",
        (
            f"actions={summary.get('action_count', 0)} "
            f"high_risk={summary.get('high_risk_action_count', 0)} "
            f"unclassified={summary.get('unclassified_high_risk_action_count', 0)}"
        ),
    ]
    for issue in payload.get("issues", []):
        location = f"{issue.get('path')}:{issue.get('line')}" if issue.get("path") else ""
        lines.append(f"- {issue.get('kind')}: {issue.get('label')!r} {location} - {issue.get('detail')}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", action="append", type=Path, default=[])
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(list(argv) if argv is not None else None)
    roots = tuple(args.source_root) if args.source_root else DEFAULT_SOURCE_ROOTS
    payload = evaluate_contract(roots)
    print(json.dumps(payload, indent=2, sort_keys=True) if args.json else render_human(payload))
    return 0 if payload["success"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
