from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_cluster.agi_distributor import service_state_support


class _FakeFuture:
    def __init__(self, status: str = "pending"):
        self.status = status


def _build_env(
    tmp_path: Path,
    *,
    target: str = "demo_target",
    app: str = "demo_app",
    resolve_share_path=None,
):
    if resolve_share_path is None:
        resolve_share_path = lambda rel: tmp_path / "share" / rel
    return SimpleNamespace(
        target=target,
        app=app,
        home_abs=tmp_path,
        resolve_share_path=resolve_share_path,
    )


def _build_agi():
    agi = SimpleNamespace(
        _workers_data_path=None,
        _service_futures={},
        _service_workers=[],
        _service_shutdown_on_stop=True,
        _service_stop_timeout=30.0,
        _service_poll_interval=None,
        _service_queue_root=None,
        _service_queue_pending=None,
        _service_queue_running=None,
        _service_queue_done=None,
        _service_queue_failed=None,
        _service_queue_heartbeats=None,
        _service_heartbeat_timeout=None,
        _service_started_at=None,
        _service_cleanup_done_ttl_sec=7 * 24 * 3600,
        _service_cleanup_failed_ttl_sec=14 * 24 * 3600,
        _service_cleanup_heartbeat_ttl_sec=24 * 3600,
        _service_cleanup_done_max_files=2000,
        _service_cleanup_failed_max_files=2000,
        _service_cleanup_heartbeat_max_files=1000,
        _service_submit_counter=0,
        _service_worker_args={},
        _mode=4,
        _run_type="run --no-sync",
        _scheduler="127.0.0.1:8786",
        _scheduler_ip="127.0.0.1",
        _scheduler_port=8786,
        _workers={"127.0.0.1": 1},
        _args={},
    )
    agi._service_apply_queue_root = lambda queue_root, create=False: service_state_support.service_apply_queue_root(
        agi,
        queue_root,
        create=create,
    )
    agi._service_state_path = lambda env: service_state_support.service_state_path(env)
    agi._service_health_path = lambda env, health_output_path=None: service_state_support.service_health_path(
        env,
        health_output_path=health_output_path,
    )
    agi._service_health_payload = lambda env, result_payload: service_state_support.service_health_payload(
        env,
        result_payload,
    )
    agi._service_write_health_payload = (
        lambda env, health_payload, health_output_path=None: service_state_support.service_write_health_payload(
            agi,
            env,
            health_payload,
            health_output_path=health_output_path,
        )
    )
    agi._service_heartbeat_timeout_value = lambda: service_state_support.service_heartbeat_timeout_value(agi)
    agi._service_read_heartbeats = lambda: service_state_support.service_read_heartbeats(agi)
    agi._service_read_heartbeat_payloads = lambda: service_state_support.service_read_heartbeat_payloads(agi)
    agi._service_unhealthy_workers = lambda workers: service_state_support.service_unhealthy_workers(agi, workers)
    agi._init_service_queue = lambda env, service_queue_dir=None: service_state_support.init_service_queue(
        agi,
        env,
        service_queue_dir=service_queue_dir,
    )
    return agi


def test_init_service_queue_falls_back_to_home_when_share_resolution_fails(tmp_path):
    agi = _build_agi()
    env = _build_env(
        tmp_path,
        resolve_share_path=lambda _hint: (_ for _ in ()).throw(RuntimeError("no share")),
    )

    paths = service_state_support.init_service_queue(agi, env)

    assert paths["root"] == (tmp_path / ".agilab_service" / env.target / "queue").resolve()
    assert paths["pending"].exists()
    assert paths["heartbeats"].exists()


def test_service_queue_prefers_workers_data_path(tmp_path):
    agi = _build_agi()
    agi._workers_data_path = str(tmp_path / "cluster-share")
    env = _build_env(tmp_path, target="mycode_project", app="mycode_project")

    queue_paths = service_state_support.init_service_queue(agi, env)

    expected_root = Path(agi._workers_data_path) / "service" / env.target / "queue"
    assert queue_paths["root"] == expected_root
    assert queue_paths["heartbeats"].parent == expected_root


