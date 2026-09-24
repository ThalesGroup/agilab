"""Batch ownership and argument contracts of built-in evidence workers."""

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src/agilab/apps/builtin"


@pytest.fixture(params=("mission_decision", "data_quality_gate"))
def worker_module(request, monkeypatch):
    name = request.param
    monkeypatch.syspath_prepend(str(ROOT / (name + "_project") / "src"))
    module = importlib.import_module(name + "_worker." + name + "_worker")
    monkeypatch.setattr(module, "_runtime", {})
    monkeypatch.setattr(module.BaseWorker, "_t0", None)
    cls = getattr(
        module, "".join(part.capitalize() for part in name.split("_")) + "Worker"
    )
    return module, cls


@pytest.mark.parametrize(
    "plan,expected",
    [
        (None, []),
        ([], []),
        ([[["other"]]], []),
        ([[], "not-a-batch-list"], []),
        (
            [["other"], [["first", "second"], ("third",), "fourth"]],
            ["first", "second", "third", "fourth"],
        ),
    ],
)
@pytest.mark.parametrize("existing_clock", [False, True])
def test_evidence_worker_dispatches_only_owned_batches_and_finishes(
    worker_module, monkeypatch, plan, expected, existing_clock
):
    module, cls = worker_module
    worker = object.__new__(cls)
    worker._worker_id = 1
    events = []
    worker.work_init = lambda: events.append(("init", None))
    worker.work_pool = lambda item: events.append(("work", item)) or {"item": item}
    worker.work_done = lambda result: events.append(("done", result["item"]))
    worker.stop = lambda: events.append(("stop", None))
    monkeypatch.setattr(module.BaseWorker, "_t0", 7.0 if existing_clock else None)
    times = iter([10.0, 12.0])
    monkeypatch.setattr(module.time, "time", lambda: next(times))
    elapsed = worker.works(plan, workers_plan_metadata={"ignored": True})
    assert events == [("init", None)] + [
        event for item in expected for event in (("work", item), ("done", item))
    ] + [("stop", None)]
    assert elapsed == (3.0 if existing_clock else 2.0)


@pytest.mark.parametrize("as_namespace", [False, True])
def test_evidence_pool_initializer_replaces_stale_runtime_arguments(
    worker_module, as_namespace
):
    module, cls = worker_module
    worker = object.__new__(cls)
    worker.args = SimpleNamespace(reset_target=False)
    raw = {"reset_target": True}
    worker.pool_init({"args": SimpleNamespace(**raw) if as_namespace else raw})
    assert worker._current_args().reset_target is True
    worker.pool_init({})
    assert worker._current_args().reset_target is False


@pytest.mark.parametrize("as_namespace", [False, True])
def test_evidence_worker_argument_defaults_ignore_private_runtime_fields(
    worker_module, as_namespace
):
    module, _ = worker_module
    raw = {"reset_target": True, "_private_runtime": "do not persist"}
    result = module._args_with_defaults(SimpleNamespace(**raw) if as_namespace else raw)
    assert result.reset_target is True
    assert not hasattr(result, "_private_runtime")


@pytest.mark.parametrize(
    "payload,message", [("[]", "JSON object"), ('{"routes": null}', "candidate routes")]
)
def test_mission_worker_rejects_malformed_scenario_before_artifact_generation(
    tmp_path, monkeypatch, payload, message
):
    monkeypatch.syspath_prepend(str(ROOT / "mission_decision_project/src"))
    module = importlib.import_module("mission_decision_worker.mission_decision_worker")
    source = tmp_path / "scenario.json"
    source.write_text(payload)
    worker = object.__new__(module.MissionDecisionWorker)
    with pytest.raises(ValueError, match=message):
        worker._load_scenario(source)


@pytest.mark.parametrize("resolver", ["input", "legacy", "none"])
def test_quality_optional_path_resolution_keeps_input_confinement(
    tmp_path, monkeypatch, resolver
):
    monkeypatch.syspath_prepend(str(ROOT / "data_quality_gate_project/src"))
    module = importlib.import_module(
        "data_quality_gate_worker.data_quality_gate_worker"
    )
    calls = []
    env = SimpleNamespace()
    if resolver != "none":

        def resolve(path):
            calls.append(path)
            return tmp_path / path

        setattr(
            env,
            "resolve_share_input_path" if resolver == "input" else "resolve_share_path",
            resolve,
        )
    assert module._resolve_optional_share_path(env, None) is None
    assert calls == []
    actual = module._resolve_optional_share_path(env, Path("inputs/candidate.csv"))
    assert actual == (
        Path("inputs/candidate.csv")
        if resolver == "none"
        else tmp_path / "inputs/candidate.csv"
    )
    if resolver != "none":
        assert calls == [Path("inputs/candidate.csv")]


