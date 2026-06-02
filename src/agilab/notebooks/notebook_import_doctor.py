from __future__ import annotations

import ast
import builtins
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .notebook_pipeline_import import build_notebook_pipeline_import, load_notebook


SCHEMA = "agilab.notebook_import_doctor.v1"
DEFAULT_RUN_ID = "notebook-import-doctor"
READ_METHODS = {
    "load",
    "read_csv",
    "read_excel",
    "read_feather",
    "read_json",
    "read_parquet",
    "read_pickle",
    "read_table",
    "read_text",
}
WRITE_METHODS = {
    "dump",
    "save",
    "savefig",
    "to_csv",
    "to_excel",
    "to_feather",
    "to_json",
    "to_parquet",
    "to_pickle",
    "write_bytes",
    "write_text",
}
IPYTHON_GLOBALS = {
    "display",
    "get_ipython",
}


@dataclass(frozen=True)
class NotebookImportDoctorIssue:
    level: str
    code: str
    location: str
    message: str
    suggestion: str = ""
    evidence: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "location": self.location,
            "message": self.message,
            "suggestion": self.suggestion,
            "evidence": list(self.evidence),
        }


def diagnose_notebook_file(
    path: Path,
    *,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    notebook_path = path.expanduser()
    return diagnose_notebook(
        load_notebook(notebook_path),
        source_notebook=notebook_path,
        run_id=run_id,
    )


def diagnose_notebook(
    notebook: Mapping[str, Any],
    *,
    source_notebook: Path | str = "notebook.ipynb",
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    notebook_import = build_notebook_pipeline_import(
        notebook=notebook,
        source_notebook=source_notebook,
        run_id=run_id,
    )
    raw_steps = notebook_import.get("pipeline_stages", notebook_import.get("pipeline_steps", []))
    steps = [step for step in raw_steps if isinstance(step, dict)]
    cell_reports: list[dict[str, Any]] = []
    issues: list[NotebookImportDoctorIssue] = []
    cumulative_defs: dict[str, str] = {}
    artifact_inputs: set[str] = set()
    artifact_outputs: set[str] = set()
    artifact_ambiguous: set[str] = set()
    execution_counts: list[int | None] = []

    for step in steps:
        cell_report = _diagnose_step(step, cumulative_defs)
        cell_reports.append(cell_report)
        cumulative_defs.update({name: str(step.get("id", "")) for name in cell_report["defines"]})
        issues.extend(cell_report["issues"])
        artifact_inputs.update(cell_report["artifact_contract"]["inputs"])
        artifact_outputs.update(cell_report["artifact_contract"]["outputs"])
        artifact_ambiguous.update(cell_report["artifact_contract"]["ambiguous"])
        execution_counts.append(cell_report["execution_count"])

    all_artifacts = {
        str(reference.get("path", ""))
        for reference in notebook_import.get("artifact_references", [])
        if isinstance(reference, dict) and str(reference.get("path", ""))
    }
    artifact_ambiguous.update(all_artifacts - artifact_inputs - artifact_outputs)
    issues.extend(_execution_count_issues(execution_counts))
    issues.extend(_scratch_cell_issues(cell_reports))
    readiness_score = _readiness_score(issues)
    status = "fail" if any(issue.level == "error" for issue in issues) else "warn" if issues else "pass"
    issue_dicts = [issue.as_dict() for issue in issues]

    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "source_notebook": str(source_notebook),
        "status": status,
        "readiness_score": readiness_score,
        "summary": {
            "cell_count": notebook_import.get("summary", {}).get("cell_count", 0),
            "code_cell_count": len(steps),
            "issue_count": len(issues),
            "error_count": sum(1 for issue in issues if issue.level == "error"),
            "warning_count": sum(1 for issue in issues if issue.level == "warning"),
            "info_count": sum(1 for issue in issues if issue.level == "info"),
            "hidden_global_count": sum(1 for issue in issues if issue.code == "hidden_global"),
            "missing_name_count": sum(1 for issue in issues if issue.code == "missing_name"),
            "scratch_cell_count": sum(1 for issue in issues if issue.code == "scratch_cell"),
            "input_artifact_count": len(artifact_inputs),
            "output_artifact_count": len(artifact_outputs),
            "ambiguous_artifact_count": len(artifact_ambiguous),
        },
        "artifact_contract": {
            "inputs": sorted(artifact_inputs),
            "outputs": sorted(artifact_outputs),
            "ambiguous": sorted(artifact_ambiguous),
        },
        "issues": issue_dicts,
        "recommendations": _recommendations(issue_dicts),
        "cell_reports": [
            {
                **report,
                "issues": [issue.as_dict() for issue in report["issues"]],
            }
            for report in cell_reports
        ],
        "notebook_import_summary": notebook_import.get("summary", {}),
    }


def write_doctor_report(path: Path, report: Mapping[str, Any]) -> Path:
    output_path = path.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def _diagnose_step(
    step: Mapping[str, Any],
    cumulative_defs: Mapping[str, str],
) -> dict[str, Any]:
    code = "".join(str(line) for line in step.get("source_lines", []))
    cell_id = str(step.get("id", ""))
    source_cell_index = int(step.get("source_cell_index", 0) or 0)
    execution_count = step.get("execution_count")
    issues: list[NotebookImportDoctorIssue] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        issues.append(
            NotebookImportDoctorIssue(
                level="error",
                code="syntax_error",
                location=cell_id,
                message=f"Notebook cell cannot be parsed as Python: {exc.msg}",
                suggestion="Fix syntax before importing this cell into lab_steps.toml.",
                evidence=(str(source_cell_index),),
            )
        )
        return {
            "id": cell_id,
            "source_cell_index": source_cell_index,
            "execution_count": execution_count,
            "defines": [],
            "uses": [],
            "hidden_globals": [],
            "missing_names": [],
            "artifact_contract": {"inputs": [], "outputs": [], "ambiguous": []},
            "role": "invalid",
            "issues": issues,
        }

    bindings = _literal_bindings(tree)
    defines = _defined_names(tree)
    uses = _used_names(tree)
    hidden = sorted(name for name in uses if name in cumulative_defs and name not in defines)
    missing = sorted(
        name
        for name in uses
        if name not in defines
        and name not in cumulative_defs
        and name not in _builtins()
        and name not in IPYTHON_GLOBALS
    )

    if hidden:
        issues.append(
            NotebookImportDoctorIssue(
                level="warning",
                code="hidden_global",
                location=cell_id,
                message="Cell uses names defined by earlier cells instead of declaring them locally.",
                suggestion="Move imports, constants, and required setup into this AGILAB step or make them explicit inputs.",
                evidence=tuple(hidden),
            )
        )
    if missing:
        issues.append(
            NotebookImportDoctorIssue(
                level="error",
                code="missing_name",
                location=cell_id,
                message="Cell uses names that are not defined in the cell or in earlier cells.",
                suggestion="Add imports, parameters, or artifact reads before importing this cell.",
                evidence=tuple(missing),
            )
        )

    artifact_contract = _artifact_contract(tree, bindings)
    role = _cell_role(tree, artifact_contract)
    return {
        "id": cell_id,
        "source_cell_index": source_cell_index,
        "execution_count": execution_count,
        "defines": sorted(defines),
        "uses": sorted(uses),
        "hidden_globals": hidden,
        "missing_names": missing,
        "artifact_contract": artifact_contract,
        "role": role,
        "issues": issues,
    }


def _builtins() -> set[str]:
    return set(dir(builtins))


def _defined_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Param)):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
    return names