def test_service_queue_keeps_workers_data_path_literal():
    agi = _build_agi()
    agi._workers_data_path = "/tmp/agilab_test_share"
    env = _build_env(Path("/tmp"), target="mycode_project", app="mycode_project")

    queue_paths = service_state_support.init_service_queue(agi, env)

    assert queue_paths["root"] == Path("/tmp/agilab_test_share") / "service" / env.target / "queue"


def test_service_public_args_filters_internal_keys():
    payload = {
        "_agi_service_mode": True,
        "_agi_service_queue_dir": "/tmp/queue",
        "model": "gpt",
        "temperature": 0.2,
    }

    cleaned = service_state_support.service_public_args(payload)

    assert "_agi_service_mode" not in cleaned
    assert "_agi_service_queue_dir" not in cleaned
    assert cleaned["model"] == "gpt"
    assert cleaned["temperature"] == 0.2


def test_service_safe_worker_name_and_timeout_default():
    agi = _build_agi()
    agi._service_poll_interval = 0.5
    agi._service_heartbeat_timeout = None

    timeout = service_state_support.service_heartbeat_timeout_value(agi)

    assert timeout == 5.0
    assert service_state_support.service_safe_worker_name("tcp://127.0.0.1:8786") == "tcp-127.0.0.1-8786"


def test_service_public_args_handles_none():
    assert service_state_support.service_public_args(None) == {}


def test_service_safe_worker_name_fallback_and_explicit_timeout():
    agi = _build_agi()
    agi._service_heartbeat_timeout = 2.5

    assert service_state_support.service_heartbeat_timeout_value(agi) == 2.5
    assert service_state_support.service_safe_worker_name(":::") == "worker"


def test_service_read_state_returns_none_for_invalid_payload(tmp_path):
    agi = _build_agi()
    env = _build_env(tmp_path)
    state_path = tmp_path / "state.json"
    agi._service_state_path = lambda _env: state_path

    state_path.write_text("not-json", encoding="utf-8")
    assert service_state_support.service_read_state(agi, env) is None

    state_path.write_text(json.dumps(["not-a-dict"]), encoding="utf-8")
    assert service_state_support.service_read_state(agi, env) is None


def test_service_write_state_roundtrip_and_clear(tmp_path):
    agi = _build_agi()
    env = _build_env(tmp_path)
    state_path = tmp_path / "service_state.json"
    agi._service_state_path = lambda _env: state_path

    service_state_support.service_write_state(agi, env, {"schema": "x", "status": "running"})
    assert json.loads(state_path.read_text(encoding="utf-8"))["status"] == "running"
    service_state_support.service_clear_state(agi, env)
    assert not state_path.exists()


def test_service_finalize_response_health_only_adds_export_path():
    agi = _build_agi()
    env = _build_env(Path("/tmp"))
    agi._service_write_health_payload = lambda *_args, **_kwargs: "/tmp/health.json"

    payload = service_state_support.service_finalize_response(agi, env, {"status": "idle"}, health_only=True)

    assert payload["schema"] == "agi.service.health.v1"
    assert payload["path"] == "/tmp/health.json"
    assert payload["status"] == "idle"


def test_service_write_health_payload_returns_none_on_failure():
    agi = _build_agi()
    env = _build_env(Path("/tmp"))
    agi._service_health_path = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))

    assert service_state_support.service_write_health_payload(agi, env, {"schema": "x"}) is None


@pytest.mark.asyncio
async def test_service_connected_workers_supports_awaitable_scheduler_info():
    class _AwaitableClient:
        async def scheduler_info(self):
            return {
                "workers": {
                    "tcp://127.0.0.1:8787": {},
                    "tcp://127.0.0.1:8788": {},
                }
            }

    workers = await service_state_support.service_connected_workers(_AwaitableClient())
    assert workers == ["127.0.0.1:8787", "127.0.0.1:8788"]


