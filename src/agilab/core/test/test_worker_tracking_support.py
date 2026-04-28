from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_env import mlflow_store
from agi_node.agi_dispatcher import worker_tracking_support as tracking_support


class FakeRunContext:
    def __init__(self, mlflow, run_id: str):
        self._mlflow = mlflow
        self._run = SimpleNamespace(info=SimpleNamespace(run_id=run_id))

    def __enter__(self):
        self._mlflow.entered.append(self._run.info.run_id)
        return self._run

    def __exit__(self, exc_type, exc, tb):
        self._mlflow.exited.append(self._run.info.run_id)
        self._mlflow.exit_exc_types.append(exc_type)
        return False


class FakeMlflow:
    def __init__(self):
        self.tracking_uri = None
        self.start_requests = []
        self.entered = []
        self.exited = []
        self.exit_exc_types = []
        self.tags = []
        self.params = []
        self.metrics = []
        self._next_run = 0

    def set_tracking_uri(self, value):
        self.tracking_uri = value

    def start_run(self, **kwargs):
        self.start_requests.append(kwargs)
        if "run_id" in kwargs:
            run_id = kwargs["run_id"]
        else:
            self._next_run += 1
            run_id = f"worker-run-{self._next_run}"
        return FakeRunContext(self, run_id)

    def set_tags(self, tags):
        self.tags.append(tags)

    def log_params(self, params):
        self.params.append(params)

    def log_metric(self, key, value):
        self.metrics.append((key, value))


def test_prepare_worker_tracking_environment_derives_uri_from_env_attribute(tmp_path):
    environ: dict[str, str] = {}
    env = SimpleNamespace(MLFLOW_TRACKING_DIR="mlflow-store", home_abs=tmp_path)

    tracking_uri = tracking_support.prepare_worker_tracking_environment(env, environ=environ)
    expected_db = tmp_path / "mlflow-store" / "mlflow.db"

    assert tracking_uri == mlflow_store.sqlite_uri_for_path(expected_db, os_name=os.name)
    assert environ[tracking_support.MLFLOW_TRACKING_DIR_ENV] == str(tmp_path / "mlflow-store")
    assert environ[tracking_support.MLFLOW_TRACKING_URI_ENV] == tracking_uri
    assert (tmp_path / "mlflow-store" / "artifacts").is_dir()


def test_prepare_worker_tracking_environment_short_circuits_existing_or_missing_config():
    existing = {tracking_support.MLFLOW_TRACKING_URI_ENV: "sqlite:///already.db"}

    assert (
        tracking_support.prepare_worker_tracking_environment(
            SimpleNamespace(MLFLOW_TRACKING_DIR="unused"),
            environ=existing,
        )
        == "sqlite:///already.db"
    )
    assert tracking_support.MLFLOW_TRACKING_DIR_ENV not in existing

    assert tracking_support.prepare_worker_tracking_environment(SimpleNamespace(), environ={}) is None


def test_worker_tracking_run_creates_nested_worker_run_and_restores_env():
    fake_mlflow = FakeMlflow()
    environ = {
        tracking_support.MLFLOW_TRACKING_URI_ENV: "sqlite:///tmp/mlflow.db",
        tracking_support.MLFLOW_RUN_ID_ENV: "parent-run",
    }
    times = iter([10.0, 12.5])

    with tracking_support.worker_tracking_run(
        worker_id=3,
        worker_name="tcp://worker:8787",
        plan_batch_count=2,
        plan_chunk_len=5,
        metadata_chunk_len=4,
        environ=environ,
        import_module_fn=lambda name: fake_mlflow if name == "mlflow" else pytest.fail(name),
        time_fn=lambda: next(times),
    ) as run:
        assert run.info.run_id == "worker-run-1"
        assert environ[tracking_support.MLFLOW_RUN_ID_ENV] == "worker-run-1"
        assert environ[tracking_support.AGILAB_RUN_ID_ENV] == "worker-run-1"

    assert environ == {
        tracking_support.MLFLOW_TRACKING_URI_ENV: "sqlite:///tmp/mlflow.db",
        tracking_support.MLFLOW_RUN_ID_ENV: "parent-run",
    }
    assert fake_mlflow.tracking_uri == "sqlite:///tmp/mlflow.db"
    assert fake_mlflow.start_requests == [
        {
            "run_name": "worker:tcp://worker:8787:3",
            "tags": {
                "agilab.component": "worker",
                "agilab.worker.id": "3",
                "agilab.worker.name": "tcp://worker:8787",
                "agilab.worker.plan_batches": "2",
                tracking_support.MLFLOW_PARENT_RUN_ID_TAG: "parent-run",
                "agilab.parent_run_id": "parent-run",
            },
        },
    ]
    assert fake_mlflow.exited == ["worker-run-1"]
    assert fake_mlflow.exit_exc_types == [None]
    assert fake_mlflow.tags[0]["agilab.component"] == "worker"
    assert fake_mlflow.tags[0]["agilab.worker.id"] == "3"
    assert fake_mlflow.tags[0][tracking_support.MLFLOW_PARENT_RUN_ID_TAG] == "parent-run"
    assert fake_mlflow.tags[-1] == {"agilab.status": "completed"}
    assert fake_mlflow.params == [{"plan_chunk_len": "5", "metadata_chunk_len": "4"}]
    assert fake_mlflow.metrics == [("agilab.worker.runtime_seconds", 2.5)]


