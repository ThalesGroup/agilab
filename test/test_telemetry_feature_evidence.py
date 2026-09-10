from __future__ import annotations

import builtins
import csv
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "src/agilab/examples/telemetry_features"
SCRIPT = EXAMPLE / "preview_telemetry_features.py"
spec = importlib.util.spec_from_file_location("telemetry_example", SCRIPT)
assert spec and spec.loader
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


@pytest.fixture
def adapter():
    pytest.importorskip(
        "featuretools",
        reason="Optional Featuretools integration; use the example's pins",
    )
    return example._adapter()


@pytest.fixture
def bundle(tmp_path, adapter):
    output = tmp_path / "bundle"
    example.build_preview(output)
    return output


@pytest.fixture
def integrity_bundle(tmp_path):
    """A recorded real run keeps integrity/path tests active without Featuretools.

    Regenerate by running the documented CLI, then recording the eight UTF-8
    files as a filename-to-content JSON object. Replay tests use fresh runs.
    """
    snapshot = json.loads(
        (ROOT / "test/fixtures/telemetry_feature_bundle.json").read_text()
    )
    output = tmp_path / "recorded"
    output.mkdir()
    for name, content in snapshot.items():
        (output / name).write_bytes(content.encode("utf-8"))
    return output


def _snapshot(root):
    return {path.name: path.read_bytes() for path in sorted(root.iterdir())}


def _rewrite_manifest(root, name, data):
    """Simulate internally consistent but semantically incorrect evidence."""
    (root / name).write_bytes(data)
    manifest = json.loads((root / "feature_manifest.json").read_text())
    manifest["artifacts"][name] = {
        "size_bytes": len(data),
        "sha256": example._digest(data),
    }
    manifest["run_id"] = example._digest(example._json_bytes(manifest["artifacts"]))
    (root / "feature_manifest.json").write_bytes(example._json_bytes(manifest))


def test_known_values_and_cutoff_boundaries(bundle):
    rows = list(
        csv.DictReader(io.StringIO((bundle / "feature_matrix.csv").read_text()))
    )
    assert rows == [
        {
            "asset_id": "node-a",
            "COUNT(samples)": "3",
            "MAX(samples.latency_ms)": "30",
            "MEAN(samples.latency_ms)": "20",
        },
        {
            "asset_id": "node-b",
            "COUNT(samples)": "3",
            "MAX(samples.latency_ms)": "60",
            "MEAN(samples.latency_ms)": "40",
        },
    ]
    manifest = json.loads((bundle / "feature_manifest.json").read_text())
    assert manifest["schema"] == "agilab.feature-evidence.v1"
    assert manifest["target"]["worker_execution"] == "not_requested"
    assert manifest["checks"]["replay"] == "not_run"
    assert set(manifest["artifacts"]) == set(example.ARTIFACTS)


def test_repeated_generation_has_identical_artifacts(bundle, tmp_path):
    second = tmp_path / "second"
    example.build_preview(second)
    for name in example.ARTIFACTS:
        assert (bundle / name).read_bytes() == (second / name).read_bytes(), name


def test_wider_history_changes_values_and_recipe(bundle, tmp_path):
    second = tmp_path / "wider"
    example.build_preview(second, window_minutes=10)
    assert (bundle / "feature_matrix.csv").read_bytes() != (
        second / "feature_matrix.csv"
    ).read_bytes()
    assert (bundle / "feature_plan.json").read_bytes() != (
        second / "feature_plan.json"
    ).read_bytes()


def test_future_and_late_arrivals_cannot_change_past_features(adapter):
    ft, pd = adapter
    plan = example.feature_plan()
    tables = example.fixture_tables()
    es = example._entityset(tables, plan, ft, pd)
    definitions = example._synthesize(es, plan, ft)
    before = example._calculate(es, definitions, plan, ft, pd)
    # The second future arrival claims an old observation time; availability wins.
    tables["samples.csv"] += (
        b"100,node-a,2026-01-01T00:12:00Z,2026-01-01T00:12:00Z,999999\n"
        b"101,node-b,2026-01-01T00:13:00Z,2026-01-01T00:07:00Z,999999\n"
    )
    after = example._calculate(
        example._entityset(tables, plan, ft, pd), definitions, plan, ft, pd
    )
    assert after == before


def test_later_cutoff_includes_newly_available_values(adapter):
    ft, pd = adapter
    plan = example.feature_plan("2026-01-01T00:12:00Z")
    es = example._entityset(example.fixture_tables(), plan, ft, pd)
    rows = list(
        csv.DictReader(
            io.StringIO(
                example._calculate(
                    es, example._synthesize(es, plan, ft), plan, ft, pd
                ).decode()
            )
        )
    )
    assert rows[0] == {
        "asset_id": "node-a",
        "COUNT(samples)": "4",
        "MAX(samples.latency_ms)": "100",
        "MEAN(samples.latency_ms)": "50",
    }