@pytest.mark.asyncio
async def test_service_connected_workers_supports_sync_scheduler_info():
    class _SyncClient:
        def scheduler_info(self):
            return {"workers": {"tcp://127.0.0.1:9001": {}}}

    workers = await service_state_support.service_connected_workers(_SyncClient())
    assert workers == ["127.0.0.1:9001"]


def test_service_apply_runtime_config_clamps_values():
    agi = _build_agi()

    service_state_support.service_apply_runtime_config(
        agi,
        heartbeat_timeout=-4.0,
        cleanup_done_ttl_sec=-1.0,
        cleanup_failed_ttl_sec=-2.0,
        cleanup_heartbeat_ttl_sec=-3.0,
        cleanup_done_max_files=-10,
        cleanup_failed_max_files=-11,
        cleanup_heartbeat_max_files=-12,
    )

    assert agi._service_heartbeat_timeout == 0.1
    assert agi._service_cleanup_done_ttl_sec == 0.0
    assert agi._service_cleanup_failed_ttl_sec == 0.0
    assert agi._service_cleanup_heartbeat_ttl_sec == 0.0
    assert agi._service_cleanup_done_max_files == 0
    assert agi._service_cleanup_failed_max_files == 0
    assert agi._service_cleanup_heartbeat_max_files == 0


def test_service_queue_paths_and_apply_queue_root_without_create(tmp_path):
    agi = _build_agi()
    queue_root = tmp_path / "queue-root"

    paths = service_state_support.service_queue_paths(queue_root)
    assert paths["pending"] == queue_root / "pending"
    assert paths["running"] == queue_root / "running"
    assert paths["done"] == queue_root / "done"
    assert paths["failed"] == queue_root / "failed"
    assert paths["heartbeats"] == queue_root / "heartbeats"

    applied = service_state_support.service_apply_queue_root(agi, queue_root, create=False)
    assert applied["root"] == queue_root
    assert agi._service_queue_root == queue_root
    assert agi._service_queue_pending == queue_root / "pending"
    assert queue_root.exists() is False


def test_service_queue_counts_reads_task_files(tmp_path):
    agi = _build_agi()
    pending = tmp_path / "pending"
    running = tmp_path / "running"
    done = tmp_path / "done"
    failed = tmp_path / "failed"
    for folder in (pending, running, done, failed):
        folder.mkdir(parents=True, exist_ok=True)

    (pending / "a.task.pkl").write_text("x", encoding="utf-8")
    (pending / "b.task.pkl").write_text("x", encoding="utf-8")
    (running / "c.task.pkl").write_text("x", encoding="utf-8")
    (done / "d.task.pkl").write_text("x", encoding="utf-8")

    agi._service_queue_pending = pending
    agi._service_queue_running = running
    agi._service_queue_done = done
    agi._service_queue_failed = failed

    assert service_state_support.service_queue_counts(agi) == {
        "pending": 2,
        "running": 1,
        "done": 1,
        "failed": 0,
    }


def test_init_service_queue_removes_stale_pending_running_and_heartbeats(tmp_path):
    agi = _build_agi()
    env = _build_env(tmp_path, target="mycode_project", app="mycode_project")
    queue_root = tmp_path / "queue"
    for name in ("pending", "running", "done", "failed", "heartbeats"):
        (queue_root / name).mkdir(parents=True, exist_ok=True)

    stale_pending = queue_root / "pending" / "old.task.pkl"
    stale_running = queue_root / "running" / "old.task.pkl"
    stale_heartbeat = queue_root / "heartbeats" / "old.json"
    stale_pending.write_text("x", encoding="utf-8")
    stale_running.write_text("x", encoding="utf-8")
    stale_heartbeat.write_text("{}", encoding="utf-8")

    queue_paths = service_state_support.init_service_queue(agi, env, service_queue_dir=queue_root)

    assert queue_paths["root"] == queue_root
    assert stale_pending.exists() is False
    assert stale_running.exists() is False
    assert stale_heartbeat.exists() is False


