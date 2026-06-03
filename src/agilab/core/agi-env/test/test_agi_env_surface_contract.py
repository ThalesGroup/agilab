"""Surface-size guardrails for the AgiEnv compatibility module."""

import ast
from pathlib import Path


AGI_ENV_MAX_LINES = 1000
AGI_ENV_IMPORT_ALIAS_BUDGET = 30
AGI_ENV_INIT_FUNCTION_BUDGET = 100


def test_agi_env_module_stays_below_review_surface_budget() -> None:
    agi_env_module = Path(__file__).resolve().parents[1] / "src" / "agi_env" / "agi_env.py"
    source = agi_env_module.read_text(encoding="utf-8")

    assert len(source.splitlines()) <= AGI_ENV_MAX_LINES
    assert _import_alias_count(source) <= AGI_ENV_IMPORT_ALIAS_BUDGET


def test_agi_env_initialization_phases_stay_reviewable() -> None:
    init_module = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "agi_env"
        / "agi_env_instance_initialization.py"
    )
    offenders = _function_lengths_over_budget(
        init_module.read_text(encoding="utf-8"),
        max_lines=AGI_ENV_INIT_FUNCTION_BUDGET,
    )

    assert offenders == {}


def _import_alias_count(source: str) -> int:
    module = ast.parse(source)
    count = 0
    for node in module.body:
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        count += sum(1 for alias in node.names if alias.asname)
    return count


def _function_lengths_over_budget(source: str, *, max_lines: int) -> dict[str, int]:
    module = ast.parse(source)
    offenders: dict[str, int] = {}
    for node in ast.walk(module):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.end_lineno is None:
            continue
        line_count = node.end_lineno - node.lineno + 1
        if line_count > max_lines:
            offenders[node.name] = line_count
    return offenders
