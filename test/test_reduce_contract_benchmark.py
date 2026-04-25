from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/reduce_contract_benchmark.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("reduce_contract_benchmark_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_expected_payload_matches_generated_partials() -> None:
    module = _load_module()

    partials = module.build_partials(2, 3)

    assert [partial.partial_id for partial in partials] == ["partition-0", "partition-1"]
    assert module.expected_payload(2, 3) == {
        "items": 6,
        "requested_bandwidth": 21,
        "delivered_bandwidth": 15,
    }


def test_run_benchmark_builds_valid_reduce_artifact() -> None:
    module = _load_module()

    summary = module.run_benchmark(partial_count=3, items_per_partial=5, target_seconds=5.0)

    assert summary.success is True
    assert summary.within_target is True
    assert summary.artifact["name"] == "public_reduce_benchmark_summary"
    assert summary.artifact["reducer"] == "public-reduce-benchmark"
    assert summary.artifact["partial_count"] == 3
    assert summary.artifact["payload"] == module.expected_payload(3, 5)


def test_main_json_emits_machine_readable_summary(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["--partials", "2", "--items-per-partial", "4", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["partial_count"] == 2
    assert payload["items_per_partial"] == 4
    assert payload["artifact"]["schema_version"] == 1