def test_service_state_path_falls_back_when_resolve_share_path_is_missing(tmp_path):
    env = _build_env(tmp_path, resolve_share_path=lambda _path: (_ for _ in ()).throw(RuntimeError("missing share")))

    path = service_state_support.service_state_path(env)

    assert str(path).endswith(f"{env.target}/service_state.json")
    assert path.exists() is False
    assert path.parent.exists()


def test_service_health_path_falls_back_when_resolve_share_path_is_missing(tmp_path):
    env = _build_env(tmp_path, resolve_share_path=lambda _path: (_ for _ in ()).throw(RuntimeError("missing share")))

    path = service_state_support.service_health_path(
        env,
        health_output_path=Path("nested/health.json"),
    )

    assert str(path).endswith(f"{env.target}/nested/health.json")
    assert path.parent.exists()


def test_service_health_path_covers_default_relative_fallback(tmp_path):
    env = _build_env(tmp_path, resolve_share_path=lambda _path: (_ for _ in ()).throw(RuntimeError("missing share")))

    path = service_state_support.service_health_path(env)

    assert str(path).endswith(f"{env.target}/health.json")
    assert path.parent.exists()


def test_service_finalize_response_without_health_path():
    agi = _build_agi()
    env = _build_env(Path("/tmp"))
    agi._service_write_health_payload = lambda *_args, **_kwargs: None

    payload = service_state_support.service_finalize_response(agi, env, {"status": "idle"}, health_only=False)

    assert payload["status"] == "idle"
    assert "health_path" not in payload
    assert payload["health"]["schema"] == "agi.service.health.v1"


def test_service_health_payload_ignores_invalid_timeout_value(tmp_path):
    env = _build_env(tmp_path)

    payload = service_state_support.service_health_payload(
        env,
        {"status": "running", "heartbeat_timeout_sec": "not-a-number"},
    )

    assert payload["status"] == "running"
    assert "heartbeat_timeout_sec" not in payload


def test_service_read_heartbeats_and_payloads_return_empty_without_dir():
    agi = _build_agi()
    agi._service_queue_heartbeats = None

    assert service_state_support.service_read_heartbeats(agi) == {}
    assert service_state_support.service_read_heartbeat_payloads(agi) == {}


def test_service_read_heartbeats_and_payloads_skip_non_dict_payload(tmp_path):
    agi = _build_agi()
    hb_dir = tmp_path / "heartbeats"
    hb_dir.mkdir(parents=True, exist_ok=True)
    agi._service_queue_heartbeats = hb_dir
    (hb_dir / "list.json").write_text(json.dumps(["not", "dict"]), encoding="utf-8")

    assert service_state_support.service_read_heartbeats(agi) == {}
    assert service_state_support.service_read_heartbeat_payloads(agi) == {}


def test_service_unhealthy_workers_returns_empty_for_no_workers():
    agi = _build_agi()
    assert service_state_support.service_unhealthy_workers(agi, []) == {}


def test_service_unhealthy_workers_reports_loop_missing_and_stale(tmp_path):
    agi = _build_agi()
    hb_dir = tmp_path / "heartbeats"
    hb_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()

    (hb_dir / "ok.json").write_text(
        json.dumps({"worker": "w_ok", "timestamp": now, "state": "running"}),
        encoding="utf-8",
    )
    (hb_dir / "stale.json").write_text(
        json.dumps({"worker": "w_stale", "timestamp": now - 8.0, "state": "running"}),
        encoding="utf-8",
    )

    agi._service_queue_heartbeats = hb_dir
    agi._service_started_at = now - 20.0
    agi._service_heartbeat_timeout = 1.0
    agi._service_futures = {
        "w_loop": _FakeFuture(status="finished"),
        "w_ok": _FakeFuture(status="running"),
        "w_missing": _FakeFuture(status="running"),
        "w_stale": _FakeFuture(status="running"),
    }

    reasons = service_state_support.service_unhealthy_workers(agi, ["w_loop", "w_ok", "w_missing", "w_stale"])

    assert reasons["w_loop"] == "loop-finished"
    assert reasons["w_missing"] == "missing-heartbeat"
    assert reasons["w_stale"].startswith("stale-heartbeat(")
    assert "w_ok" not in reasons


