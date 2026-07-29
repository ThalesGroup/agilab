"""Guard built-in manifests against the exact WORKFLOW renderer contract."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from agilab.workflow.workflow_validation import validate_lab_stages_file


BUILTIN_ROOT = Path(__file__).resolve().parents[1] / "src" / "agilab" / "apps" / "builtin"
META_KEY = "__meta__"
CONCEPTUAL_ONLY_PROJECTS = {
    "data_quality_gate_project",
    "r_runtime_bridge_project",
    "sklearn_pipeline_project",
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

    module_key = _module_key(stage_file.parent)
    payload = tomllib.loads(stage_file.read_text(encoding="utf-8"))
    entries = payload.get(module_key)

    assert isinstance(entries, list) and entries, (
        f"{stage_file.parent.name}/lab_stages.toml must expose its stages under the module key "
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

    module_key = _module_key(stage_file.parent)
    payload = tomllib.loads(stage_file.read_text(encoding="utf-8"))
    entries = payload.get(module_key)
    assert isinstance(entries, list), (
        f"{stage_file.parent.name}/lab_stages.toml has no {module_key!r} table; "
        "test_builtin_lab_stages_use_the_module_key explains why."
    )

    undisplayable = [
        index
        for index, entry in enumerate(entries)
        if not str(entry.get("Q") or "").strip() and not str(entry.get("C") or "").strip()
    ]
    assert not undisplayable, (
        f"{stage_file.parent.name}/lab_stages.toml entries {undisplayable} have neither Q nor C; "
        "prune_invalid_entries drops them and the WORKFLOW editor deletes them "
        "permanently on the next save."
    )


@pytest.mark.parametrize(
    "stage_file", _stage_files(), ids=lambda path: path.parent.name
)
def test_builtin_lab_stages_have_schema_metadata(stage_file: Path) -> None:
    payload = tomllib.loads(stage_file.read_text(encoding="utf-8"))

    assert payload.get(META_KEY) == {
        "schema": "agilab.lab_stages.v1",
        "version": 1,
    }


@pytest.mark.parametrize(
    "stage_file", _stage_files(), ids=lambda path: path.parent.name
)
def test_builtin_lab_stages_pass_the_shared_strict_validator(
    stage_file: Path,
) -> None:
    report = validate_lab_stages_file(
        stage_file,
        apps_root=BUILTIN_ROOT,
        repo_root=BUILTIN_ROOT.parents[3],
        module_key=_module_key(stage_file.parent),
        require_metadata=True,
    )

    assert report["status"] == "pass", report["issues"]


@pytest.mark.parametrize("project", sorted(CONCEPTUAL_ONLY_PROJECTS))
def test_conceptual_only_apps_ship_dot_without_executable_stages(project: str) -> None:
    project_root = BUILTIN_ROOT / project
    dot = project_root / "pipeline_view.dot"

    assert not (project_root / "lab_stages.toml").exists()
    assert dot.is_file()
    assert dot.read_text(encoding="utf-8").strip().startswith("digraph ")