def _used_names(tree: ast.AST) -> set[str]:
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }


def _literal_bindings(tree: ast.AST) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value = _path_literal(node.value, bindings)
        if not value:
            continue
        for target in node.targets:
            for name in _target_names(target):
                bindings[name] = value
    return bindings


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for item in target.elts:
            names.extend(_target_names(item))
        return names
    return []


def _path_literal(node: ast.AST, bindings: Mapping[str, str]) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value if _looks_like_artifact(node.value) else ""
    if isinstance(node, ast.Name):
        return bindings.get(node.id, "")
    if isinstance(node, ast.Call):
        func_name = _call_name(node.func)
        if func_name in {"Path", "PurePath"} and node.args:
            return _path_literal(node.args[0], bindings)
    return ""


def _artifact_contract(tree: ast.AST, bindings: Mapping[str, str]) -> dict[str, list[str]]:
    inputs: set[str] = set()
    outputs: set[str] = set()
    ambiguous: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and _looks_like_artifact(node.value):
            ambiguous.add(node.value)
        if not isinstance(node, ast.Call):
            continue
        method = _call_method(node.func)
        if method in READ_METHODS:
            value = _call_path_argument(node, bindings)
            if value:
                inputs.add(value)
        if method in WRITE_METHODS or method.startswith("to_"):
            value = _call_output_path(node, bindings)
            if value:
                outputs.add(value)
    ambiguous -= inputs
    ambiguous -= outputs
    return {
        "inputs": sorted(inputs),
        "outputs": sorted(outputs),
        "ambiguous": sorted(ambiguous),
    }


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _call_method(func: ast.AST) -> str:
    return func.attr if isinstance(func, ast.Attribute) else _call_name(func)


