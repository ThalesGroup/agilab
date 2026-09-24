"""Runtime distribution refuses invalid plans before dispatching worker work."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agi_cluster.agi_distributor.runtime import runtime_distribution_support as runtime
from agi_cluster.agi_distributor.deployment import deployment_local_support as deployment


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [None, "invalid", 0, -1])
async def test_stop_rejects_invalid_timeout_before_claiming_cleanup(timeout):
    state = SimpleNamespace(_service_cleanup_unproven=False)
    with pytest.raises(ValueError, match="positive number"):
        await runtime.stop(state, cleanup_timeout=timeout)
    assert state._service_cleanup_unproven is False
    assert not hasattr(state, "_runtime_cleanup_task")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_prior_failed_or_cancelled_cleanup_task_is_consumed_for_retry(failure):
    async def operation():
        if failure:
            raise OSError("prior cleanup failed")
        await asyncio.Future()
    task = asyncio.create_task(operation())
    await asyncio.sleep(0)
    if not failure:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    state = SimpleNamespace(_runtime_cleanup_task=task)
    log = Mock()
    assert runtime._reusable_runtime_cleanup_task(state, log=log) is None
    assert state._runtime_cleanup_task is None
    log.warning.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("workers,plan", [([], [[1]]), (["worker"], [[1], [2]])])
async def test_distribution_refuses_plan_without_matching_worker_slots(monkeypatch, workers, plan):
    client = SimpleNamespace(
        scheduler_info=Mock(return_value={"workers": {f"tcp://{worker}": {} for worker in workers}}),
        gather=Mock(return_value=[]), submit=Mock(return_value=object()),
    )
    state = SimpleNamespace(
        env=SimpleNamespace(debug=False, app="demo_project"), _dask_client=client,
        _mode=0, verbose=0, _workers={}, _args={}, _capacity={},
        _scale_cluster=Mock(), _calibration=AsyncMock(),
    )
    dispatcher = SimpleNamespace(_do_distrib=AsyncMock(return_value=({}, plan, [])))
    worker = SimpleNamespace(_new=Mock(), _do_works=Mock())
    with pytest.raises(RuntimeError, match="no configured Dask workers|more non-empty worker chunks"):
        await runtime.distribute(state, work_dispatcher_cls=dispatcher, base_worker_cls=worker, log=Mock())
    assert all(call.args[0] is worker._new for call in client.submit.call_args_list)
    assert state._work_plan == plan


def test_worker_upload_cleanup_preserves_directories_matching_ui_filenames(tmp_path):
    (tmp_path / "app_args_form.py").mkdir()
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "demo_args_form.cpython-313.pyc").mkdir()
    assert runtime._clean_top_level_ui_source_artifacts(tmp_path, log=Mock()) == []
    assert (tmp_path / "app_args_form.py").is_dir()
    assert cache.is_dir()


def test_empty_worker_top_level_metadata_stays_empty():
    assert runtime._sanitize_egg_top_level_metadata(
        "EGG-INFO/top_level.txt", b"app_args_form\ndemo_args_form\n"
    ) == b""


def test_manager_app_path_supplies_app_name_when_explicit_name_is_absent(tmp_path):
    assert runtime._manager_app_name(SimpleNamespace(active_app=tmp_path / "demo_project")) == "demo_project"


@pytest.mark.asyncio
async def test_empty_multi_package_install_does_not_create_environment(tmp_path):
    run = AsyncMock()
    await deployment._install_many_into_project_venv("uv", tmp_path, [], run_fn=run)
    run.assert_not_awaited()
    assert not (tmp_path / ".venv").exists()


def test_non_source_postinstall_needs_no_editable_overlay():
    assert deployment._worker_post_install_run_overlay_args(SimpleNamespace(is_source_env=False)) == ""


def test_remove_missing_environment_path_does_not_call_subprocess(tmp_path, monkeypatch):
    subprocess_run = Mock()
    monkeypatch.setattr(deployment.subprocess, "run", subprocess_run)
    deployment._force_remove(tmp_path / "missing")
    subprocess_run.assert_not_called()


@pytest.mark.parametrize("timing", ["mode banana", "mode banana seconds", "mode 1 fortnight", "mode 1 seconds 2"])
def test_capacity_timing_rejects_unparseable_duration(timing):
    from agi_cluster.agi_distributor.runtime import capacity_support as capacity
    with pytest.raises(ValueError, match="Unexpected run format"):
        capacity._parse_run_timing(timing)


@pytest.mark.parametrize("info", [None, [], "unknown"])
def test_capacity_update_missing_feature_row_never_produces_training_data(info):
    from agi_cluster.agi_distributor.runtime import capacity_support as capacity
    state = SimpleNamespace(_workers={"worker": 1})
    assert capacity._capacity_update_row(state, "worker:1", info, 1.0) is None


@pytest.mark.parametrize("rows", [["local run"], [None, {}, []]])
def test_malformed_capacity_feedback_does_not_retrain(tmp_path, rows):
    from agi_cluster.agi_distributor.runtime import capacity_support as capacity
    state = SimpleNamespace(_run_time=rows, workers_info={}, _train_capacity=Mock(),
                            _capacity_data_file=tmp_path / "capacity.csv")
    capacity.update_capacity(state)
    state._train_capacity.assert_not_called()
    assert not state._capacity_data_file.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("info", [None, {"only_one_feature": 1}])
async def test_calibration_invalid_worker_features_use_uniform_fallback(monkeypatch, info):
    from agi_cluster.agi_distributor.runtime import capacity_support as capacity
    monkeypatch.setattr(capacity, "_restore_calibration_cache", lambda *_args, **_kwargs: False)
    store = Mock()
    monkeypatch.setattr(capacity, "_store_calibration_cache", store)
    predictor = SimpleNamespace(predict=Mock())
    client = SimpleNamespace(run=Mock(return_value={}), gather=Mock(return_value=[{"tcp://worker:1": info}]))
    state = SimpleNamespace(_dask_client=client, _dask_workers=["worker:1"],
                            _workers={"worker": 1}, _capacity_predictor=predictor)
    await capacity.calibration(state, log=Mock())
    assert state._capacity == {"worker:1": 1.0}
    assert state.workers_info == {"worker:1": {"label": 1.0}}
    predictor.predict.assert_not_called()
    store.assert_called_once()
