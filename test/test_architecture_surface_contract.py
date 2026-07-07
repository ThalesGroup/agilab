from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

MID_LAYER_MODULE_LINE_BUDGETS = {
    "src/agilab/pipeline/pipeline_lab.py": 6200,
    "src/agilab/notebooks/notebook_export_support.py": 3100,
    "src/agilab/orchestrate/orchestrate_page_support.py": 2050,
}


def test_large_mid_layer_support_modules_do_not_grow_without_decomposition() -> None:
    violations: list[str] = []
    for rel_path, budget in MID_LAYER_MODULE_LINE_BUDGETS.items():
        path = REPO_ROOT / rel_path
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > budget:
            violations.append(f"{rel_path}: {line_count} lines > budget {budget}")

    assert violations == []
