from __future__ import annotations

import importlib.util
import sys
from dataclasses import asdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "parallel_stage.py"

spec = importlib.util.spec_from_file_location("parallel_stage", MODULE_PATH)
assert spec is not None and spec.loader is not None
parallel_stage = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = parallel_stage
spec.loader.exec_module(parallel_stage)


def test_build_and_validate_file_parallel_stage_contract():
    contract = parallel_stage.build_contract(
        name="process_csv_files",
        function="my_pipeline.process:process_file",
        split="files",
        input_value="data/*.csv",
        workers=4,
        reducer="concat-jsonl",
        backend="pool",
        output="parallel_stage.toml",
    )

    result = parallel_stage.validate_mapping(asdict(contract))

    assert result.ok is True
    assert result.issues == ()


def test_render_contract_uses_stable_schema_and_next_steps():
    contract = parallel_stage.build_contract(
        name="sweep",
        function="experiments.grid:run_one",
        split="parameter-sweep",
        input_value="params.json",
        workers=8,
        reducer="collect-json",
        backend="dask",
        output="parallel_stage.toml",
    )

    text = parallel_stage.render_contract(contract)

    assert 'schema = "agilab.parallel_stage.v1"' in text
    assert 'split = "parameter-sweep"' in text
    assert 'partition_strategy = "one-file-per-partition"' in text
    assert "[next_steps]" in text


def test_validate_rejects_missing_function_and_unknown_split():
    result = parallel_stage.validate_mapping(
        {
            "schema": "agilab.parallel_stage.v1",
            "name": "bad",
            "split": "magic",
            "input": "data/*.csv",
            "workers": 2,
            "partition_strategy": "one-file-per-partition",
            "target_partitions": 0,
            "min_partitions_per_worker": 2,
            "reducer": "collect-json",
            "backend": "local",
            "output": "parallel_stage.toml",
        }
    )

    assert result.ok is False
    assert "missing required key: function" in result.issues
    assert "split must be one of: files, data-partitions, parameter-sweep" in result.issues


def test_validate_warns_for_preview_workers_and_custom_reducer():
    result = parallel_stage.validate_mapping(
        {
            "schema": "agilab.parallel_stage.v1",
            "name": "preview",
            "function": "demo:run_one",
            "split": "files",
            "input": "data/*.csv",
            "workers": 1,
            "partition_strategy": "one-file-per-partition",
            "target_partitions": 0,
            "min_partitions_per_worker": 2,
            "reducer": "custom",
            "backend": "local",
            "output": "parallel_stage.toml",
        }
    )

    assert result.ok is True
    assert "workers=1 is valid for preview but does not parallelize execution" in result.warnings
    assert "custom reducer should describe the merge contract in notes" in result.warnings


def test_validate_supports_file_chunk_strategy_when_files_are_fewer_than_cores():
    result = parallel_stage.validate_mapping(
        {
            "schema": "agilab.parallel_stage.v1",
            "name": "chunk_large_files",
            "function": "demo:process_chunk",
            "split": "files",
            "input": "data/*.csv",
            "workers": "auto",
            "partition_strategy": "file-chunks",
            "target_partitions": 64,
            "min_partitions_per_worker": 2,
            "reducer": "concat-jsonl",
            "backend": "pool",
            "output": "parallel_stage.toml",
        }
    )

    assert result.ok is True
    assert result.issues == ()


def test_recommended_effective_workers_caps_unsplittable_low_file_count():
    assert (
        parallel_stage.recommended_effective_workers(
            file_count=3,
            workers=8,
            files_are_splittable=False,
        )
        == 3
    )
    assert (
        parallel_stage.recommended_effective_workers(
            file_count=3,
            workers=8,
            files_are_splittable=True,
        )
        == 8
    )
