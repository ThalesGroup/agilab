#!/usr/bin/env python3
"""Validate AGILAB UI robot action coverage and explicit action dispositions."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
WIDGET_ROBOT_PATH = REPO_ROOT / "tools" / "agilab_widget_robot.py"
MATRIX_PATH = REPO_ROOT / "tools" / "agilab_widget_robot_matrix.py"
SCHEMA = "agilab.ui_robot_action_contract.v1"
DEFAULT_SOURCE_ROOTS = (REPO_ROOT / "src/agilab",)
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


EXPLICIT_ACTION_DISPOSITIONS: Mapping[str, tuple[str, str]] = {
    "Add argument": (
        "trial-only",
        "mutates the ORCHESTRATE argument editor; covered by focused page tests, not fired by generic robots",
    ),
    "Apply": (
        "trial-only",
        "applies page-local user choices; generic robots verify visibility without firing the callback",
    ),
    "Build cluster plan": (
        "trial-only",
        "writes advisory LAN discovery output; focused cluster tests cover the planning logic without mutating user settings",
    ),
    "Clear LAN cache": (
        "trial-only",
        "clears local discovery cache; safe to render, but not a selected release action",
    ),
    "Create": (
        "trial-only",
        "creates project or analysis objects; PROJECT/ANALYSIS robots probe the control without mutating state",
    ),
    "Delete": (
        "trial-only",
        "destructive project-level delete action; focused tests cover confirmation behavior",
    ),
    "Export": (
        "trial-only",
        "project export is not part of the first-proof selected-click path",
    ),
    "Export promotion decision": (
        "trial-only",
        "apps-page export side effect is covered by page-specific tests and visual robots",
    ),
    "Import": (
        "trial-only",
        "project import is probed through PROJECT import scenarios without firing archive import",
    ),
    "Install PyPI app": (
        "trial-only",
        "installs a reviewed external app package; helper tests cover command construction without mutating the environment",
    ),
    "Overwrite": (
        "ignored",
        "conditional conflict-resolution action that only appears after an import conflict",
    ),
    "Rebuild Universal Offline knowledge base": (
        "ignored",
        "requires a local knowledge-base rebuild outside the deterministic UI robot environment",
    ),
    "Reset": (
        "trial-only",
        "clears the PyTorch playground local training state; focused playground tests cover state reset behavior",
    ),
    "Rename": (
        "trial-only",
        "project rename is probed through PROJECT rename scenarios without mutating the project",
    ),
    "Remove PyPI app": (
        "trial-only",
        "removes an installed external app package only after explicit user confirmation",
    ),
    "Save .env": (
        "ignored",
        "writes local environment configuration and is covered by env-editor helper tests",
    ),
    "Save and retry": (
        "ignored",
        "writes local environment configuration and depends on user-provided settings",
    ),
    "Save classroom uploads": (
        "trial-only",
        "writes classroom intake files; focused TeSciA tests cover upload handling without mutating generic robot state",
    ),
    "Start GPT-OSS server": (
        "ignored",
        "starts an external local service and is not deterministic in CI robots",
    ),
    "Train / refresh": (
        "trial-only",
        "runs page-local PyTorch training; focused playground tests cover state and evidence without making generic robots train",
    ),
    "Undo last delete": (
        "trial-only",
        "stateful recovery action that appears only after selected delete-output flows",
    ),
    "Update PyPI app": (
        "trial-only",
        "updates an installed external app package only after explicit user confirmation",
    ),
    "Update key": (
        "ignored",
        "updates local secret configuration and is covered by provider-form tests",
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


def _literal_string(node: ast.AST, constants: Mapping[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_string(node.left, constants)
        right = _literal_string(node.right, constants)
        if left is not None and right is not None:
            return left + right
    return None


def _module_string_constants(tree: ast.AST) -> dict[str, str]:
    constants: dict[str, str] = {}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = _literal_string(node.value, constants)
            if value is not None:
                constants[node.targets[0].id] = value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            value = _literal_string(node.value, constants) if node.value is not None else None
            if value is not None:
                constants[node.target.id] = value
    return constants


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return ""


def _call_label(node: ast.Call, constants: Mapping[str, str]) -> str | None:
    if node.args:
        label = _literal_string(node.args[0], constants)
        if label is not None:
            return label
    for keyword in node.keywords:
        if keyword.arg == "label":
            return _literal_string(keyword.value, constants)
    return None


def scan_action_occurrences(
    source_roots: Sequence[Path],
    *,
    widget_robot: Any,
) -> list[ActionOccurrence]:
    occurrences: list[ActionOccurrence] = []
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
            constants = _module_string_constants(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = _call_name(node)
                if name not in ACTION_CALL_NAMES:
                    continue
                label = _call_label(node, constants)
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


def _explicit_dispositions(widget_robot: Any) -> dict[str, tuple[str, str, str]]:
    return {
        widget_robot._normalized_label(label): (label, disposition, reason)
        for label, (disposition, reason) in EXPLICIT_ACTION_DISPOSITIONS.items()
    }


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
        _raw_label, disposition, reason = explicit_entry
        if not reason.strip():
            first = label_occurrences[0]
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
        dispositions.append(
            ActionDisposition(
                label=label,
                normalized_label=normalized_label,
                disposition=disposition,
                reason=reason,
                selected_scenarios=[],
                occurrences=label_occurrences,
            )
        )

    unused_dispositions = [
        {"label": raw_label, "normalized_label": normalized_label, "disposition": disposition, "reason": reason}
        for normalized_label, (raw_label, disposition, reason) in sorted(explicit.items())
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