def test_service_worker_health_builds_mixed_report():
    agi = _build_agi()
    now = time.time()
    agi._service_started_at = now - 30.0
    agi._service_heartbeat_timeout = 2.0
    agi._service_futures = {
        "w_good": _FakeFuture(status="running"),
        "w_bad": _FakeFuture(status="error"),
    }
    agi._service_read_heartbeat_payloads = lambda: {
        "w_good": {"worker": "w_good", "timestamp": now - 0.5, "state": "running"},
        "w_bad": {"worker": "w_bad", "timestamp": now - 0.2, "state": "running"},
    }
    agi._service_unhealthy_workers = lambda workers: {"w_bad": "loop-error"}

    report = service_state_support.service_worker_health(agi, ["w_good", "w_bad", "w_new"])
    by_worker = {row["worker"]: row for row in report}

    assert by_worker["w_good"]["healthy"] is True
    assert by_worker["w_bad"]["healthy"] is False
    assert by_worker["w_bad"]["reason"] == "loop-error"
    assert by_worker["w_new"]["future_state"] == "detached"
    assert by_worker["w_new"]["healthy"] is False


def test_service_health_payload_counts_and_fields(tmp_path):
    env = _build_env(tmp_path)

    payload = service_state_support.service_health_payload(
        env,
        {
            "status": "running",
            "workers": ["w1", "w2"],
            "pending": ["p1"],
            "restarted_workers": ["w2"],
            "restart_reasons": {"w2": "missing-heartbeat"},
            "queue": {"pending": 1, "done": 2},
            "queue_dir": Path("/tmp/queue"),
            "heartbeat_timeout_sec": "9.5",
            "client_status": "running",
            "cleanup": {"done": 0, "failed": 1, "heartbeats": 1},
            "worker_health": [
                {"worker": "w1", "healthy": True},
                {"worker": "w2", "healthy": False},
                "bad-row",
                {"worker": "", "healthy": True},
            ],
        },
    )

    assert payload["schema"] == "agi.service.health.v1"
    assert payload["status"] == "running"
    assert payload["workers_running_count"] == 2
    assert payload["workers_pending_count"] == 1
    assert payload["workers_restarted_count"] == 1
    assert payload["workers_healthy"] == ["w1"]
    assert payload["workers_unhealthy"] == ["w2"]
    assert payload["heartbeat_timeout_sec"] == 9.5
    assert payload["queue_dir"] == "/tmp/queue"
    assert payload["restart_reasons"]["w2"] == "missing-heartbeat"


def test_service_read_heartbeats_keeps_latest_and_ignores_bad(tmp_path):
    agi = _build_agi()
    hb_dir = tmp_path / "heartbeats"
    hb_dir.mkdir(parents=True, exist_ok=True)
    agi._service_queue_heartbeats = hb_dir

    (hb_dir / "a.json").write_text(json.dumps({"worker": "w1", "timestamp": 1.0}), encoding="utf-8")
    (hb_dir / "b.json").write_text(json.dumps({"worker": "w1", "timestamp": 3.0}), encoding="utf-8")
    (hb_dir / "c.json").write_text(json.dumps({"worker": "w2", "timestamp": 2.0, "state": "running"}), encoding="utf-8")
    (hb_dir / "bad.json").write_text("not-json", encoding="utf-8")
    (hb_dir / "zero.json").write_text(json.dumps({"worker": "w3", "timestamp": 0}), encoding="utf-8")

    beats = service_state_support.service_read_heartbeats(agi)
    payloads = service_state_support.service_read_heartbeat_payloads(agi)

    assert beats == {"w1": 3.0, "w2": 2.0}
    assert set(payloads) == {"w1", "w2"}
    assert float(payloads["w1"]["timestamp"]) == 3.0


