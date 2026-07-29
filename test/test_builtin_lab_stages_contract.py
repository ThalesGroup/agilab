"""Guard the one lab_stages.toml property the app contract matrix never checks.

``tools/app_contract_matrix.py`` asserts that a built-in app's ``lab_stages.toml``
parses and is non-empty. It never checks the property that decides whether the
WORKFLOW page shows anything: the top-level table key must equal the app's module
key, because ``3_WORKFLOW.py::_read_stages`` is a strict ``data.get(module_key, [])``
with no fallback. A file keyed ``[[stages]]`` or ``[[steps]]`` yields ``[]`` and the
page renders empty, silently -- no error, no warning, no log line.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest


BUILTIN_ROOT = Path(__file__).resolve().parents[1] / "src" / "agilab" / "apps" / "builtin"
META_KEY = "__meta__"

# Apps whose stage file predates this contract and does not satisfy it yet.
# Each entry is a documented debt, not a permitted shape: the file is a design
# manifest (``id``/``label``/``kind``/``depends_on``/``produces``) that was written
# into the executable contract's filename, so no entry is even displayable and a
# key rename alone would not fix it. Removing an app from this list is the fix;
# adding one is not allowed -- author the stages, or ship the decomposition as
# ``pipeline_view.dot`` instead.
KNOWN_UNRENDERABLE = {
    "data_quality_gate_project",
    "r_runtime_bridge_project",
    "sklearn_pipeline_project",
    "tescia_diagnostic_project",
}


def _module_key(project_dir: Path) -> str:
    name = project_dir.name
    return name[: -len("_project")] if name.endswith("_project") else name


def _stage_files() -> list[Path]:
    return sorted(BUILTIN_ROOT.glob("*/lab_stages.toml"))


def test_builtin_stage_files_are_discoverable() -> None:
    """The glob must find files, otherwise every test below passes vacuously."""

    assert _stage_files(), f"no built-in lab_stages.toml found under {BUILTIN_ROOT}"


@pytest.mark.parametrize(
    "stage_file", _stage_files(), ids=lambda path: path.parent.name
)
def test_builtin_lab_stages_use_the_module_key(stage_file: Path) -> None:
    """The WORKFLOW page looks the payload up by module key and nothing else."""

    project = stage_file.parent.name
    module_key = _module_key(stage_file.parent)
    payload = tomllib.loads(stage_file.read_text(encoding="utf-8"))
    entries = payload.get(module_key)

    if project in KNOWN_UNRENDERABLE:
        pytest.xfail(f"{project} ships a design manifest, not a stage contract")

    assert isinstance(entries, list) and entries, (
        f"{project}/lab_stages.toml must expose its stages under the module key "
        f"{module_key!r}; found top-level keys "
        f"{sorted(k for k in payload if k != META_KEY)!r}. "
        "The WORKFLOW page reads data.get(module_key, []) with no fallback, so any "
        "other key renders an empty page."
    )


@pytest.mark.parametrize(
    "stage_file", _stage_files(), ids=lambda path: path.parent.name
)
def test_builtin_lab_stages_entries_are_displayable(stage_file: Path) -> None:
    """Every entry needs a non-empty Q or C or prune_invalid_entries drops it."""

    project = stage_file.parent.name
    if project in KNOWN_UNRENDERABLE:
        pytest.xfail(f"{project} ships a design manifest, not a stage contract")

    module_key = _module_key(stage_file.parent)
    payload = tomllib.loads(stage_file.read_text(encoding="utf-8"))
    entries = payload.get(module_key)
    assert isinstance(entries, list), (
        f"{project}/lab_stages.toml has no {module_key!r} table; "
        "test_builtin_lab_stages_use_the_module_key explains why."
    )

    undisplayable = [
        index
        for index, entry in enumerate(entries)
        if not str(entry.get("Q") or "").strip() and not str(entry.get("C") or "").strip()
    ]
    assert not undisplayable, (
        f"{project}/lab_stages.toml entries {undisplayable} have neither Q nor C; "
        "prune_invalid_entries drops them and the WORKFLOW editor deletes them "
        "permanently on the next save."
    )


def test_known_unrenderable_list_stays_closed() -> None:
    """The debt list may shrink, never grow, and must not name a missing app."""

    present = {path.parent.name for path in _stage_files()}
    stale = KNOWN_UNRENDERABLE - present
    assert not stale, (
        f"KNOWN_UNRENDERABLE names apps with no lab_stages.toml: {sorted(stale)}. "
        "Drop them from the list."
    )
    assert len(KNOWN_UNRENDERABLE) <= 4, (
        "KNOWN_UNRENDERABLE grew. A new built-in app must ship a renderable "
        "lab_stages.toml, or ship its decomposition as pipeline_view.dot and no "
        "lab_stages.toml at all."
    )
