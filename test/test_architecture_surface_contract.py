from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

# These budgets ratchet against unplanned growth in the large mid-layer support
# modules. They are not targets: raising one is a deliberate act that belongs in
# the change that needs it, with the reason recorded here.
#
# Raised 2026-07-27 after both files sat over budget on `main` since 2026-07-15,
# which had left this guard failing and therefore ignored. Growth came from two
# changes that did not adjust the budgets:
#   1175660 (#807, notebook import/export round-trip fidelity and safety)
#     notebook_export_support 3059 -> 3577, pipeline_lab 6194 -> 6221
#   7ec856f (harden concurrent runtime access)
#     notebook_export_support -> 3592, pipeline_lab -> 6318
# Both remain decomposition candidates; raising the ceiling records the current
# size honestly rather than pretending the older number still holds.
#
# Lowered 2026-07-27 for notebook_export_support, 3700 -> 2450, after the
# ~1250-line `_helper_cell` template moved to notebook_helper_cell.py. The module
# is 2334 lines, below even the 3100 ceiling that predated #807. A budget only
# ratchets if it tracks reality downward too, so paying the debt reclaims the
# ceiling instead of leaving the headroom to be silently refilled.
#
# notebook_helper_cell.py is deliberately unbudgeted: it is emitted source for
# exported notebooks, and its size reflects the generated runtime rather than
# control flow anyone reads top to bottom.
MID_LAYER_MODULE_LINE_BUDGETS = {
    "src/agilab/pipeline/pipeline_lab.py": 6400,
    "src/agilab/notebooks/notebook_export_support.py": 2450,
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
