"""Static workflow dry-run validation for AGILAB ``lab_stages.toml`` files."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from agilab.workflow.lab_stages_contract import (
    LAB_STAGES_SCHEMA,
    LAB_STAGES_SCHEMA_VERSION,
    displayable_stage_rows,
    is_displayable_stage,
    lab_stages_metadata_issues,
    module_key_from_project,
)


WORKFLOW_DRY_RUN_SCHEMA = "agilab.workflow_dry_run_report.v1"
SUPPORTED_LAB_STAGES_VERSION = LAB_STAGES_SCHEMA_VERSION
SUPPORTED_ENGINES = {"", "runpy", "agi.run", "agi.install"}
ROLE_KEYS = ("NB_RUNTIME_ROLE", "AGILAB_RUNTIME_ROLE", "runtime_role", "role")
DANGEROUS_CALL_NAMES = {
    "eval",
    "exec",
    "os.system",
    "subprocess.call",
    "subprocess.Popen",
    "subprocess.run",
}


@dataclass(frozen=True)
class WorkflowIssue:
    severity: str
    check_id: str
    message: str
    stage_id: str = ""
    path: str = ""
    hint: str = ""

    def as_dict(self) -> dict[str, str]:
        payload = {
            "severity": self.severity,
            "check_id": self.check_id,
            "message": self.message,
        }
        if self.stage_id:
            payload["stage_id"] = self.stage_id
        if self.path:
            payload["path"] = self.path
        if self.hint:
            payload["hint"] = self.hint
        return payload


@dataclass(frozen=True)
class StageContract:
    stage_id: str
    source_key: str
    index: int
    label: str
    kind: str
    engine: str
    runtime_role: str
    app: str
    code_sha256: str
    depends_on: tuple[str, ...]
    consumes: tuple[str, ...]
    produces: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.stage_id,
            "source_key": self.source_key,
            "index": self.index,
            "label": self.label,
            "kind": self.kind,
            "engine": self.engine,
            "runtime_role": self.runtime_role,
            "app": self.app,
            "code_sha256": self.code_sha256,
            "depends_on": list(self.depends_on),
            "consumes": list(self.consumes),
            "produces": list(self.produces),
        }


def validate_lab_stages_file(
    stages_file: Path,
    *,
    apps_root: Path | None = None,
    repo_root: Path | None = None,
    module_key: str | None = None,
    require_metadata: bool = False,
) -> dict[str, Any]:
    """Validate a workflow contract without executing stage code."""
    stages_file = stages_file.expanduser()
    root = repo_root or _repo_root_from(stages_file)
    resolved_module_key = (
        str(module_key).strip()
        if module_key is not None
        else module_key_from_project(stages_file.parent)
    )
    report: dict[str, Any] = {
        "schema": WORKFLOW_DRY_RUN_SCHEMA,
        "status": "fail",
        "mode": "static_dry_run",
        "stages_file": str(stages_file),
        "module_key": resolved_module_key,
        "summary": {
            "stage_count": 0,
            "dependency_count": 0,
            "artifact_produced_count": 0,
            "artifact_consumed_count": 0,
            "external_input_count": 0,
            "error_count": 0,
            "warning_count": 0,
            "info_count": 0,
        },
        "stages": [],
        "dependency_edges": [],
        "artifact_edges": [],
        "external_inputs": [],
        "issues": [],
    }
    issues: list[WorkflowIssue] = []
    if not stages_file.is_file():
        issues.append(
            WorkflowIssue(
                "error",
                "stages-file-missing",
                f"Workflow stages file does not exist: {stages_file}",
                path=str(stages_file),
                hint="Create or export a lab_stages.toml file before validating the workflow.",
            )
        )
        _finalize_report(report, issues)
        return report

    try:
        payload = tomllib.loads(stages_file.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        issues.append(
            WorkflowIssue(
                "error",
                "stages-file-unreadable",
                f"Could not read lab_stages.toml: {exc}",
                path=str(stages_file),
            )
        )
        _finalize_report(report, issues)
        return report

    if not isinstance(payload, dict):
        issues.append(WorkflowIssue("error", "stages-file-shape", "lab_stages.toml must decode to a TOML table."))
        _finalize_report(report, issues)
        return report

    issues.extend(_metadata_issues(payload, require_metadata=require_metadata))
    unexpected_stage_keys = sorted(
        str(key)
        for key, value in payload.items()
        if str(key) not in {"__meta__", resolved_module_key}
        and isinstance(value, list)
    )
    if unexpected_stage_keys:
        issues.append(
            WorkflowIssue(
                "error",
                "unexpected-stage-lists",
                (
                    "lab_stages.toml contains stage lists WORKFLOW will ignore: "
                    f"{unexpected_stage_keys!r}."
                ),
                path=str(stages_file),
                hint=(
                    f"Reconcile those entries under {resolved_module_key!r}, then remove "
                    "the stale lists; AGILAB will not delete user-owned stages automatically."
                ),
            )
        )
    module_entries = payload.get(resolved_module_key)
    if isinstance(module_entries, list):
        undisplayable_indices = [
            index
            for index, entry in enumerate(module_entries)
            if not is_displayable_stage(entry)
        ]
        if undisplayable_indices:
            issues.append(
                WorkflowIssue(
                    "error",
                    "undisplayable-stages",
                    (
                        "WORKFLOW would prune stage entries at indices "
                        f"{undisplayable_indices!r} under {resolved_module_key!r}."
                    ),
                    path=str(stages_file),
                    hint="Give every stage a non-empty Q or C field.",
                )
            )
    raw_stages = _extract_stage_entries(payload, resolved_module_key)
    if not raw_stages:
        entries = payload.get(resolved_module_key)
        if not isinstance(entries, list):
            available_keys = sorted(
                str(key) for key in payload if str(key) != "__meta__"
            )
            issues.append(
                WorkflowIssue(
                    "error",
                    "module-key-missing" if available_keys else "no-stages",
                    (
                        "No workflow stage list exists under the module key "
                        f"{resolved_module_key!r}; found {available_keys!r}."
                        if available_keys
                        else "No workflow stages were found in lab_stages.toml."
                    ),
                    path=str(stages_file),
                    hint=(
                        f"Store stages under [[{resolved_module_key}]]; WORKFLOW does "
                        "not render generic [[stages]] or [[steps]] tables."
                    ),
                )
            )
        else:
            issues.append(
                WorkflowIssue(
                    "error",
                    "no-displayable-stages",
                    (
                        f"No displayable workflow stages were found under "
                        f"{resolved_module_key!r}."
                    ),
                    path=str(stages_file),
                    hint="Give each stage a non-empty Q or C field so WORKFLOW keeps it.",
                )
            )
        _finalize_report(report, issues)
        return report

    stage_contracts: list[StageContract] = []
    for source_key, index, entry in raw_stages:
        stage, stage_issues = _stage_contract(
            entry,
            source_key=source_key,
            index=index,
            stages_file=stages_file,
            apps_root=apps_root,
            repo_root=root,
        )
        stage_contracts.append(stage)
        issues.extend(stage_issues)

    issues.extend(_graph_issues(stage_contracts))
    report["stages"] = [stage.as_dict() for stage in stage_contracts]
    report["dependency_edges"] = _dependency_edges(stage_contracts)
    report["artifact_edges"] = _artifact_edges(stage_contracts)
    report["external_inputs"] = _external_inputs(stage_contracts)
    report["summary"].update(
        {
            "stage_count": len(stage_contracts),
            "dependency_count": len(report["dependency_edges"]),
            "artifact_produced_count": sum(len(stage.produces) for stage in stage_contracts),
            "artifact_consumed_count": sum(len(stage.consumes) for stage in stage_contracts),
            "external_input_count": len(report["external_inputs"]),
        }
    )
    _finalize_report(report, issues)
    return report


def _metadata_issues(
    payload: Mapping[str, Any],
    *,
    require_metadata: bool = False,
) -> list[WorkflowIssue]:
    hint = (
        f"Add [__meta__] schema = {LAB_STAGES_SCHEMA!r}, "
        f"version = {SUPPORTED_LAB_STAGES_VERSION}."
    )
    return [
        WorkflowIssue(
            issue.severity,
            issue.check_id,
            issue.message,
            hint=hint if issue.check_id == "metadata-missing" else "",
        )
        for issue in lab_stages_metadata_issues(
            payload,
            require_metadata=require_metadata,
        )
    ]


def _extract_stage_entries(
    payload: Mapping[str, Any],
    module_key: str,
) -> list[tuple[str, int, Mapping[str, Any]]]:
    """Return exactly the rows the WORKFLOW page keeps for ``module_key``."""

    return displayable_stage_rows(payload, module_key)


def _stage_contract(
    entry: Mapping[str, Any],
    *,
    source_key: str,
    index: int,
    stages_file: Path,
    apps_root: Path | None,
    repo_root: Path | None,
) -> tuple[StageContract, list[WorkflowIssue]]:
    explicit_id = _text(entry.get("id"))
    stage_id = explicit_id or f"{_slug(source_key)}_{index + 1:03d}"
    code = _text(entry.get("C"))
    code_facts, issues = _code_facts(code, stage_id=stage_id, path=str(stages_file))
    label = _text(entry.get("label")) or _text(entry.get("D")) or _first_line(entry.get("Q")) or stage_id
    engine = _text(entry.get("R")).lower()
    kind = _text(entry.get("kind")) or _engine_kind(engine)
    app = _text(entry.get("app")) or code_facts["app"] or _text(entry.get("APP"))
    runtime_role = _runtime_role(entry, code_facts)
    produces = _unique_texts(
        [
            *_items(entry.get("produces")),
            *_items(entry.get("outputs")),
            *code_facts["produces"],
        ]
    )
    consumes = _unique_texts(
        [
            *_items(entry.get("consumes")),
            *_items(entry.get("uses")),
            *_items(entry.get("inputs")),
            *code_facts["consumes"],
        ]
    )
    depends_on = tuple(_unique_texts(_items(entry.get("depends_on"))))

    if not explicit_id and source_key == "stages":
        issues.append(
            WorkflowIssue(
                "warning",
                "stage-id-missing",
                "Stage has no explicit id; generated ids are stable only while order is unchanged.",
                stage_id=stage_id,
                path=str(stages_file),
                hint="Add id = \"...\" to make dependency and evidence references durable.",
            )
        )
    if engine not in SUPPORTED_ENGINES:
        issues.append(
            WorkflowIssue(
                "warning",
                "stage-engine-unknown",
                f"Stage engine {engine!r} is not a standard AGILAB dry-run engine.",
                stage_id=stage_id,
                path=str(stages_file),
                hint="Use runpy, agi.run, or agi.install when the stage is meant to be executable.",
            )
        )
    if code.strip() and not runtime_role:
        issues.append(
            WorkflowIssue(
                "info",
                "runtime-role-missing",
                "Stage has code but no explicit manager/worker role metadata.",
                stage_id=stage_id,
                path=str(stages_file),
                hint="Notebook imports can set NB_RUNTIME_ROLE to manager, worker, or analysis.",
            )
        )
    if app and not _app_exists(app, apps_root=apps_root, repo_root=repo_root, stages_file=stages_file):
        issues.append(
            WorkflowIssue(
                "warning",
                "app-reference-missing",
                f"Referenced app project was not found locally: {app}",
                stage_id=stage_id,
                path=str(stages_file),
                hint="Pass --apps-root or install the app before executing this workflow.",
            )
        )
    code_sha256 = hashlib.sha256(code.encode("utf-8")).hexdigest() if code else ""
    return (
        StageContract(
            stage_id=stage_id,
            source_key=source_key,
            index=index,
            label=label,
            kind=kind,
            engine=engine or "runpy",
            runtime_role=runtime_role or "unspecified",
            app=app,
            code_sha256=code_sha256,
            depends_on=depends_on,
            consumes=tuple(consumes),
            produces=tuple(produces),
        ),
        issues,
    )


def _code_facts(code: str, *, stage_id: str, path: str) -> tuple[dict[str, Any], list[WorkflowIssue]]:
    facts: dict[str, Any] = {"app": "", "consumes": [], "produces": [], "role": ""}
    issues: list[WorkflowIssue] = []
    if not code.strip():
        return facts, issues
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        issues.append(
            WorkflowIssue(
                "error",
                "stage-code-syntax",
                f"Stage code is not valid Python: {exc.msg}",
                stage_id=stage_id,
                path=path,
            )
        )
        return facts, issues

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            name, value = _assignment_name_value(node)
            if name == "APP":
                facts["app"] = _expr_to_text(value)
            elif name in {"data_in", "input_path", "source_path"}:
                facts["consumes"].append(_expr_to_text(value))
            elif name in {"data_out", "output_path", "artifact_path"}:
                facts["produces"].append(_expr_to_text(value))
            elif name in ROLE_KEYS:
                facts["role"] = _expr_to_text(value).lower()
        elif isinstance(node, ast.Call):
            call_name = _call_name(node)
            if call_name in DANGEROUS_CALL_NAMES:
                issues.append(
                    WorkflowIssue(
                        "warning",
                        "stage-code-risky-call",
                        f"Stage contains a risky call for dry-run review: {call_name}",
                        stage_id=stage_id,
                        path=path,
                        hint="Review isolation and secrets before executing imported or generated code.",
                    )
                )
            if call_name not in {"AGI.run", "AGI.install"}:
                continue
            for keyword in node.keywords:
                if not keyword.arg:
                    continue
                value = _expr_to_text(keyword.value)
                if keyword.arg == "data_in":
                    facts["consumes"].append(value)
                elif keyword.arg == "data_out":
                    facts["produces"].append(value)
                elif keyword.arg in ROLE_KEYS:
                    facts["role"] = value.lower()
    facts["consumes"] = _unique_texts(facts["consumes"])
    facts["produces"] = _unique_texts(facts["produces"])
    return facts, issues


def _assignment_name_value(node: ast.Assign | ast.AnnAssign) -> tuple[str, ast.AST]:
    if isinstance(node, ast.AnnAssign):
        return (node.target.id if isinstance(node.target, ast.Name) else "", node.value or ast.Constant(""))
    for target in node.targets:
        if isinstance(target, ast.Name):
            return target.id, node.value
    return "", node.value


def _expr_to_text(node: ast.AST) -> str:
    try:
        if isinstance(node, ast.Constant):
            return str(node.value if node.value is not None else "")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left = _expr_to_text(node.left)
            right = _expr_to_text(node.right)
            return " / ".join(part for part in (left, right) if part)
        if isinstance(node, (ast.List, ast.Tuple)):
            return ",".join(_expr_to_text(item) for item in node.elts if _expr_to_text(item))
        return ast.unparse(node).strip()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return ""


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        prefix = _call_attribute_prefix(func.value)
        return f"{prefix}.{func.attr}" if prefix else func.attr
    return ""


def _call_attribute_prefix(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_attribute_prefix(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _runtime_role(entry: Mapping[str, Any], code_facts: Mapping[str, Any]) -> str:
    for key in ROLE_KEYS:
        value = _text(entry.get(key))
        if value:
            return value.lower()
    return _text(code_facts.get("role")).lower()


def _graph_issues(stages: Sequence[StageContract]) -> list[WorkflowIssue]:
    issues: list[WorkflowIssue] = []
    seen_ids: dict[str, str] = {}
    for stage in stages:
        if stage.stage_id in seen_ids:
            issues.append(
                WorkflowIssue(
                    "error",
                    "stage-id-duplicate",
                    f"Duplicate stage id: {stage.stage_id}",
                    stage_id=stage.stage_id,
                    hint="Stage ids must be unique for dependency and evidence graph references.",
                )
            )
        seen_ids[stage.stage_id] = stage.stage_id

    stage_ids = {stage.stage_id for stage in stages}
    stage_index = {stage.stage_id: index for index, stage in enumerate(stages)}
    for stage in stages:
        for dependency in stage.depends_on:
            if dependency not in stage_ids:
                issues.append(
                    WorkflowIssue(
                        "error",
                        "dependency-missing",
                        f"Stage depends on unknown stage: {dependency}",
                        stage_id=stage.stage_id,
                    )
                )
            elif stage_index[dependency] > stage_index[stage.stage_id]:
                issues.append(
                    WorkflowIssue(
                        "warning",
                        "dependency-forward-reference",
                        f"Stage depends on a later stage: {dependency}",
                        stage_id=stage.stage_id,
                        hint="Keep dependency producers before consumers for readable workflow reviews.",
                    )
                )
    issues.extend(_cycle_issues(stages))
    issues.extend(_artifact_collision_issues(stages))
    return issues


def _cycle_issues(stages: Sequence[StageContract]) -> list[WorkflowIssue]:
    by_id = {stage.stage_id: stage for stage in stages}
    visiting: set[str] = set()
    visited: set[str] = set()
    issues: list[WorkflowIssue] = []

    def visit(stage_id: str, stack: tuple[str, ...]) -> None:
        if stage_id in visited:
            return
        if stage_id in visiting:
            cycle = " -> ".join((*stack, stage_id))
            issues.append(WorkflowIssue("error", "dependency-cycle", f"Workflow dependency cycle detected: {cycle}"))
            return
        visiting.add(stage_id)
        stage = by_id.get(stage_id)
        if stage:
            for dependency in stage.depends_on:
                if dependency in by_id:
                    visit(dependency, (*stack, stage_id))
        visiting.discard(stage_id)
        visited.add(stage_id)

    for stage in stages:
        visit(stage.stage_id, ())
    return issues


def _artifact_collision_issues(stages: Sequence[StageContract]) -> list[WorkflowIssue]:
    producers: dict[str, str] = {}
    issues: list[WorkflowIssue] = []
    for stage in stages:
        for artifact in stage.produces:
            previous = producers.get(artifact)
            if previous:
                issues.append(
                    WorkflowIssue(
                        "warning",
                        "artifact-produced-twice",
                        f"Artifact {artifact!r} is produced by both {previous} and {stage.stage_id}.",
                        stage_id=stage.stage_id,
                        hint="Use distinct artifact ids or make overwrite semantics explicit.",
                    )
                )
            producers[artifact] = stage.stage_id
    return issues


def _dependency_edges(stages: Sequence[StageContract]) -> list[dict[str, str]]:
    edges = [
        {"source": dependency, "target": stage.stage_id, "kind": "depends_on"}
        for stage in stages
        for dependency in stage.depends_on
    ]
    return sorted(edges, key=lambda row: (row["source"], row["target"], row["kind"]))


def _artifact_edges(stages: Sequence[StageContract]) -> list[dict[str, str]]:
    producers: dict[str, str] = {}
    for stage in stages:
        for artifact in stage.produces:
            producers.setdefault(artifact, stage.stage_id)
    edges = [
        {
            "source": producers[artifact],
            "target": stage.stage_id,
            "artifact": artifact,
            "kind": "artifact_flow",
        }
        for stage in stages
        for artifact in stage.consumes
        if artifact in producers and producers[artifact] != stage.stage_id
    ]
    return sorted(edges, key=lambda row: (row["source"], row["target"], row["artifact"]))


def _external_inputs(stages: Sequence[StageContract]) -> list[dict[str, str]]:
    produced = {artifact for stage in stages for artifact in stage.produces}
    rows = [
        {"stage_id": stage.stage_id, "artifact": artifact, "kind": "external_input"}
        for stage in stages
        for artifact in stage.consumes
        if artifact and artifact not in produced
    ]
    return sorted(rows, key=lambda row: (row["stage_id"], row["artifact"]))


def _finalize_report(report: dict[str, Any], issues: Sequence[WorkflowIssue]) -> None:
    issue_dicts = [issue.as_dict() for issue in issues]
    error_count = sum(1 for issue in issues if issue.severity == "error")
    warning_count = sum(1 for issue in issues if issue.severity == "warning")
    info_count = sum(1 for issue in issues if issue.severity == "info")
    report["issues"] = issue_dicts
    report["summary"]["error_count"] = error_count
    report["summary"]["warning_count"] = warning_count
    report["summary"]["info_count"] = info_count
    report["status"] = "fail" if error_count else "warn" if warning_count else "pass"


def _items(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, Mapping):
        for key in ("artifact", "id", "path", "name"):
            value = _text(raw.get(key))
            if value:
                return [value]
        return []
    if isinstance(raw, Sequence) and not isinstance(raw, (bytes, bytearray)):
        result: list[str] = []
        for item in raw:
            result.extend(_items(item))
        return result
    return [str(raw).strip()] if str(raw).strip() else []


def _unique_texts(values: Sequence[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first_line(value: Any) -> str:
    for line in _text(value).splitlines():
        if line.strip():
            return line.strip()
    return ""


def _engine_kind(engine: str) -> str:
    if engine == "agi.install":
        return "install"
    if engine == "agi.run":
        return "run"
    if engine == "runpy":
        return "python"
    return "stage"


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("_.-")
    return slug or "stage"


def _repo_root_from(path: Path) -> Path | None:
    for candidate in (path.parent, *path.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "agilab").is_dir():
            return candidate
    return None


def _app_exists(
    app: str,
    *,
    apps_root: Path | None,
    repo_root: Path | None,
    stages_file: Path,
) -> bool:
    candidates: list[Path] = []
    if apps_root is not None:
        candidates.append(apps_root.expanduser() / app)
    if repo_root is not None:
        candidates.append(repo_root / "src" / "agilab" / "apps" / "builtin" / app)
        candidates.append(repo_root / "src" / "agilab" / "apps" / app)
    candidates.append(stages_file.parent)
    return any(candidate.name == app and candidate.exists() for candidate in candidates)


def _json_dump(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def _text_report(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {})
    summary = summary if isinstance(summary, Mapping) else {}
    lines = [
        f"status: {report.get('status', 'unknown')}",
        (
            "stages: "
            f"{summary.get('stage_count', 0)}; "
            f"dependencies: {summary.get('dependency_count', 0)}; "
            f"artifact flows: {len(report.get('artifact_edges', []) or [])}; "
            f"external inputs: {summary.get('external_input_count', 0)}"
        ),
    ]
    for issue in report.get("issues", []) or []:
        if not isinstance(issue, Mapping):
            continue
        stage = f" [{issue.get('stage_id')}]" if issue.get("stage_id") else ""
        lines.append(f"{issue.get('severity', 'info')}: {issue.get('check_id', 'check')}{stage}: {issue.get('message', '')}")
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    validate = subparsers.add_parser("validate", help="Validate lab_stages.toml without executing code.")
    validate.add_argument("stages_file", nargs="?", default="lab_stages.toml")
    validate.add_argument("--dry-run", action="store_true", help="Accepted for explicitness; validation is always static.")
    validate.add_argument("--apps-root", default=None, help="Optional apps directory used to check APP references.")
    validate.add_argument("--repo-root", default=None, help="Optional source checkout root used to check built-in apps.")
    validate.add_argument(
        "--module-key",
        default=None,
        help="Expected WORKFLOW module key. Defaults to the stages file parent directory.",
    )
    validate.add_argument(
        "--require-metadata",
        action="store_true",
        help="Reject legacy files that omit the __meta__ schema table.",
    )
    validate.add_argument("--json", action="store_true", help="Print the full machine-readable report.")
    validate.add_argument("--strict", action="store_true", help="Return non-zero when warnings are present.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if not raw_args or raw_args[0] != "validate":
        raw_args = ["validate", *raw_args]
    args = parser.parse_args(raw_args)
    command = args.command
    if command != "validate":
        parser.error(f"unsupported command: {command}")
    stages_file = Path(args.stages_file)
    report = validate_lab_stages_file(
        stages_file,
        apps_root=Path(args.apps_root) if args.apps_root else None,
        repo_root=Path(args.repo_root) if args.repo_root else None,
        module_key=args.module_key,
        require_metadata=args.require_metadata,
    )
    print(_json_dump(report) if args.json else _text_report(report), end="")
    if report["status"] == "fail":
        return 2
    if report["status"] == "warn" and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
