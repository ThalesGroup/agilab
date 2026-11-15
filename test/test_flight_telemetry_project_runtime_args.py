from __future__ import annotations

import json
import math
import sys
import tomllib
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest
from agi_node import MutableNamespace
from agi_node.reduction import ReduceArtifact
from packaging.requirements import Requirement


def _import_flight_modules(monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    app_src = repo_root / "src" / "agilab" / "apps" / "builtin" / "flight_telemetry_project" / "src"
    monkeypatch.syspath_prepend(str(app_src))
    existing = sys.modules.get("flight_telemetry")
    if existing is not None and not hasattr(existing, "__path__"):
        monkeypatch.delitem(sys.modules, "flight_telemetry", raising=False)
    from flight_telemetry.flight_telemetry import FlightTelemetry as Flight
    from flight_telemetry_worker.flight_telemetry_worker import FlightTelemetryWorker as FlightWorker

    return Flight, FlightWorker


def test_flight_telemetry_project_declares_polars_runtime_compat():
    repo_root = Path(__file__).resolve().parents[1]
    pyproject = (
        repo_root
        / "src"
        / "agilab"
        / "apps"
        / "builtin"
        / "flight_telemetry_project"
        / "pyproject.toml"
    )
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    requirements = {Requirement(dependency).name: Requirement(dependency) for dependency in project["dependencies"]}

    assert requirements["polars"].extras == {"rtcompat"}
    assert "geopy" not in project["dependencies"]


def test_flight_telemetry_project_declares_worker_only_cython_contract():
    repo_root = Path(__file__).resolve().parents[1]
    app_root = repo_root / "src" / "agilab" / "apps" / "builtin" / "flight_telemetry_project"
    settings = tomllib.loads((app_root / "src" / "app_settings.toml").read_text(encoding="utf-8"))
    worker_project = tomllib.loads(
        (app_root / "src" / "flight_telemetry_worker" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert settings["cluster"]["cython"] is True
    assert {"setuptools", "cython"} <= set(worker_project["build-system"]["requires"])


class _FakeEnv:
    verbose = 0
    _is_managed_pc = False

    def __init__(self, share_root: Path) -> None:
        self.share_root = share_root
        self.home_abs = share_root.parent
        self.agi_share_path_abs = share_root
        self.agi_share_path = share_root
        self.AGI_LOCAL_SHARE = str(share_root)
        self.target = "flight_telemetry"

    def share_root_path(self):
        return self.share_root

    def resolve_share_path(self, value):
        path = Path(value)
        if path.is_absolute():
            return path
        return self.share_root / path


def test_flight_manager_ignores_agi_step_list_args(monkeypatch, tmp_path):
    Flight, _ = _import_flight_modules(monkeypatch)
    env = _FakeEnv(tmp_path / "share")

    flight = Flight(
        env,
        args=[{"name": "uav_graph_routing_ppo", "args": {"seed": 0}}],
        data_in="network_sim/pipeline",
        data_out="uav_graph_routing/pipeline",
        reset_target=False,
    )

    assert flight.args.data_source == "file"
    assert flight.args.data_in == tmp_path / "share" / "network_sim" / "pipeline"
    assert flight.args.data_out == tmp_path / "share" / "uav_graph_routing" / "pipeline"


def test_flight_manager_rejects_unsupported_hawk_source(monkeypatch, tmp_path):
    Flight, _ = _import_flight_modules(monkeypatch)

    with pytest.raises(ValueError, match="file-based input"):
        Flight(
            _FakeEnv(tmp_path / "share"),
            data_source="hawk",
            data_in="hawk.cluster.local:9200",
        )


def test_flight_args_validation_persistence_and_default_helpers(monkeypatch, tmp_path):
    _import_flight_modules(monkeypatch)
    from flight_telemetry.flight_args import (
        ARGS_SECTION,
        FlightArgs,
        apply_source_defaults,
        dump_args,
        dump_args_to_toml,
        ensure_defaults,
        load_args,
        load_args_from_toml,
        merge_args,
    )

    migrated = FlightArgs(data_uri="flight_telemetry/custom", files="*.csv", nfile=0, data_out="")
    assert migrated.data_in == Path("flight_telemetry/custom")
    assert migrated.data_out == Path("flight_telemetry/dataframe")
    assert migrated.nfile == 999_999_999_999
    assert migrated.to_toml_payload()["datemin"] == "2020-01-01"

    with pytest.raises(ValueError, match="file-based input"):
        FlightArgs(data_source="hawk")
    with pytest.raises(TypeError, match="data_in must be"):
        FlightArgs(data_in=object())
    with pytest.raises(TypeError, match="data_out must be"):
        FlightArgs(data_out=object())
    with pytest.raises(ValueError, match="datemin must be on or after"):
        FlightArgs(datemin="2019-12-31")
    with pytest.raises(ValueError, match="datemax must be on or after datemin"):
        FlightArgs(datemin="2020-02-01", datemax="2020-01-01")
    with pytest.raises(ValueError, match="datemax must be on or before"):
        FlightArgs(datemax="2022-01-01")
    with pytest.raises(ValueError, match="not a valid regex"):
        FlightArgs(files="[")
    with pytest.raises(ValueError):
        FlightArgs.model_validate("not-a-dict")
    with pytest.raises(ValueError, match="file-based input"):
        apply_source_defaults(SimpleNamespace(data_source="hawk"))

    base = FlightArgs(data_in="flight_telemetry/dataset", files="")
    with_defaults = apply_source_defaults(base)
    assert with_defaults.files == "*"
    assert ensure_defaults(FlightArgs(files="*.csv")) is not None
    unchanged = FlightArgs(files="*.csv")
    assert apply_source_defaults(unchanged) is unchanged
    merged = merge_args(unchanged, {"files": ".*\\.csv", "output_format": "csv"})
    assert merged.files == ".*\\.csv"
    assert merged.output_format == "csv"

    settings_path = tmp_path / "app_settings.toml"
    dump_args_to_toml(merged, settings_path)
    dump_args_to_toml(merged, settings_path)
    loaded = load_args_from_toml(settings_path)
    assert loaded.files == ".*\\.csv"
    assert load_args(settings_path).files == ".*\\.csv"
    dumped_path = tmp_path / "dumped.toml"
    dump_args(loaded, dumped_path)
    assert tomllib.loads(dumped_path.read_text(encoding="utf-8"))[ARGS_SECTION]["output_format"] == "csv"
    with pytest.raises(FileNotFoundError, match="Settings file not found"):
        dump_args_to_toml(loaded, tmp_path / "missing.toml", create_missing=False)


def test_flight_manager_constructor_and_helper_branches(monkeypatch, tmp_path):
    Flight, _ = _import_flight_modules(monkeypatch)
    import flight_telemetry.flight_telemetry as flight_module
    from flight_telemetry.flight_args import FlightArgs

    env = _FakeEnv(tmp_path / "share")
    existing_out = env.share_root / "existing-output"
    existing_out.mkdir(parents=True)
    (existing_out / "stale.txt").write_text("old", encoding="utf-8")

    direct = Flight(
        env,
        args=FlightArgs(data_in="flight_telemetry/dataset", data_out="existing-output", reset_target=True),
    )
    assert direct.args.data_in == env.share_root / "flight_telemetry" / "dataset"
    assert not (existing_out / "stale.txt").exists()

    from_dict = Flight(env, args={"data_in": "dict-in", "data_out": "dict-out", "reset_target": False})
    assert from_dict.args.data_in == env.share_root / "dict-in"

    from_object = Flight(
        env,
        args=SimpleNamespace(data_in="object-in", data_out="object-out", reset_target=False),
    )
    assert from_object.args.data_out == env.share_root / "object-out"

    class SlotOnly:
        __slots__ = ()

    with pytest.raises(ValueError, match="Invalid FlightTelemetry arguments"):
        Flight(env, args=SlotOnly())

    settings_path = tmp_path / "flight_settings.toml"
    settings_path.write_text(
        "[args]\ndata_in = 'settings-in'\ndata_out = 'settings-out'\nreset_target = false\n",
        encoding="utf-8",
    )
    loaded = Flight.from_toml(env, settings_path, data_out="override-out")
    assert loaded.args.data_out == env.share_root / "override-out"
    loaded.to_toml(tmp_path / "written_settings.toml")
    assert loaded.as_dict()["data_source"] == "file"

    assert Flight.extract_plane_from_file_name("logs/prefix_value_AC34.csv") == 34
    with pytest.raises(NotImplementedError, match="file-based input"):
        direct.get_data_from_hawk()

    monkeypatch.setattr(direct, "get_data_from_files", lambda: pl.DataFrame({"files": ["60_dummy.csv"], "size": [1000]}))
    monkeypatch.setattr(flight_module.WorkDispatcher, "make_chunks", lambda *_args, **_kwargs: [])
    assert direct.build_distribution({"127.0.0.1": 1}) == ([], [], "plane", "files", "KB")

    def fail_inventory():
        raise OSError("bad inventory")

    monkeypatch.setattr(direct, "get_data_from_files", fail_inventory)
    with pytest.raises(RuntimeError, match="Unable to build flight distribution"):
        direct.build_distribution({"127.0.0.1": 1})


def test_flight_manager_file_inventory_error_and_absolute_display(monkeypatch, tmp_path):
    Flight, _ = _import_flight_modules(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    share_root = tmp_path / "outside-share"
    source_root = share_root / "flight_telemetry" / "dataset"
    source_root.mkdir(parents=True)
    source = source_root / "60_abs.csv"
    source.write_text("x" * 1000, encoding="utf-8")

    flight = Flight(
        _FakeEnv(share_root),
        data_in="flight_telemetry/dataset",
        data_out="flight_telemetry/dataframe",
        files="*.csv",
        reset_target=False,
    )

    assert flight.get_data_from_files().to_dict(as_series=False) == {
        "files": [str(source)],
        "size": [1],
    }

    missing = Flight(
        _FakeEnv(share_root),
        data_in="missing",
        data_out="flight_telemetry/dataframe",
        files="*.csv",
        reset_target=False,
    )
    with pytest.raises(FileNotFoundError, match="no files found"):
        missing.get_data_from_files()

    raw = object.__new__(Flight)
    raw.args = MutableNamespace(data_source="hawk", data_in="hawk", files="*.csv")
    with pytest.raises(NotImplementedError, match="file-based input"):
        raw.get_data_from_files()


def test_flight_manager_rejects_share_root_reset(monkeypatch, tmp_path):
    Flight, _ = _import_flight_modules(monkeypatch)
    from flight_telemetry.flight_args import FlightArgs

    env = _FakeEnv(tmp_path / "share")
    env.share_root.mkdir(parents=True)
    marker = env.share_root / "important.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="confinement root"):
        Flight(
            env,
            args=FlightArgs(
                data_in="flight_telemetry/dataset",
                data_out=".",
                reset_target=True,
            ),
        )

    assert marker.read_text(encoding="utf-8") == "keep"


def test_flight_manager_builds_typed_file_inventory(monkeypatch, tmp_path):
    Flight, _ = _import_flight_modules(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    share_root = tmp_path / "localshare"
    source_root = share_root / "flight_cluster_validation" / "dataset" / "csv"
    source_root.mkdir(parents=True)
    first = source_root / "61_6101.csv"
    second = source_root / "60_5984.csv"
    first.write_text("a" * 2222, encoding="utf-8")
    second.write_text("b" * 3333, encoding="utf-8")

    flight = Flight(
        _FakeEnv(share_root),
        data_in="flight_cluster_validation/dataset/csv",
        data_out="flight_cluster_validation/dataframe",
        files="*.csv",
        reset_target=True,
    )

    df = flight.get_data_from_files()

    assert df.schema == {"files": pl.String, "size": pl.Int64}
    assert df.to_dict(as_series=False) == {
        "files": [
            "localshare/flight_cluster_validation/dataset/csv/60_5984.csv",
            "localshare/flight_cluster_validation/dataset/csv/61_6101.csv",
        ],
        "size": [3, 2],
    }

    work_plan, metadata, partition_key, weights_key, weights_unit = flight.build_distribution(
        {"127.0.0.1": 1}
    )

    assert work_plan == [
        [
            [{"schema": "flight_telemetry.input_file.v1", "path": "60_5984.csv"}],
            [{"schema": "flight_telemetry.input_file.v1", "path": "61_6101.csv"}],
        ]
    ]
    assert metadata == [[(60, 0.003), (61, 0.002)]]
    assert partition_key == "plane"
    assert weights_key == "files"
    assert weights_unit == "KB"



@pytest.fixture
def flight_input_path_case(monkeypatch, tmp_path, request):
    Flight, FlightWorker = _import_flight_modules(monkeypatch)
    manager_home = tmp_path / "manager-home"
    worker_home = tmp_path / "worker-home"
    manager_root = tmp_path / "manager-backing" / "workflow"
    worker_root = tmp_path / "worker-mount" / "workflow"
    relative_file = Path("csv") / "60_crosshost.csv"
    contents = (
        "aircraft,date,lat,long,altitude,heading\n"
        "A1,2021-01-01 00:00:00,48.0000,2.0000,1000,20\n"
        "A1,2021-01-01 00:01:00,48.0005,2.0005,1100,\n"
        "A1,2021-01-01 00:02:00,,2.0010,1200,30\n"
    )
    for root in (manager_root, worker_root):
        source = root / "dataset" / relative_file
        source.parent.mkdir(parents=True)
        source.write_text(contents, encoding="utf-8")
    manager_env = _FakeEnv(manager_root)
    worker_env = _FakeEnv(worker_root)
    if getattr(request, "param", False):
        # The actual SDK resolver selects pre-existing physical-share input
        # when the active workflow directory has no dataset.
        for env in (manager_env, worker_env):
            env.AGILAB_WORKFLOW_DATA_ROOT = env.share_root / "runs" / "current"
            from agi_env import AgiEnv

            env.workflow_data_root_path = lambda _env=env: _env.AGILAB_WORKFLOW_DATA_ROOT
            env.resolve_share_input_path = lambda value, _env=env: (
                AgiEnv.resolve_share_input_path(_env, value)
            )
            env.resolve_share_path = lambda value, _env=env: (
                AgiEnv.resolve_share_path(_env, value)
            )
    monkeypatch.setenv("HOME", str(manager_home))
    flight = Flight(
        manager_env,
        data_in="dataset",
        data_out="output",
        files="*.csv",
        reset_target=False,
    )
    plan, metadata, *labels = flight.build_distribution({"worker": 1})
    # Transport the manager's actual plan unchanged, rather than rewriting a filename.
    plan = json.loads(json.dumps(plan))
    monkeypatch.setenv("HOME", str(worker_home))
    worker = FlightWorker()
    worker.env = worker_env
    worker.args = {
        "data_in": "dataset",
        "data_out": "output",
        "reset_target": False,
        "output_format": "parquet",
    }
    worker._worker_id = 0
    worker.worker_id = 0
    worker.verbose = 0
    worker.start()
    return SimpleNamespace(
        flight=flight,
        worker=worker,
        plan=plan,
        metadata=metadata,
        labels=labels,
        manager_root=manager_root,
        worker_root=worker_root,
        manager_source=manager_root / "dataset" / relative_file,
        worker_source=worker_root / "dataset" / relative_file,
        worker_home=worker_home,
    )


@pytest.mark.parametrize("flight_input_path_case", [False, True], indirect=True)
@pytest.mark.parametrize("execution", ["work_pool", "mono_plan"])
def test_flight_manager_plan_reads_worker_input_root(
    flight_input_path_case, monkeypatch, execution
):
    case = flight_input_path_case
    reference = case.worker.work_pool(str(case.worker_source))
    assert reference.width == 17
    assert reference.height == 3
    assert reference["lat"].null_count() == 1
    assert reference["heading"].null_count() == 1
    assert reference["speed"][0] == 0.0
    assert reference["speed"][1] == pytest.approx(66.895819, abs=0.001)
    # The manager's backing path must be unusable in the worker context.
    case.manager_source.unlink()
    if execution == "work_pool":
        result = case.worker.work_pool(case.plan[0][0][0])
    else:
        chunks = []
        monkeypatch.setattr(case.worker, "work_done", chunks.append)
        case.worker._exec_mono_process(case.plan, case.metadata)
        assert len(chunks) == 1
        result = chunks[0].drop("worker_id")
    assert result.equals(reference)
    assert case.labels == ["plane", "files", "KB"]


def test_flight_legacy_strings_keep_home_and_absolute_meaning(flight_input_path_case):
    case = flight_input_path_case
    expected = case.worker.work_pool(str(case.worker_source))
    legacy_relative = "60_legacy.csv"
    legacy_absolute = case.worker_home / legacy_relative
    legacy_absolute.parent.mkdir(parents=True, exist_ok=True)
    legacy_absolute.write_bytes(case.worker_source.read_bytes())
    # A conflicting basename under data_in must not change the legacy HOME binding.
    (Path(case.worker.args.data_in) / legacy_relative).write_text(
        "not,the,selected,file\n", encoding="utf-8"
    )
    for item in (legacy_relative, str(legacy_absolute)):
        result = case.worker.work_pool(item)
        assert result.drop("source_file").equals(expected.drop("source_file"))
        assert result["source_file"].unique().to_list() == [legacy_relative]
    with pytest.raises(FileNotFoundError):
        case.worker.work_pool(str(case.manager_root / "absent" / legacy_relative))


@pytest.mark.parametrize(
    "relative",
    [
        "../60_escape.csv",
        "csv/../../60_escape.csv",
        "/60_absolute.csv",
        "C:/60_absolute.csv",
        "C:60_drive_relative.csv",
        r"csv\..\60_escape.csv",
        r"\\server\share\60_file.csv",
        "",
        None,
        17,
    ],
)
def test_flight_input_record_rejects_unsafe_paths(flight_input_path_case, relative):
    item = {"schema": "flight_telemetry.input_file.v1", "path": relative}
    with pytest.raises(ValueError, match="flight input"):
        flight_input_path_case.worker.work_pool(item)


def test_flight_input_record_confines_symlinks(flight_input_path_case):
    case = flight_input_path_case
    root = Path(case.worker.args.data_in)
    inside = root / "60_inside.csv"
    outside = root / "60_outside.csv"
    try:
        inside.symlink_to(case.worker_source)
        outside.symlink_to(case.manager_source)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this platform")
    reference = case.worker.work_pool(str(case.worker_source))
    result = case.worker.work_pool(
        {"schema": "flight_telemetry.input_file.v1", "path": inside.name}
    )
    assert result.drop("source_file").equals(reference.drop("source_file"))
    assert result["source_file"].unique().to_list() == [inside.name]
    with pytest.raises(ValueError, match="flight input"):
        case.worker.work_pool(
            {"schema": "flight_telemetry.input_file.v1", "path": outside.name}
        )


@pytest.mark.parametrize(
    "item",
    [
        {},
        {"schema": "flight_telemetry.input_file.v2", "path": "csv/60_crosshost.csv"},
        {"schema": "flight_telemetry.input_file.v1"},
        {
            "schema": "flight_telemetry.input_file.v1",
            "path": "csv/60_crosshost.csv",
            "extra": 1,
        },
    ],
)
def test_flight_input_record_rejects_unknown_schema(flight_input_path_case, item):
    with pytest.raises(ValueError, match="flight input"):
        flight_input_path_case.worker.work_pool(item)


def test_flight_manager_rejects_input_symlink_escape(flight_input_path_case):
    case = flight_input_path_case
    link = case.manager_source.parent / "61_escape.csv"
    try:
        link.symlink_to(case.worker_source)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this platform")
    with pytest.raises(
        RuntimeError, match="Unable to build flight distribution"
    ) as error:
        case.flight.build_distribution({"worker": 1})
    assert isinstance(error.value.__cause__, ValueError)
    assert "flight input" in str(error.value.__cause__)


def test_flight_telemetry_worker_defaults_missing_data_source(monkeypatch, tmp_path):
    _, FlightWorker = _import_flight_modules(monkeypatch)
    worker = object.__new__(FlightWorker)
    worker.args = MutableNamespace(
        data_in="network_sim/pipeline",
        data_out="uav_graph_routing/pipeline",
        reset_target=False,
    )
    worker.verbose = 0
    worker._worker_id = 0
    worker.env = _FakeEnv(tmp_path / "share")
    worker.pool_vars = {}

    def fake_setup_data_directories(**_kwargs):
        return SimpleNamespace(normalized_input=str(tmp_path / "share" / "network_sim" / "pipeline"))

    worker.setup_data_directories = fake_setup_data_directories

    worker.start()

    assert worker.args.data_source == "file"
    assert worker.args.output_format == "parquet"
    assert worker.pool_vars["args"] is worker.args

    object_args_worker = object.__new__(FlightWorker)
    object_args_worker.args = SimpleNamespace(
        data_in="flight_telemetry/dataset",
        data_out="flight_telemetry/dataframe",
        reset_target=True,
        data_source="",
        output_format="",
    )
    object_args_worker.verbose = 2
    object_args_worker._worker_id = 3
    object_args_worker.env = _FakeEnv(tmp_path / "share")
    object_args_worker.pool_vars = None
    object_args_worker.data_out = str(tmp_path / "share" / "flight_telemetry" / "dataframe")
    object_args_worker.setup_data_directories = fake_setup_data_directories

    object_args_worker.start()

    assert isinstance(object_args_worker.args, MutableNamespace)
    assert object_args_worker.args.data_source == "file"
    assert object_args_worker.args.output_format == "parquet"
    assert object_args_worker.pool_vars["verbose"] == 2


def test_flight_telemetry_worker_helper_and_error_branches(monkeypatch, tmp_path):
    _, FlightWorker = _import_flight_modules(monkeypatch)
    import flight_telemetry_worker.flight_telemetry_worker as worker_module

    assert worker_module._haversine_distance_m({"prev_lat": None, "prev_long": 2, "lat": 3, "long": 4}) == 0.0
    assert worker_module._haversine_distance_m({"prev_lat": "bad", "prev_long": 2, "lat": 3, "long": 4}) == 0.0
    assert worker_module._haversine_distance_m({"prev_lat": 48.0, "prev_long": 2.0, "lat": 48.001, "long": 2.001}) > 0
    values = worker_module._as_contiguous_float64(pl.Series("lat", [48.0, 48.001]))
    assert values.flags.writeable is True
    kernel_df = pl.DataFrame(
        {
            "prev_lat": pl.Series("prev_lat", [None, 48.0, "bad"], strict=False),
            "prev_long": [None, 2.0, 2.0],
            "lat": [48.0, 48.001, 48.002],
            "long": [2.0, 2.001, 2.002],
        }
    )
    kernel_series, runtime, dtype_contract, checksum = worker_module._haversine_distance_series(kernel_df)
    expected = worker_module._haversine_distance_m(
        {"prev_lat": 48.0, "prev_long": 2.0, "lat": 48.001, "long": 2.001}
    )
    assert kernel_series.to_list()[0] == 0.0
    assert math.isclose(kernel_series.to_list()[1], expected, rel_tol=1e-12)
    assert kernel_series.to_list()[2] == 0.0
    assert math.isclose(checksum, expected, rel_tol=1e-12)
    assert runtime in {"python", "cython"}
    assert dtype_contract == worker_module.SPEED_DTYPE_CONTRACT

    worker = object.__new__(FlightWorker)
    worker.pool_init({"args": MutableNamespace(data_source="file")})
    with pytest.raises(FileNotFoundError):
        worker.work_pool("missing.csv")
    worker.pool_init({"args": MutableNamespace(data_source="hawk")})
    with pytest.raises(NotImplementedError, match="file-based input"):
        worker.work_pool("ignored.csv")
    worker.work_init()

    worker.args = MutableNamespace(output_format="csv")
    worker.data_out = str(tmp_path / "csv-output")
    worker._worker_id = 7
    worker.work_done(
        pl.DataFrame(
            {
                "aircraft": ["A1", "A1"],
                "date": ["2021-01-01 00:00:00", "2021-01-01 00:01:00"],
                "speed": [0.0, 10.0],
                "source_file": ["source.csv", "source.csv"],
            }
        ).with_columns(pl.col("date").str.strptime(pl.Datetime, format="%Y-%m-%d %H:%M:%S"))
    )
    assert list((tmp_path / "csv-output").glob("A1_*.csv"))
    worker.work_done(pl.DataFrame())

    stop_calls: list[bool] = []
    monkeypatch.setattr(worker_module.PolarsWorker, "stop", lambda _self: stop_calls.append(True))
    worker.verbose = 1
    worker.stop()
    assert stop_calls == [True]
    monkeypatch.setattr(worker_module.glob, "glob", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("boom")))
    worker.stop()
    assert stop_calls == [True, True]


def test_flight_telemetry_worker_rejects_unsupported_hawk_source(monkeypatch, tmp_path):
    _, FlightWorker = _import_flight_modules(monkeypatch)
    worker = object.__new__(FlightWorker)
    worker.args = MutableNamespace(
        data_source="hawk",
        data_in="hawk.cluster.local:9200",
        data_out="flight_telemetry/dataframe",
        reset_target=False,
    )
    worker.verbose = 0
    worker._worker_id = 0
    worker.env = _FakeEnv(tmp_path / "share")
    worker.pool_vars = {}

    def fake_setup_data_directories(**_kwargs):
        return SimpleNamespace(normalized_input="hawk.cluster.local:9200")

    worker.setup_data_directories = fake_setup_data_directories

    with pytest.raises(NotImplementedError, match="file-based input"):
        worker.start()


def test_flight_reduce_contract_merges_trajectory_partials(monkeypatch):
    _import_flight_modules(monkeypatch)
    from flight_telemetry.reduction import (
        REDUCE_ARTIFACT_NAME,
        REDUCER_NAME,
        build_reduce_artifact,
        partial_from_flight_frame,
    )

    first = pl.DataFrame(
        {
            "aircraft": ["A1", "A1"],
            "date": ["2021-01-01 00:00:00", "2021-01-01 00:01:00"],
            "speed": [0.0, 100.0],
            "source_file": ["01_track.csv", "01_track.csv"],
        }
    ).with_columns(pl.col("date").str.strptime(pl.Datetime, format="%Y-%m-%d %H:%M:%S"))
    second = pl.DataFrame(
        {
            "aircraft": ["B2"],
            "date": ["2021-01-01 00:02:00"],
            "speed": [50.0],
            "source_file": ["02_track.csv"],
        }
    ).with_columns(pl.col("date").str.strptime(pl.Datetime, format="%Y-%m-%d %H:%M:%S"))

    artifact = build_reduce_artifact(
        (
            partial_from_flight_frame(
                first,
                partial_id="first",
                output_files=["A1.parquet"],
                output_format="parquet",
            ),
            partial_from_flight_frame(
                second,
                partial_id="second",
                output_files=["B2.parquet"],
                output_format="parquet",
            ),
        )
    )

    assert artifact.name == REDUCE_ARTIFACT_NAME
    assert artifact.reducer == REDUCER_NAME
    assert artifact.partial_count == 2
    assert artifact.payload["flight_run_count"] == 2
    assert artifact.payload["row_count"] == 3
    assert artifact.payload["source_file_count"] == 2
    assert artifact.payload["source_files"] == ["01_track.csv", "02_track.csv"]
    assert artifact.payload["aircraft_count"] == 2
    assert artifact.payload["aircraft"] == ["A1", "B2"]
    assert artifact.payload["output_file_count"] == 2
    assert artifact.payload["output_formats"] == ["parquet"]
    assert artifact.payload["mean_speed_m"] == 50.0
    assert artifact.payload["max_speed_m"] == 100.0
    assert artifact.payload["speed_kernel_runtimes"] == []
    assert artifact.payload["speed_dtype_contracts"] == []
    assert artifact.payload["speed_kernel_checksum_m"] == 0.0
    assert artifact.payload["time_start"] == "2021-01-01T00:00:00"
    assert artifact.payload["time_end"] == "2021-01-01T00:02:00"


def test_flight_reduce_contract_validation_edges(monkeypatch):
    _import_flight_modules(monkeypatch)
    from flight_telemetry import reduction

    assert reduction._timestamp(date(2021, 1, 2)) == "2021-01-02"
    assert reduction._timestamp(None) == ""
    assert reduction._sorted_strings({"B", "", "A"}) == ["A", "B"]
    with pytest.raises(ValueError, match="non-empty trajectory"):
        reduction.partial_from_flight_frame(pl.DataFrame(), partial_id="empty")
    with pytest.raises(ValueError, match="missing columns"):
        reduction.partial_from_flight_frame(pl.DataFrame({"aircraft": ["A1"]}), partial_id="missing")

    for payload, message in [
        ({"row_count": 0, "aircraft_count": 1, "source_file_count": 1}, "no trajectory rows"),
        ({"row_count": 1, "aircraft_count": 0, "source_file_count": 1}, "no aircraft metadata"),
        ({"row_count": 1, "aircraft_count": 1, "source_file_count": 0}, "no source files"),
    ]:
        artifact = ReduceArtifact(
            name=reduction.REDUCE_ARTIFACT_NAME,
            reducer=reduction.REDUCER_NAME,
            schema_version="1",
            partial_count=1,
            partial_ids=("partial",),
            payload=payload,
            metadata={},
        )
        with pytest.raises(ValueError, match=message):
            reduction._validate_flight_artifact(artifact)


def test_flight_telemetry_worker_emits_reduce_artifact(monkeypatch, tmp_path):
    _, FlightWorker = _import_flight_modules(monkeypatch)
    from flight_telemetry.reduction import REDUCE_ARTIFACT_NAME, REDUCER_NAME, reduce_artifact_path

    monkeypatch.setenv("HOME", str(tmp_path))
    share_root = tmp_path / "share"
    source_root = share_root / "flight_telemetry" / "dataset"
    source_root.mkdir(parents=True)
    source = source_root / "01_track.csv"
    source.write_text(
        "\n".join(
            [
                "aircraft,date,lat,long",
                "A1,2021-01-01 00:00:00,48.0000,2.0000",
                "A1,2021-01-01 00:01:00,48.0005,2.0005",
                "A1,2021-01-01 00:02:00,48.0010,2.0010",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    worker = FlightWorker()
    worker.env = _FakeEnv(share_root)
    worker.args = {
        "data_in": "flight_telemetry/dataset",
        "data_out": "flight_telemetry/dataframe",
        "reset_target": True,
        "output_format": "parquet",
    }
    worker._worker_id = 0
    worker.worker_id = 0
    worker.verbose = 0
    worker.start()

    result = worker.work_pool(str(source.relative_to(tmp_path)))
    assert "source_file" in result.columns
    assert "speed_kernel_runtime" in result.columns
    assert "speed_dtype_contract" in result.columns
    assert "speed_kernel_checksum_m" in result.columns
    assert result.select("speed_dtype_contract").unique().to_series().to_list() == [
        "float64-contiguous"
    ]
    assert result.select("speed_kernel_runtime").unique().to_series().to_list()[0] in {
        "python",
        "cython",
    }
    absolute_result = worker.work_pool(str(source))
    assert absolute_result.select("source_file").unique().to_series().to_list() == ["01_track.csv"]

    worker.work_done(result)

    result_root = Path(worker.data_out)
    artifact_path = reduce_artifact_path(result_root, 0)
    artifact = ReduceArtifact.from_dict(json.loads(artifact_path.read_text(encoding="utf-8")))

    assert (result_root / "A1.parquet").is_file()
    assert artifact.name == REDUCE_ARTIFACT_NAME
    assert artifact.reducer == REDUCER_NAME
    assert artifact.partial_count == 1
    assert artifact.partial_ids == ("flight_telemetry_worker_0",)
    assert artifact.payload["flight_run_count"] == 1
    assert artifact.payload["row_count"] == 3
    assert artifact.payload["source_files"] == ["01_track.csv"]
    assert artifact.payload["aircraft"] == ["A1"]
    assert artifact.payload["output_files"] == ["A1.parquet"]
    assert artifact.payload["output_formats"] == ["parquet"]
    assert artifact.payload["mean_speed_m"] > 0.0
    assert artifact.payload["max_speed_m"] > 0.0
    assert artifact.payload["speed_kernel_runtimes"][0] in {"python", "cython"}
    assert artifact.payload["speed_dtype_contracts"] == ["float64-contiguous"]
    assert artifact.payload["speed_kernel_checksum_m"] > 0.0


def test_flight_args_codec_hooks_round_trip(monkeypatch, tmp_path):
    # AGILAB ORCHESTRATE args-codec contract: the manager package exports
    # load_args_payload / persist_args_payload so the generic page needs no
    # app-specific imports.
    repo_root = Path(__file__).resolve().parents[1]
    app_src = repo_root / "src" / "agilab" / "apps" / "builtin" / "flight_telemetry_project" / "src"
    monkeypatch.syspath_prepend(str(app_src))
    existing = sys.modules.get("flight_telemetry")
    if existing is not None and not hasattr(existing, "__path__"):
        monkeypatch.delitem(sys.modules, "flight_telemetry", raising=False)
    import flight_telemetry

    settings_file = tmp_path / "app_settings.toml"
    payload = flight_telemetry.persist_args_payload(
        {"data_source": "file"}, settings_file
    )
    assert payload["files"] == "*"
    assert settings_file.is_file()

    loaded = flight_telemetry.load_args_payload(settings_file)
    assert loaded == payload

    with pytest.raises(ValueError):
        flight_telemetry.persist_args_payload(
            {"data_source": "not-a-source"}, settings_file
        )


def test_orchestrate_page_has_no_app_specific_imports():
    repo_root = Path(__file__).resolve().parents[1]
    page_source = (repo_root / "src" / "agilab" / "pages" / "2_ORCHESTRATE.py").read_text(
        encoding="utf-8"
    )
    assert "flight_telemetry" not in page_source
    assert "load_args_payload" in page_source
    assert "persist_args_payload" in page_source