def test_worker_tracking_run_marks_failed_and_preserves_exception():
    fake_mlflow = FakeMlflow()
    environ = {tracking_support.MLFLOW_TRACKING_URI_ENV: "sqlite:///tmp/mlflow.db"}
    times = iter([1.0, 1.25])

    with pytest.raises(RuntimeError, match="boom"):
        with tracking_support.worker_tracking_run(
            worker_id=0,
            worker_name="local",
            plan_batch_count=1,
            environ=environ,
            import_module_fn=lambda name: fake_mlflow if name == "mlflow" else pytest.fail(name),
            time_fn=lambda: next(times),
        ):
            raise RuntimeError("boom")

    assert tracking_support.MLFLOW_RUN_ID_ENV not in environ
    assert tracking_support.AGILAB_RUN_ID_ENV not in environ
    assert fake_mlflow.tags[-1]["agilab.status"] == "failed"
    assert fake_mlflow.tags[-1]["agilab.error_type"] == "RuntimeError"
    assert fake_mlflow.metrics == [("agilab.worker.runtime_seconds", 0.25)]
    assert fake_mlflow.exit_exc_types == [RuntimeError]


def test_worker_tracking_run_continues_when_mlflow_start_fails():
    debug_messages: list[str] = []
    logger = SimpleNamespace(
        debug=lambda message, *args: debug_messages.append(str(message % args if args else message))
    )
    mlflow = SimpleNamespace(
        set_tracking_uri=lambda _value: None,
        start_run=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("store unavailable")),
    )

    with tracking_support.worker_tracking_run(
        worker_id=0,
        worker_name="local",
        plan_batch_count=1,
        environ={tracking_support.MLFLOW_TRACKING_URI_ENV: "sqlite:///tmp/mlflow.db"},
        import_module_fn=lambda name: mlflow if name == "mlflow" else pytest.fail(name),
        logger_obj=logger,
    ) as run:
        assert run is None

    assert debug_messages == [
        "worker tracking disabled: failed to start MLflow run: store unavailable"
    ]


def test_worker_tracking_run_does_not_set_run_env_when_worker_run_has_no_id():
    class NoRunIdContext:
        def __enter__(self):
            return SimpleNamespace(info=SimpleNamespace(run_id=None))

        def __exit__(self, exc_type, exc, tb):
            return False

    mlflow = SimpleNamespace(
        set_tracking_uri=lambda _value: None,
        start_run=lambda **_kwargs: NoRunIdContext(),
        set_tags=lambda _tags: None,
        log_params=lambda _params: None,
        log_metric=lambda _key, _value: None,
    )
    environ = {tracking_support.MLFLOW_TRACKING_URI_ENV: "sqlite:///tmp/mlflow.db"}

    with tracking_support.worker_tracking_run(
        worker_id=0,
        worker_name=None,
        plan_batch_count=1,
        environ=environ,
        import_module_fn=lambda name: mlflow if name == "mlflow" else pytest.fail(name),
    ) as run:
        assert run.info.run_id is None
        assert tracking_support.MLFLOW_RUN_ID_ENV not in environ
        assert tracking_support.AGILAB_RUN_ID_ENV not in environ


def test_worker_tracking_run_ignores_metadata_logging_errors():
    debug_messages: list[str] = []
    logger = SimpleNamespace(
        debug=lambda message, *args: debug_messages.append(str(message % args if args else message))
    )

    class MetadataFailingMlflow(FakeMlflow):
        def set_tags(self, tags):
            raise RuntimeError("tag write failed")

    mlflow = MetadataFailingMlflow()

    with tracking_support.worker_tracking_run(
        worker_id=0,
        worker_name="local",
        plan_batch_count=1,
        environ={tracking_support.MLFLOW_TRACKING_URI_ENV: "sqlite:///tmp/mlflow.db"},
        import_module_fn=lambda name: mlflow if name == "mlflow" else pytest.fail(name),
        logger_obj=logger,
    ):
        pass

    assert debug_messages == [
        "worker tracking metadata log failed: tag write failed",
        "worker tracking metadata log failed: tag write failed",
    ]


def test_worker_tracking_run_supports_minimal_mlflow_module_without_set_tracking_uri():
    mlflow = SimpleNamespace(
        start_run=lambda **_kwargs: FakeRunContext(
            SimpleNamespace(entered=[], exited=[], exit_exc_types=[]),
            "worker-run",
        ),
        set_tags=lambda _tags: None,
        log_params=lambda _params: None,
        log_metric=lambda _key, _value: None,
    )

    with tracking_support.worker_tracking_run(
        worker_id=0,
        worker_name="local",
        plan_batch_count=1,
        environ={tracking_support.MLFLOW_TRACKING_URI_ENV: "sqlite:///tmp/mlflow.db"},
        import_module_fn=lambda name: mlflow if name == "mlflow" else pytest.fail(name),
    ) as run:
        assert run.info.run_id == "worker-run"


def test_worker_tracking_run_noops_without_mlflow_or_tracking_uri():
    with tracking_support.worker_tracking_run(
        worker_id=0,
        worker_name="local",
        plan_batch_count=1,
        environ={},
        import_module_fn=lambda name: pytest.fail(name),
    ) as run:
        assert run is None

    with tracking_support.worker_tracking_run(
        worker_id=0,
        worker_name="local",
        plan_batch_count=1,
        environ={tracking_support.MLFLOW_TRACKING_URI_ENV: "sqlite:///tmp/mlflow.db"},
        import_module_fn=lambda _name: (_ for _ in ()).throw(ImportError("missing")),
    ) as run:
        assert run is None


def test_worker_tracking_private_helpers_cover_edge_cases():
    assert tracking_support._truncate("abcdef", 1) == "a"
    assert tracking_support._truncate("abcdef", 4) == "abc..."
    assert tracking_support._clean(None) == ""
    tracking_support._log_debug(None, "ignored")