def test_service_cleanup_artifacts_ttl_and_max_files(tmp_path):
    agi = _build_agi()
    done_dir = tmp_path / "done"
    failed_dir = tmp_path / "failed"
    hb_dir = tmp_path / "heartbeats"
    for folder in (done_dir, failed_dir, hb_dir):
        folder.mkdir(parents=True, exist_ok=True)

    done_old = done_dir / "old.task.pkl"
    done_new = done_dir / "new.task.pkl"
    failed_old = failed_dir / "old.task.pkl"
    hb_old = hb_dir / "old.json"
    hb_new = hb_dir / "new.json"
    for file_path in (done_old, done_new, failed_old, hb_old, hb_new):
        file_path.write_text("x", encoding="utf-8")

    now = time.time()
    os.utime(done_old, (now - 1000, now - 1000))
    os.utime(done_new, (now - 5, now - 5))
    os.utime(failed_old, (now - 1000, now - 1000))
    os.utime(hb_old, (now - 1000, now - 1000))
    os.utime(hb_new, (now - 10, now - 10))

    agi._service_queue_done = done_dir
    agi._service_queue_failed = failed_dir
    agi._service_queue_heartbeats = hb_dir
    agi._service_cleanup_done_ttl_sec = 100.0
    agi._service_cleanup_failed_ttl_sec = 100.0
    agi._service_cleanup_heartbeat_ttl_sec = 100.0
    agi._service_cleanup_done_max_files = 10
    agi._service_cleanup_failed_max_files = 10
    agi._service_cleanup_heartbeat_max_files = 1

    cleaned = service_state_support.service_cleanup_artifacts(agi)

    assert cleaned["done"] == 1
    assert cleaned["failed"] == 1
    assert cleaned["heartbeats"] == 1
    assert done_old.exists() is False
    assert failed_old.exists() is False
    assert hb_old.exists() is False
    assert done_new.exists() is True
    assert hb_new.exists() is True


def test_service_cleanup_artifacts_removes_overflow_and_ignores_missing_unlinks(tmp_path, monkeypatch):
    agi = _build_agi()
    done_dir = tmp_path / "done"
    failed_dir = tmp_path / "failed"
    hb_dir = tmp_path / "heartbeats"
    for folder in (done_dir, failed_dir, hb_dir):
        folder.mkdir(parents=True, exist_ok=True)

    done_a = done_dir / "a.task.pkl"
    done_b = done_dir / "b.task.pkl"
    done_c = done_dir / "c.task.pkl"
    for idx, file_path in enumerate((done_a, done_b, done_c), start=1):
        file_path.write_text("x", encoding="utf-8")
        os.utime(file_path, (100 + idx, 100 + idx))

    agi._service_queue_done = done_dir
    agi._service_queue_failed = failed_dir
    agi._service_queue_heartbeats = hb_dir
    agi._service_cleanup_done_ttl_sec = 0.0
    agi._service_cleanup_failed_ttl_sec = 0.0
    agi._service_cleanup_heartbeat_ttl_sec = 0.0
    agi._service_cleanup_done_max_files = 1
    agi._service_cleanup_failed_max_files = 10
    agi._service_cleanup_heartbeat_max_files = 10

    original_unlink = Path.unlink

    def _patched_unlink(self, *args, **kwargs):
        if self == done_a:
            raise FileNotFoundError("gone")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(service_state_support.Path, "unlink", _patched_unlink, raising=False)

    cleaned = service_state_support.service_cleanup_artifacts(agi)

    assert cleaned["done"] == 1
    assert done_c.exists()
    assert done_b.exists() is False