def test_replay_uses_saved_definitions_and_is_portable_read_only(
    bundle, monkeypatch, tmp_path
):
    relocated = tmp_path / "relocated"
    shutil.copytree(bundle, relocated)
    before = _snapshot(relocated)
    monkeypatch.setattr(
        example, "_synthesize", lambda *args: pytest.fail("Replay must not synthesize")
    )
    result = example.verify_evidence(relocated, replay=True)
    assert result["artifact_integrity"] == result["replay"] == "passed"
    assert _snapshot(relocated) == before


@pytest.mark.parametrize("name", example.ARTIFACTS)
def test_every_artifact_is_verified(integrity_bundle, name):
    bundle = integrity_bundle
    (bundle / name).write_bytes((bundle / name).read_bytes() + b" ")
    with pytest.raises(ValueError, match="hash/size mismatch"):
        example.verify_evidence(bundle)


@pytest.mark.parametrize("mutation", ["missing", "escape", "symlink", "schema"])
def test_manifest_and_path_contract(integrity_bundle, tmp_path, mutation):
    bundle = integrity_bundle
    manifest_path = bundle / "feature_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if mutation == "missing":
        del manifest["artifacts"]["samples.csv"]
    elif mutation == "escape":
        manifest["artifacts"]["../samples.csv"] = manifest["artifacts"].pop(
            "samples.csv"
        )
    elif mutation == "schema":
        manifest["schema"] = "unknown"
    else:
        target = tmp_path / "outside.csv"
        (bundle / "samples.csv").rename(target)
        (bundle / "samples.csv").symlink_to(target)
    manifest_path.write_bytes(example._json_bytes(manifest))
    with pytest.raises(ValueError):
        example.verify_evidence(bundle)


def test_replay_detects_rehashed_wrong_values(bundle):
    _rewrite_manifest(bundle, "feature_matrix.csv", b"asset_id,wrong\nnode-a,9000\n")
    assert example.verify_evidence(bundle)["replay"] == "not_run"
    with pytest.raises(ValueError, match="Replay mismatch"):
        example.verify_evidence(bundle, replay=True)


@pytest.mark.parametrize("field", ["runtime", "producer"])
def test_replay_rejects_version_or_source_drift(bundle, field):
    path = bundle / "feature_manifest.json"
    manifest = json.loads(path.read_text())
    if field == "runtime":
        manifest[field]["packages"]["featuretools"] = "different"
    else:
        manifest[field]["sha256"] = "0" * 64
    path.write_bytes(example._json_bytes(manifest))
    with pytest.raises(ValueError, match="mismatch|source changed"):
        example.verify_evidence(bundle, replay=True)


def test_custom_primitive_is_rejected_before_deserialization(
    bundle, adapter, monkeypatch
):
    ft, _ = adapter
    saved = json.loads((bundle / "feature_definitions.json").read_text())
    next(iter(saved["primitive_definitions"].values()))["module"] = "unexpected.module"
    monkeypatch.setattr(
        ft, "load_features", lambda *args: pytest.fail("Must reject before loading")
    )
    with pytest.raises(ValueError, match="unsupported primitive"):
        example._load_definitions(example._json_bytes(saved), ft)


def test_verifier_runs_without_site_packages(integrity_bundle):
    bundle = integrity_bundle
    result = subprocess.run(
        [sys.executable, "-S", str(SCRIPT), "--verify", "--output-dir", str(bundle)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["artifact_integrity"] == "passed"


def test_existing_output_is_preserved(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep.txt").write_text("user work")
    with pytest.raises(ValueError, match="already exists"):
        example.build_preview(output)
    assert (output / "keep.txt").read_text() == "user work"


def test_missing_optional_dependency_has_actionable_error(monkeypatch):
    original = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "featuretools":
            raise ImportError("not installed")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(ValueError, match="uv run --script"):
        example._adapter()


@pytest.mark.parametrize("window", [0, -1, 61, True, 1.5])
def test_invalid_window_fails_before_optional_import(tmp_path, monkeypatch, window):
    monkeypatch.setattr(
        example, "_adapter", lambda: pytest.fail("Invalid plan must fail first")
    )
    with pytest.raises(ValueError, match="window_minutes"):
        example.build_preview(tmp_path / "bundle", window_minutes=window)


def test_cutoff_requires_timezone():
    with pytest.raises(ValueError, match="timezone"):
        example.feature_plan("2026-01-01T00:10:00")
    assert example.feature_plan("2026-01-01T01:10:00+01:00") == example.feature_plan()


def test_verify_rejects_ignored_generation_options(integrity_bundle, capsys):
    with pytest.raises(SystemExit) as error:
        example.main(
            [
                "--verify",
                "--output-dir",
                str(integrity_bundle),
                "--window-minutes",
                "10",
            ]
        )
    assert error.value.code == 2
    assert "replay uses the saved plan" in capsys.readouterr().err


def test_workflow_stages_execute_in_order(tmp_path, adapter, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(ROOT / "src"))
    stages = tomllib.loads((EXAMPLE / "lab_stages.toml").read_text())[
        "telemetry_features"
    ]
    namespace = {}
    for stage in stages:
        exec(compile(stage["C"], "lab_stages.toml", "exec"), namespace)
    assert namespace["feature_verification"]["replay"] == "passed"
