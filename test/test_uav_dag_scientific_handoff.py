"""Scientific app regression for exact delivered-packet handoff, without SDK mocks."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
for _project in ("uav_queue_project", "uav_relay_queue_project"):
    sys.path.insert(0, str(REPO_ROOT / "src/agilab/apps/builtin" / _project / "src"))

from uav_queue import UavQueue, UavQueueArgs  # noqa: E402
from uav_queue_worker import UavQueueWorker  # noqa: E402
from uav_relay_queue import UavRelayQueue, UavRelayQueueArgs  # noqa: E402
from uav_relay_queue_worker import UavRelayQueueWorker  # noqa: E402


def _environment(root: Path, target: str) -> SimpleNamespace:
    share = root / "share"
    share.mkdir(parents=True)
    exports = root / "export"
    exports.mkdir()

    def resolve_share_path(path):
        path = Path(path)
        return path if path.is_absolute() else share / path

    return SimpleNamespace(
        verbose=0, resolve_share_path=resolve_share_path, home_abs=root,
        _is_managed_pc=False, AGI_LOCAL_SHARE=str(share),
        AGILAB_EXPORT_ABS=exports, target=target,
    )


def _worker(root: Path, *, relay: bool, **overrides):
    env = _environment(root, "relay" if relay else "queue")
    args_type = UavRelayQueueArgs if relay else UavQueueArgs
    manager_type = UavRelayQueue if relay else UavQueue
    worker_type = UavRelayQueueWorker if relay else UavQueueWorker
    args = args_type(**{"sim_time_s": 3.0, "sampling_interval_s": 0.5, **overrides})
    manager = manager_type(env, args=args)
    source = sorted(manager.args.data_in.glob("*.json"))[0]
    worker = worker_type()
    worker.env = env
    worker.args = manager.args.model_dump(mode="json")
    worker._worker_id = worker.worker_id = worker.verbose = 0
    worker.start()
    return worker, source


def _binding(root: Path, packets=None):
    if packets is None:
        packets = [
            {"packet_id": 4, "delivered_s": 0.123456789012345},
            {"packet_id": 8, "delivered_s": 0.25},
            {"packet_id": 12, "delivered_s": 3.456789012345},
        ]
    payload = {
        "sim_time_s": 3.0, "packets_generated": len(packets),
        "packets_delivered": len(packets),
        "delivery_trace": {
            "schema": "agilab.uav_delivered_packet_trace.v1",
            "source_emission_horizon_s": 3.0, "simulation_horizon_s": 6.0,
            "packets": packets,
        },
    }
    producer = root / "producer"
    producer.mkdir(parents=True)
    path = producer / "uav_queue_summary_metrics.json"
    raw = json.dumps(payload, allow_nan=False).encode()
    path.write_bytes(raw)
    binding = {
        "artifact": "queue_metrics", "producer": "queue_baseline",
        "kind": "summary_metrics", "path": str(path),
        "resolved_path": str(path.resolve()), "producer_run_root": str(producer),
        "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return binding, payload


def test_queue_exports_actual_delivered_trace_only_when_requested(tmp_path):
    worker, source = _worker(tmp_path / "queue", relay=False, emit_delivery_trace=True)
    result = worker.work_pool(source)
    metrics = result["summary_metrics"]
    trace = metrics["delivery_trace"]
    delivered = result["packet_events"].query("origin_kind == 'source' and status == 'delivered'")
    assert trace["schema"] == "agilab.uav_delivered_packet_trace.v1"
    assert len(trace["packets"]) == metrics["packets_delivered"] == len(delivered)
    assert {row["packet_id"] for row in trace["packets"]} == set(delivered.packet_id)
    assert trace["source_emission_horizon_s"] == 3.0
    assert trace["simulation_horizon_s"] > 3.0
    assert trace["packets"] == sorted(trace["packets"], key=lambda row: (row["delivered_s"], row["packet_id"]))
    assert any(row["delivered_s"] != round(row["delivered_s"], 6) for row in trace["packets"])
    worker.work_done(result)
    exported = json.loads(next(Path(worker.data_out).glob("**/*_summary_metrics.json")).read_bytes())
    assert exported["delivery_trace"] == trace
    default, default_source = _worker(tmp_path / "default", relay=False)
    assert "delivery_trace" not in default.work_pool(default_source)["summary_metrics"]


def test_relay_schedules_exact_trace_including_late_deliveries_and_records_worker_read(tmp_path):
    binding, payload = _binding(tmp_path)
    worker, source = _worker(
        tmp_path / "relay", relay=True, use_upstream_delivery_trace=True,
        upstream_queue_metrics=binding,
    )
    result = worker.work_pool(source)
    receipt = result["summary_metrics"]["upstream_queue_receipt"]
    expected = [
        {"upstream_packet_id": row["packet_id"], "created_s": row["delivered_s"]}
        for row in payload["delivery_trace"]["packets"]
    ]
    assert receipt["scheduled_packets"] == expected
    assert receipt["source_packet_count"] == 3
    assert receipt["read_scope"] == "worker"
    assert receipt["numerically_conditioned"] is True
    assert receipt["sha256"] == binding["sha256"]
    assert receipt["size_bytes"] == binding["size_bytes"]
    assert receipt["producer_run_root"] == binding["producer_run_root"]
    assert receipt["worker_pid"] > 0
    assert result["summary_metrics"]["packets_generated"] == 3
    assert result["summary_metrics"]["source_arrival_mode"] == "upstream_delivery_trace"
    worker.work_done(result)
    exported = json.loads(next(Path(worker.data_out).glob("**/*_summary_metrics.json")).read_bytes())
    assert exported["upstream_queue_receipt"] == receipt


def test_late_delivery_monitoring_covers_source_arrivals_and_drain(tmp_path):
    binding, _ = _binding(
        tmp_path, packets=[{"packet_id": identity, "delivered_s": 3.5} for identity in range(1, 9)],
    )
    worker, source = _worker(
        tmp_path / "relay", relay=True, use_upstream_delivery_trace=True,
        upstream_queue_metrics=binding,
    )
    scenario = json.loads(source.read_bytes())
    for relay in scenario["relays"]:
        relay["background_rate_pps"] = 0.0
    source.write_text(json.dumps(scenario))

    result = worker.work_pool(source)
    metrics = result["summary_metrics"]
    monitored = result["queue_timeseries"]
    assert metrics["packets_generated"] == metrics["packets_delivered"] == 8
    assert metrics["mean_queue_wait_ms"] > 0
    assert metrics["max_queue_depth_pkts"] > 0
    assert monitored["time_s"].max() >= (
        metrics["simulation_horizon_s"] - metrics["sampling_interval_s"]
    )
    assert result["node_positions"]["time_s"].max() == monitored["time_s"].max()


def test_uncoupled_reference_uses_its_original_source_process(tmp_path):
    worker, source = _worker(tmp_path / "reference", relay=True)
    result = worker.work_pool(source)
    assert result["summary_metrics"]["packets_generated"] > 3
    assert "upstream_queue_receipt" not in result["summary_metrics"]
    assert result["summary_metrics"]["source_rate_pps"] == 14.0
    assert result["queue_timeseries"]["time_s"].max() == 3.0
    assert result["node_positions"]["time_s"].max() == 3.0


def test_exact_handoff_args_reject_multi_scenario_fanout():
    with pytest.raises(ValueError, match="single scenario|nfile=1"):
        UavRelayQueueArgs(use_upstream_delivery_trace=True, nfile=2)
    assert UavRelayQueueArgs(nfile=2).nfile == 2


def test_worker_rejects_multi_scenario_fanout_from_serialized_args(tmp_path):
    binding, _ = _binding(tmp_path)
    worker, source = _worker(
        tmp_path / "relay", relay=True, use_upstream_delivery_trace=True,
        upstream_queue_metrics=binding,
    )
    worker.args.nfile = 2
    with pytest.raises(ValueError, match="single scenario|nfile=1"):
        worker.work_pool(source)


def test_empty_delivery_trace_has_zero_source_packets_even_without_background(tmp_path):
    binding, _ = _binding(tmp_path, packets=[])
    worker, source = _worker(
        tmp_path / "relay", relay=True, use_upstream_delivery_trace=True,
        upstream_queue_metrics=binding,
    )
    scenario = json.loads(source.read_bytes())
    for relay in scenario["relays"]:
        relay["background_rate_pps"] = 0.0
    source.write_text(json.dumps(scenario))
    result = worker.work_pool(source)
    assert result["summary_metrics"]["packets_generated"] == 0
    assert result["summary_metrics"]["upstream_queue_receipt"]["scheduled_packets"] == []
    worker.work_done(result)


@pytest.mark.parametrize("horizon", [3.0, 30.0])
def test_original_queue_artifact_drives_relay_without_resampling(tmp_path, horizon):
    queue, queue_source = _worker(
        tmp_path / "queue", relay=False, emit_delivery_trace=True, sim_time_s=horizon,
    )
    upstream = queue.work_pool(queue_source)
    queue.work_done(upstream)
    path = next(Path(queue.data_out).glob("**/*_summary_metrics.json"))
    raw = path.read_bytes()
    binding = {
        "artifact": "queue_metrics", "producer": "queue_baseline", "kind": "summary_metrics",
        "path": str(path), "resolved_path": str(path.resolve()),
        "producer_run_root": str(Path(queue.data_out)), "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    relay, relay_source = _worker(
        tmp_path / "relay", relay=True, use_upstream_delivery_trace=True,
        upstream_queue_metrics=binding, sim_time_s=horizon,
    )
    downstream = relay.work_pool(relay_source)
    trace = upstream["summary_metrics"]["delivery_trace"]["packets"]
    scheduled = downstream["summary_metrics"]["upstream_queue_receipt"]["scheduled_packets"]
    assert scheduled == [
        {"upstream_packet_id": row["packet_id"], "created_s": row["delivered_s"]}
        for row in trace
    ]
    assert downstream["summary_metrics"]["packets_generated"] == upstream["summary_metrics"]["packets_delivered"]
    reference, reference_source = _worker(tmp_path / "reference", relay=True, sim_time_s=horizon)
    baseline = reference.work_pool(reference_source)
    assert baseline["summary_metrics"]["packets_generated"] != downstream["summary_metrics"]["packets_generated"]


@pytest.mark.parametrize("with_binding,enabled", [(False, True), (True, False)])
def test_relay_rejects_missing_or_implicitly_ignored_context(tmp_path, with_binding, enabled):
    binding, _ = _binding(tmp_path)
    worker, source = _worker(
        tmp_path / "relay", relay=True, use_upstream_delivery_trace=enabled,
        upstream_queue_metrics=binding if with_binding else None,
    )
    with pytest.raises(ValueError, match="upstream|delivery trace|binding"):
        worker.work_pool(source)


@pytest.mark.parametrize("mutation", ["missing", "hash", "size", "producer", "escape", "symlink", "resolved_path", "directory"])
def test_relay_rejects_changed_or_invalid_original_producer_binding(tmp_path, mutation):
    binding, _ = _binding(tmp_path)
    path = Path(binding["path"])
    if mutation == "missing":
        path.unlink()
    elif mutation == "hash":
        path.write_bytes(path.read_bytes().replace(b"0.25", b"0.35"))
    elif mutation == "size":
        binding["size_bytes"] += 1
    elif mutation == "producer":
        binding["producer"] = "unrelated_stage"
    elif mutation == "escape":
        binding["producer_run_root"] = str(tmp_path / "other_producer")
    elif mutation == "resolved_path":
        binding["resolved_path"] += ".changed"
    elif mutation == "directory":
        binding["identity_kind"] = "directory"
    else:
        retained = path.with_name("retained.json")
        path.rename(retained)
        path.symlink_to(retained)
    worker, source = _worker(
        tmp_path / "relay", relay=True, use_upstream_delivery_trace=True,
        upstream_queue_metrics=binding,
    )
    with pytest.raises(ValueError, match="upstream|producer|identity|artifact|symlink"):
        worker.work_pool(source)


@pytest.mark.parametrize("mutation", ["nan", "negative", "duplicate", "unordered", "count", "schema", "horizon", "oversize", "packet_limit"])
def test_relay_rejects_invalid_trace_before_scheduling(tmp_path, mutation):
    binding, payload = _binding(tmp_path)
    trace = payload["delivery_trace"]
    packets = trace["packets"]
    if mutation == "nan":
        packets[0]["delivered_s"] = float("nan")
    elif mutation == "negative":
        packets[0]["delivered_s"] = -0.1
    elif mutation == "duplicate":
        packets[1]["packet_id"] = packets[0]["packet_id"]
    elif mutation == "unordered":
        packets.reverse()
    elif mutation == "count":
        payload["packets_delivered"] += 1
    elif mutation == "schema":
        trace["schema"] = "unknown.v1"
    elif mutation == "horizon":
        trace["simulation_horizon_s"] = 1.0
    elif mutation == "packet_limit":
        trace["packets"] = [{"packet_id": i, "delivered_s": i / 10_000} for i in range(1, 10_002)]
        payload["packets_generated"] = payload["packets_delivered"] = len(trace["packets"])
    else:
        payload["padding"] = "x" * 1_048_576
    raw = json.dumps(payload).encode()
    Path(binding["path"]).write_bytes(raw)
    binding.update(size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    worker, source = _worker(
        tmp_path / "relay", relay=True, use_upstream_delivery_trace=True,
        upstream_queue_metrics=binding,
    )
    with pytest.raises(ValueError, match="upstream|trace|finite|limit"):
        worker.work_pool(source)


def test_unconditioned_zero_source_reducer_guard_is_preserved(tmp_path):
    from uav_relay_queue.reduction import build_reduce_artifact, partial_from_summary_metrics

    worker, source = _worker(tmp_path / "reference", relay=True)
    metrics = worker.work_pool(source)["summary_metrics"]
    metrics.update(packets_generated=0, packets_delivered=0, packets_dropped=0)
    partial = partial_from_summary_metrics(metrics, partial_id="reference")
    with pytest.raises(ValueError, match="no generated packets"):
        build_reduce_artifact([partial])


def test_compiled_relay_worker_loads_scientific_handoff_through_sdk(tmp_path, monkeypatch, request):
    import importlib
    import importlib.machinery
    import shutil
    import subprocess
    import sysconfig

    pytest.importorskip("Cython")
    if not (shutil.which("cc") or shutil.which("cl")):
        pytest.skip("native C compiler required for actual Cython worker import")
    if not (Path(sysconfig.get_path("include")) / "Python.h").is_file():
        pytest.skip("Python development headers required for actual Cython worker import")
    from setuptools import Distribution
    from agi_node.agi_dispatcher import base_worker_runtime_support, build

    project = REPO_ROOT / "src/agilab/apps/builtin/uav_relay_queue_project"
    worker_name = "uav_relay_queue_worker"
    original = project / "src" / worker_name / f"{worker_name}.py"
    source_root = tmp_path / "compiled-worker-source"
    source_root.mkdir()
    worker_source = source_root / original.name
    shutil.copyfile(original, worker_source)
    preparation = build._build_pre_install_command(
        pre_install_script=Path(build.__file__).with_name("pre_install.py"),
        worker_py=worker_source, verbose=False,
        type_preprocess=build._resolve_cython_type_preprocess_option(),
    )
    prepared = subprocess.run(preparation, capture_output=True, text=True, check=False)
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    worker_pyx = worker_source.with_suffix(".pyx")
    assert worker_pyx.is_file()
    compile_args, macros, directives = build._build_ext_compile_config(
        sys_platform=sys.platform, pyvers_worker=f"{sys.version_info.major}.{sys.version_info.minor}",
        project_dir=project,
    )
    extension = build._build_worker_extension(
        worker_module=worker_name, src_rel=worker_pyx, prefix=Path(sys.prefix),
        extra_compile_args=compile_args, define_macros=macros,
        library_dirs=[], extra_link_args=[],
    )
    extensions = build._cythonize_worker_extension(
        extension=extension, compiler_directives=directives, quiet=True,
        annotate=False, resolve_cython_cache_option_fn=lambda: False,
    )
    distribution = Distribution({"ext_modules": extensions})
    command = distribution.get_command_obj("build_ext")
    command.build_lib = str(tmp_path / "compiled-worker-lib")
    command.build_temp = str(tmp_path / "compiled-worker-build")
    command.ensure_finalized()
    command.run()
    monkeypatch.syspath_prepend(command.build_lib)
    importlib.invalidate_caches()

    compiled_name = f"{worker_name}_cy"
    previous = {name: sys.modules.get(name) for name in (worker_name, compiled_name)}
    try:
        selected = base_worker_runtime_support.load_worker(
            SimpleNamespace(target_worker=worker_name, target_worker_class="UavRelayQueueWorker"),
            2, load_module_fn=base_worker_runtime_support.load_module,
        )
        module = sys.modules[compiled_name]
        assert selected.__module__ == compiled_name
        assert module.__package__ == ""
        assert any(str(module.__file__).endswith(suffix)
                   for suffix in importlib.machinery.EXTENSION_SUFFIXES)
        assert module.read_upstream_delivery_trace.__module__ == "uav_relay_queue.scientific_handoff"
        request.node.user_properties.extend([
            ("compiled_worker_path", str(module.__file__)),
            ("compiled_worker_sha256", hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()),
            ("sdk_selected_worker_module", selected.__module__),
        ])
    finally:
        for name, value in previous.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value
