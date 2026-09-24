"""Public managers preserve arguments and regenerate only stale local datasets."""

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src/agilab/apps/builtin"


@pytest.fixture
def env(tmp_path):
    share = tmp_path / "share"
    share.mkdir()

    def resolve(value):
        path = Path(value)
        return path if path.is_absolute() else share / path

    return SimpleNamespace(
        AGILAB_EXPORT_ABS=tmp_path / "export",
        AGI_LOCAL_SHARE=str(share),
        _is_managed_pc=False,
        home_abs=tmp_path,
        resolve_share_path=resolve,
        workflow_data_root=share,
        target="contract_project",
        verbose=0,
    )


@pytest.fixture(params=("data_quality_gate", "execution_polars"))
def manager_type(request, monkeypatch):
    name = request.param
    monkeypatch.syspath_prepend(str(ROOT / (name + "_project") / "src"))
    module = importlib.import_module(name)
    cls = getattr(
        module, "DataQualityGate" if name == "data_quality_gate" else "ExecutionPolars"
    )
    defaults = (
        {}
        if name == "data_quality_gate"
        else dict(n_partitions=2, rows_per_file=5, n_groups=2)
    )
    return name, module, cls, defaults


def test_manager_reports_invalid_configuration_before_creating_dataset(
    manager_type, env
):
    name, _, cls, defaults = manager_type
    with pytest.raises(ValueError, match="Invalid .* arguments"):
        cls(env, **{**defaults, "seed": "not-an-integer"})
    assert list(Path(env.AGI_LOCAL_SHARE).iterdir()) == []


def test_manager_toml_roundtrip_preserves_unrelated_settings_and_overrides(
    manager_type, env, tmp_path
):
    name, _, cls, defaults = manager_type
    manager = cls(env, **defaults)
    settings = tmp_path / "settings.toml"
    settings.write_text('[unrelated]\nkeep = "yes"\n')
    manager.to_toml(settings)
    restored = cls.from_toml(env, settings, seed=123)
    assert restored.as_dict()["seed"] == 123
    assert restored.as_dict()["data_out"] == manager.as_dict()["data_out"]
    import tomllib

    assert tomllib.loads(settings.read_text())["unrelated"] == {"keep": "yes"}


def test_manager_path_resolution_error_keeps_context(manager_type, env):
    _, _, cls, defaults = manager_type

    def reject(path):
        raise ValueError("share root denied")

    env.resolve_share_path = reject
    with pytest.raises(ValueError, match="Invalid .* path: share root denied"):
        cls(env, **defaults)


@pytest.mark.parametrize(
    "workers,expected", [(None, 1), ("invalid", 1), (0, 1), (3, 3)]
)
def test_quality_manager_dispatches_exactly_one_gate_task(
    monkeypatch, env, workers, expected
):
    monkeypatch.syspath_prepend(str(ROOT / "data_quality_gate_project/src"))
    module = importlib.import_module("data_quality_gate")
    manager = module.DataQualityGate(env, seed=11)
    plan, metadata, name, weight, unit = manager.build_distribution(workers)
    assert len(plan) == len(metadata) == expected
    assert plan[0] == [["data_quality_gate"]]
    assert all(slot == [] for slot in plan[1:])
    assert metadata[0] == [{"run": "data_quality_gate", "work_items": 1}]
    assert (name, weight, unit) == ("run", "work_items", "items")


def test_quality_model_overrides_preserve_explicit_options(monkeypatch, env):
    monkeypatch.syspath_prepend(str(ROOT / "data_quality_gate_project/src"))
    module = importlib.import_module("data_quality_gate")
    original = module.DataQualityGateArgs(seed=7, drift_strength=0.1)
    manager = module.DataQualityGate(env, args=original, seed=13)
    assert manager.args.seed == 13
    assert manager.args.drift_strength == 0.1
    assert original.seed == 7


@pytest.fixture
def execution(monkeypatch, env):
    monkeypatch.syspath_prepend(str(ROOT / "execution_polars_project/src"))
    module = importlib.import_module("execution_polars")
    return module.ExecutionPolars(
        env, n_partitions=2, rows_per_file=5, n_groups=2, seed=42
    )


@pytest.mark.parametrize("manifest_state", ["missing", "malformed", "stale"])
def test_execution_dataset_rebuilds_stale_manifest_deterministically(
    execution, manifest_state
):
    root = execution.args.data_in
    expected = {path.name: path.read_bytes() for path in root.glob("*.csv")}
    manifest = execution._manifest_path(root)
    if manifest_state == "missing":
        manifest.unlink()
    elif manifest_state == "malformed":
        manifest.write_text("{")
    else:
        manifest.write_text('{"seed":0}')
    (root / "obsolete.csv").write_text("stale\n")
    execution._ensure_dataset(root)
    assert {path.name: path.read_bytes() for path in root.glob("*.csv")} == expected
    assert json.loads(manifest.read_text()) == execution._dataset_manifest()


def test_execution_current_manifest_preserves_existing_data(execution):
    root = execution.args.data_in
    path = next(root.glob("*.csv"))
    path.write_text("custom preserved contents\n")
    execution._ensure_dataset(root)
    assert path.read_text() == "custom preserved contents\n"


def test_execution_distribution_respects_file_limit_and_missing_file_error(execution):
    execution.args.nfile = 1
    plan, metadata, key, weight, unit = execution.build_distribution(8)
    assert len(plan) == len(metadata) == 1
    assert len(plan[0][0]) == 1
    assert metadata[0][0]["file"] == Path(plan[0][0][0]).name
    assert (key, weight, unit) == ("file", "size_kb", "KB")
    execution.args.files = "missing-*.csv"
    with pytest.raises(FileNotFoundError, match="No workload files"):
        execution.build_distribution(8)