def test_quality_artifact_copy_preserves_nested_layout_and_self_copy_is_noop(
    tmp_path, monkeypatch
):
    monkeypatch.syspath_prepend(str(ROOT / "data_quality_gate_project/src"))
    module = importlib.import_module(
        "data_quality_gate_worker.data_quality_gate_worker"
    )
    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    (source / "nested/result.json").write_text('{"passed": true}')
    module._copy_artifacts(source, source)
    destination = tmp_path / "destination"
    module._copy_artifacts(source, destination)
    assert (destination / "nested/result.json").read_bytes() == (
        source / "nested/result.json"
    ).read_bytes()


@pytest.fixture
def weather_worker(monkeypatch):
    # Forecast training is outside these input/startup contracts. Fail loudly if
    # a tested path starts invoking the optional engine.
    import sys
    from types import ModuleType

    def no_training(*args, **kwargs):
        pytest.fail("input/runtime contract unexpectedly invoked forecasting")

    for name, symbols in (
        ("skforecast", ()),
        ("skforecast.model_selection", ("TimeSeriesFold", "backtesting_forecaster")),
        ("skforecast.recursive", ("ForecasterRecursive",)),
    ):
        boundary = ModuleType(name)
        for symbol in symbols:
            setattr(boundary, symbol, no_training)
        monkeypatch.setitem(sys.modules, name, boundary)
    for name in (
        "weather_forecast_worker.weather_forecast_worker",
        "weather_forecast_worker",
    ):
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.syspath_prepend(str(ROOT / "weather_forecast_project/src"))
    module = importlib.import_module("weather_forecast_worker.weather_forecast_worker")
    monkeypatch.setattr(module, "_runtime", {})
    worker = object.__new__(module.WeatherForecastWorker)
    worker.args = SimpleNamespace(
        target_column="temperature", station="Paris", validation_days=2, lags=2
    )
    yield module, worker
    for name in (
        "weather_forecast_worker.weather_forecast_worker",
        "weather_forecast_worker",
    ):
        monkeypatch.delitem(sys.modules, name, raising=False)


@pytest.mark.parametrize(
    "rows,message",
    [
        ("date,station\n2026-01-01,Paris\n", "Missing required columns"),
        ("date,station,temperature\n2026-01-01,Lyon,12\n", "Available stations"),
        ("date,station,temperature\n2026-01-01,Paris,12\n", "Need more rows"),
    ],
)
def test_weather_worker_rejects_unforecastable_station_inputs(
    weather_worker, tmp_path, rows, message
):
    _, worker = weather_worker
    source = tmp_path / "station.csv"
    source.write_text(rows)
    with pytest.raises(ValueError, match=message):
        worker._load_station_frame(source)


def test_weather_station_loading_sorts_filters_and_resets_rows(
    weather_worker, tmp_path
):
    _, worker = weather_worker
    source = tmp_path / "station.csv"
    source.write_text(
        "date,station,temperature\n"
        + "".join(f"2026-01-0{day},Paris,{day + 10}\n" for day in [5, 3, 1, 4, 2])
        + "2026-01-01,Lyon,99\n"
    )
    result = worker._load_station_frame(source)
    assert result["temperature"].tolist() == [11, 12, 13, 14, 15]
    assert result["station"].unique().tolist() == ["Paris"]
    assert result.index.tolist() == list(range(5))


@pytest.mark.parametrize("argument_shape", ["dict", "object", "namespace"])
def test_weather_start_publishes_normalized_runtime_paths(
    weather_worker, tmp_path, monkeypatch, argument_shape
):
    module, worker = weather_worker
    values = dict(data_in="raw.csv", data_out="output", reset_target=True)
    if argument_shape == "dict":
        worker.args = values
    elif argument_shape == "namespace":
        worker.args = SimpleNamespace(**values)
    else:
        worker.args = type("AppArgs", (), {})()
        vars(worker.args).update(values)
    calls = []
    paths = SimpleNamespace(
        normalized_input="normalized/input.csv",
        normalized_output="normalized/output",
        output_path=tmp_path / "output",
    )
    worker.setup_data_directories = lambda **kwargs: calls.append(kwargs) or paths
    worker.env = SimpleNamespace()
    monkeypatch.setattr(module, "_artifact_dir", lambda env, leaf: tmp_path / leaf)
    worker.start()
    assert calls == [
        dict(
            source_path="raw.csv",
            target_path="output",
            target_subdir="results",
            reset_target=True,
        )
    ]
    assert worker.args.data_in == "normalized/input.csv"
    assert worker.args.data_out == "normalized/output"
    assert worker.data_out == tmp_path / "output"
    assert worker.artifact_dir.is_dir()
    assert module._runtime == {"args": worker.args}
    worker.pool_init({"args": {"station": "Lyon"}})
    assert worker._current_args().station == "Lyon"
    assert worker.work_init() is None


def test_weather_empty_completion_creates_no_artifacts(weather_worker, tmp_path):
    import pandas as pd

    _, worker = weather_worker
    worker.data_out = tmp_path / "output"
    worker.artifact_dir = tmp_path / "artifacts"
    worker.work_done(None)
    worker.work_done(pd.DataFrame())
    assert not worker.data_out.exists()
    assert not worker.artifact_dir.exists()