def _call_path_argument(node: ast.Call, bindings: Mapping[str, str]) -> str:
    if node.args:
        value = _path_literal(node.args[0], bindings)
        if value:
            return value
    for keyword in node.keywords:
        if keyword.arg in {"path", "filepath_or_buffer", "fname"}:
            value = _path_literal(keyword.value, bindings)
            if value:
                return value
    return ""


def _call_output_path(node: ast.Call, bindings: Mapping[str, str]) -> str:
    if isinstance(node.func, ast.Attribute) and node.func.attr in {"write_text", "write_bytes"}:
        value = _path_literal(node.func.value, bindings)
        if value:
            return value
    return _call_path_argument(node, bindings)


def _looks_like_artifact(value: str) -> bool:
    path = str(value or "").strip()
    if not path:
        return False
    suffix = Path(path).suffix.lower()
    return suffix in {
        ".csv",
        ".json",
        ".parquet",
        ".png",
        ".jpg",
        ".jpeg",
        ".svg",
        ".html",
        ".txt",
        ".toml",
        ".pkl",
        ".pickle",
    }


def _cell_role(tree: ast.AST, contract: Mapping[str, Sequence[str]]) -> str:
    if contract.get("outputs"):
        return "export"
    if contract.get("inputs"):
        return "load"
    method_names = {
        _call_method(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    if method_names and method_names.issubset({"display", "head", "print"}):
        return "scratch"
    return "transform"


def _execution_count_issues(execution_counts: Sequence[int | None]) -> list[NotebookImportDoctorIssue]:
    present = [count for count in execution_counts if count is not None]
    if not present:
        return []
    issues: list[NotebookImportDoctorIssue] = []
    if len(present) != len(execution_counts):
        issues.append(
            NotebookImportDoctorIssue(
                level="warning",
                code="partial_execution_counts",
                location="notebook",
                message="Only some code cells have execution counts.",
                suggestion="Restart and run all cells before migration, or treat execution counts as stale notebook state.",
                evidence=(f"{len(present)}/{len(execution_counts)}",),
            )
        )
    if present != sorted(present):
        issues.append(
            NotebookImportDoctorIssue(
                level="warning",
                code="execution_order_risk",
                location="notebook",
                message="Execution counts do not follow notebook cell order.",
                suggestion="Restart and run cells in order before using the notebook as migration evidence.",
                evidence=tuple(str(count) for count in present),
            )
        )
    return issues


def _scratch_cell_issues(cell_reports: Sequence[Mapping[str, Any]]) -> list[NotebookImportDoctorIssue]:
    issues: list[NotebookImportDoctorIssue] = []
    for report in cell_reports:
        if report.get("role") != "scratch":
            continue
        issues.append(
            NotebookImportDoctorIssue(
                level="info",
                code="scratch_cell",
                location=str(report.get("id", "")),
                message="Cell looks like notebook-only inspection code.",
                suggestion="Drop it from the pipeline or convert it to an explicit analysis artifact.",
            )
        )
    return issues


def _readiness_score(issues: Sequence[NotebookImportDoctorIssue]) -> int:
    score = 100
    for issue in issues:
        if issue.level == "error":
            score -= 25
        elif issue.level == "warning":
            score -= 10
        elif issue.level == "info":
            score -= 2
    return max(0, score)


def _recommendations(issues: Sequence[Mapping[str, Any]]) -> list[str]:
    codes = {str(issue.get("code", "")) for issue in issues}
    recommendations: list[str] = []
    if "missing_name" in codes:
        recommendations.append("Fix undefined names before importing the notebook into AGILAB.")
    if "hidden_global" in codes:
        recommendations.append("Move imports and constants into each step or expose them as explicit AGILAB parameters.")
    if {"partial_execution_counts", "execution_order_risk"} & codes:
        recommendations.append("Restart the notebook kernel and run cells in order before migration review.")
    if "scratch_cell" in codes:
        recommendations.append("Skip scratch cells or convert useful inspection output into analysis artifacts.")
    if not recommendations:
        recommendations.append("Notebook is a good candidate for direct AGILAB pipeline import.")
    return recommendations
