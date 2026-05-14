from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import types
from argparse import Namespace
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
while str(SRC_ROOT) in sys.path:
    sys.path.remove(str(SRC_ROOT))
sys.path.insert(0, str(SRC_ROOT))
loaded_agilab = sys.modules.get("agilab")
loaded_path = str(getattr(loaded_agilab, "__file__", ""))
if loaded_agilab is not None and not loaded_path.startswith(str(SRC_ROOT)):
    sys.modules.pop("agilab", None)

from agilab import cluster_flight_validation as cfv


def _args(**overrides):
    values = {
        "app": "flight_telemetry_project",
        "apps_path": "src/agilab/apps/builtin",
        "scheduler": "192.168.3.103",
        "workers": "jpm@192.168.3.35:2",
        "remote_user": "",
        "local_share": "localshare",
        "cluster_share": "",
        "remote_cluster_share": "clustershare",
        "dataset_rel": "flight_cluster_validation/dataset/csv",
        "output_rel": "flight_cluster_validation/dataframe_cluster_validation",
        "aircraft": "60,61",
        "rows_per_aircraft": 3,
        "modes_enabled": 15,
    }
    values.update(overrides)
    return Namespace(**values)


def test_worker_spec_ssh_target_formats_user_host():
    assert cfv.WorkerSpec(host="192.168.3.35", user="jpm").ssh_target == "jpm@192.168.3.35"
    assert cfv.WorkerSpec(host="192.168.3.35").ssh_target == "192.168.3.35"


def test_parse_worker_specs_accepts_user_and_counts():
    specs = cfv.parse_worker_specs("jpm@192.168.3.35:2,192.168.3.36")

    assert specs == (
        cfv.WorkerSpec(host="192.168.3.35", count=2, user="jpm"),
        cfv.WorkerSpec(host="192.168.3.36", count=1, user=None),
    )


def test_parse_worker_specs_rejects_empty_or_missing_host():
    with pytest.raises(ValueError, match="did not contain"):
        cfv.parse_worker_specs(" , ")

    with pytest.raises(ValueError, match="host is missing"):
        cfv.parse_worker_specs("jpm@")

    with pytest.raises(ValueError, match="count must be positive"):
        cfv.parse_worker_specs("192.168.3.35:0")


def test_parse_args_requires_cluster_and_positive_rows():
    with pytest.raises(SystemExit):
        cfv._parse_args(["--scheduler", "127.0.0.1", "--workers", "127.0.0.1"])

    args = cfv._parse_args(["--discover-lan"])
    assert args.discover_lan is True
    assert args.scheduler == ""
    assert args.workers == ""

    with pytest.raises(SystemExit):
        cfv._parse_args(["--cluster", "--scheduler", "127.0.0.1", "--workers", "127.0.0.1", "--json"])

    with pytest.raises(SystemExit):
        cfv._parse_args(["--discover-lan", "--share-check-only"])

    with pytest.raises(SystemExit):
        cfv._parse_args(["--discover-lan", "--cluster"])

    with pytest.raises(SystemExit):
        cfv._parse_args(
            [
                "--cluster",
                "--scheduler",
                "127.0.0.1",
                "--workers",
                "127.0.0.1",
                "--rows-per-aircraft",
                "0",
            ]
        )

    with pytest.raises(SystemExit):
        cfv._parse_args(
            [
                "--cluster",
                "--scheduler",
                "127.0.0.1",
                "--workers",
                "127.0.0.1",
                "--share-check-only",
                "--dry-run",
            ]
        )

    with pytest.raises(SystemExit):
        cfv._parse_args(
            [
                "--cluster",
                "--scheduler",
                "127.0.0.1",
                "--workers",
                "127.0.0.1",
                "--setup-share",
                "sshfs",
            ]
        )

    with pytest.raises(SystemExit):
        cfv._parse_args(
            [
                "--cluster",
                "--scheduler",
                "127.0.0.1",
                "--workers",
                "127.0.0.1",
                "--apply",
            ]
        )

    with pytest.raises(SystemExit):
        cfv._parse_args(
            [
                "--cluster",
                "--scheduler",
                "127.0.0.1",
                "--workers",
                "127.0.0.1",
                "--setup-share",
                "sshfs",
                "--apply",
                "--share-check-only",
            ]
        )


def test_build_validation_plan_makes_flight_paths_home_relative(tmp_path: Path):
    plan = cfv.build_validation_plan(
        _args(),
        home=tmp_path,
        environ={"USER": "agi"},
    )

    assert plan.remote_user == "jpm"
    assert plan.workers == {"192.168.3.35": 2}
    assert plan.local_dataset_dir == tmp_path / "localshare/flight_cluster_validation/dataset/csv"
    assert plan.dataset_rel_to_home == Path("localshare/flight_cluster_validation/dataset/csv")
    assert plan.local_cluster_share_setting == "clustershare/agi"
    assert plan.remote_cluster_share_setting == "clustershare"


def test_build_validation_plan_reads_env_files_and_serializes_paths(tmp_path: Path):
    env_dir = tmp_path / ".agilab"
    env_dir.mkdir()
    (env_dir / ".env").write_text(
        "# ignored\n\nNO_EQUALS\nAGI_LOCAL_SHARE='share-in-env'\n"
        "AGI_CLUSTER_SHARE=\"cluster-in-env\"\n",
        encoding="utf-8",
    )

    plan = cfv.build_validation_plan(
        _args(local_share="", cluster_share="", workers="192.168.3.35", remote_user="ops"),
        home=tmp_path,
        environ={"USER": "agi"},
    )

    assert plan.remote_user == "ops"
    assert plan.local_share_setting == "share-in-env"
    assert plan.local_cluster_share_setting == "cluster-in-env"
    assert plan.to_dict()["local_dataset_dir"].endswith("share-in-env/flight_cluster_validation/dataset/csv")


def test_build_validation_plan_rejects_absolute_relative_arguments(tmp_path: Path):
    with pytest.raises(ValueError, match="--dataset-rel must be relative"):
        cfv.build_validation_plan(
            _args(dataset_rel=str(tmp_path / "dataset")),
            home=tmp_path,
            environ={"USER": "agi"},
        )

    with pytest.raises(ValueError, match="--output-rel must be relative"):
        cfv.build_validation_plan(
            _args(output_rel=str(tmp_path / "out")),
            home=tmp_path,
            environ={"USER": "agi"},
        )


def test_build_validation_plan_rejects_invalid_aircraft(tmp_path: Path):
    with pytest.raises(ValueError, match="two-digit"):
        cfv.build_validation_plan(
            _args(aircraft="100"),
            home=tmp_path,
            environ={"USER": "agi"},
        )

    with pytest.raises(ValueError, match="did not contain"):
        cfv.build_validation_plan(
            _args(aircraft=","),
            home=tmp_path,
            environ={"USER": "agi"},
        )


def test_resolve_remote_user_rejects_mixed_worker_users():
    with pytest.raises(ValueError, match="one SSH user"):
        cfv.resolve_remote_user(
            (
                cfv.WorkerSpec(host="192.168.3.35", user="jpm"),
                cfv.WorkerSpec(host="192.168.3.36", user="agi"),
            ),
            remote_user="",
            environ={"USER": "local"},
        )


def test_build_workers_map_keeps_only_explicit_workers():
    workers = cfv.build_workers_map(
        "127.0.0.1",
        [cfv.WorkerSpec(host="127.0.0.1"), cfv.WorkerSpec(host="192.168.3.35")],
    )

    assert workers == {"127.0.0.1": 1, "192.168.3.35": 1}


def test_default_share_user_sanitizes_machine_user():
    assert cfv._default_share_user({"USER": "Jean Pierre!"}) == "Jean_Pierre"
    assert cfv._default_share_user({"USER": "!!!"}) == "user"


def test_write_synthetic_flight_dataset_uses_flight_worker_schema(tmp_path: Path):
    (tmp_path / "stale.csv").write_text("old\n", encoding="utf-8")
    stale_dir = tmp_path / "directory.csv"
    stale_dir.mkdir()
    files = cfv.write_synthetic_flight_dataset(
        tmp_path,
        aircraft=(60, 61),
        rows_per_aircraft=2,
    )

    assert not (tmp_path / "stale.csv").exists()
    assert stale_dir.is_dir()
    assert [path.name for path in files] == [
        "60_cluster_validation.csv",
        "61_cluster_validation.csv",
    ]
    assert files[0].read_text(encoding="utf-8").splitlines() == [
        "aircraft,date,lat,long",
        "60,2020-01-01 00:00:00,48.060000,2.060000",
        "60,2020-01-01 00:01:00,48.060100,2.060100",
    ]


def test_remote_worker_specs_filters_local_scheduler(tmp_path: Path):
    plan = cfv.build_validation_plan(
        _args(scheduler="127.0.0.1", workers="127.0.0.1,jpm@192.168.3.35"),
        home=tmp_path,
        environ={"USER": "agi"},
    )

    assert cfv.remote_worker_specs(plan) == (
        cfv.WorkerSpec(host="192.168.3.35", count=1, user="jpm"),
    )


def test_sync_remote_inputs_builds_ssh_and_scp_commands(tmp_path: Path, monkeypatch):
    plan = cfv.build_validation_plan(
        _args(workers="jpm@192.168.3.35", remote_cluster_share="remote share"),
        home=tmp_path,
        environ={"USER": "agi"},
    )
    input_file = tmp_path / "input.csv"
    input_file.write_text("aircraft,date,lat,long\n", encoding="utf-8")
    commands: list[tuple[list[str], int | None]] = []

    def fake_run(argv, *, timeout=None):
        commands.append((list(argv), timeout))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(cfv, "_run_command", fake_run)

    cfv.sync_remote_inputs(plan, [input_file], timeout=12)

    assert commands[0][0][:4] == ["ssh", "-o", "BatchMode=yes", "jpm@192.168.3.35"]
    assert "rm -f" in commands[0][0][-1]
    assert commands[1][0] == [
        "scp",
        "-q",
        "-o",
        "BatchMode=yes",
        str(input_file),
        "jpm@192.168.3.35:localshare/flight_cluster_validation/dataset/csv/",
    ]
    assert "mkdir -p 'remote share'" in commands[2][0][-1]
    assert all(timeout == 12 for _, timeout in commands)


def test_run_command_captures_stdout():
    completed = cfv._run_command([sys.executable, "-c", "print('ok')"], timeout=5)

    assert completed.stdout.strip() == "ok"


def test_build_validation_plan_rejects_dataset_outside_home(tmp_path: Path):
    outside = tmp_path / "outside"
    home = tmp_path / "home"
    home.mkdir()

    with pytest.raises(ValueError, match="must resolve under HOME"):
        cfv.build_validation_plan(
            _args(local_share=str(outside)),
            home=home,
            environ={"USER": "agi"},
        )


def test_local_output_candidates_include_configured_cluster_share(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("USER", "agi")
    plan = cfv.build_validation_plan(
        _args(cluster_share="clustershare/agi"),
        home=tmp_path,
        environ={"USER": "agi"},
    )

    candidates = cfv.local_output_candidates(plan, home=tmp_path)

    assert candidates == (
        tmp_path / "clustershare/agi/flight_cluster_validation/dataframe_cluster_validation",
        tmp_path / "clustershare/flight_cluster_validation/dataframe_cluster_validation",
    )


def test_collect_local_outputs_summarizes_reduce_artifacts(tmp_path: Path):
    plan = cfv.build_validation_plan(
        _args(cluster_share="shared"),
        home=tmp_path,
        environ={"USER": "agi"},
    )
    output_dir = tmp_path / "shared/flight_cluster_validation/dataframe_cluster_validation"
    output_dir.mkdir(parents=True)
    (output_dir / "61.parquet").write_text("parquet", encoding="utf-8")
    (output_dir / "60.parquet").write_text("parquet", encoding="utf-8")
    (output_dir / "reduce_summary_worker_0.json").write_text(
        json.dumps({"payload": {"row_count": 4, "aircraft": [60, "61"]}}),
        encoding="utf-8",
    )
    (output_dir / "reduce_summary_worker_1.json").write_text("not json", encoding="utf-8")
    (output_dir / "reduce_summary_worker_2.json").write_text(
        json.dumps({"payload": {"row_count": "bad", "aircraft": [62]}}),
        encoding="utf-8",
    )

    summaries = cfv.collect_local_outputs(plan, home=tmp_path)

    assert summaries[0].has_result
    assert summaries[0].parquet_files == ("60.parquet", "61.parquet")
    assert summaries[0].reduce_artifacts == (
        "reduce_summary_worker_0.json",
        "reduce_summary_worker_1.json",
        "reduce_summary_worker_2.json",
    )
    assert summaries[0].row_count == 4
    assert summaries[0].aircraft == ("60", "61", "62")


def test_cluster_share_sentinel_rejects_local_share_alias(tmp_path: Path):
    plan = cfv.build_validation_plan(
        _args(local_share="shared", cluster_share="shared", workers="127.0.0.1"),
        home=tmp_path,
        environ={"USER": "agi"},
    )

    with pytest.raises(ValueError, match="must be distinct"):
        cfv.write_cluster_share_sentinel(plan, home=tmp_path, token="fixed")


def test_validate_shared_cluster_share_probes_remote_sentinel(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    plan = cfv.build_validation_plan(
        _args(cluster_share="shared", workers="jpm@192.168.3.35"),
        home=tmp_path,
        environ={"USER": "agi"},
    )
    calls: list[list[str]] = []

    def fake_run(argv, *, timeout=None):
        calls.append(list(argv))
        script = argv[-1]
        assert ".agilab_cluster_doctor" in script
        assert "cluster share sentinel is not visible" in script
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="/Users/jpm/clustershare/.agilab_cluster_doctor/fixed.json\n",
            stderr="",
        )

    monkeypatch.setattr(cfv, "_run_command", fake_run)

    probes = cfv.validate_shared_cluster_share(plan, timeout=11)

    sentinel_files = sorted((tmp_path / "shared" / ".agilab_cluster_doctor").glob("*.json"))
    assert len(sentinel_files) == 1
    assert probes[0].location == "local"
    assert probes[0].path == str(sentinel_files[0])
    assert probes[1] == cfv.ShareProbeSummary(
        location="jpm@192.168.3.35",
        path="/Users/jpm/clustershare/.agilab_cluster_doctor/fixed.json",
    )
    assert calls[0][:4] == ["ssh", "-o", "BatchMode=yes", "jpm@192.168.3.35"]


def test_share_setup_script_lines_print_sshfs_commands(tmp_path: Path):
    plan = cfv.build_validation_plan(
        _args(
            scheduler="192.168.3.103",
            workers="jpm@192.168.3.35",
            cluster_share="/Users/agi/clustershare/agilab-two-node",
            remote_cluster_share="/Users/jpm/clustershare/agilab-two-node",
        ),
        home=tmp_path,
        environ={"USER": "agi"},
    )

    script = "\n".join(cfv.share_setup_script_lines(plan, "sshfs", local_user="agi"))

    assert "sshfs" in script
    assert "agi@192.168.3.103:/Users/agi/clustershare/agilab-two-node" in script
    assert "jpm@192.168.3.35" in script
    assert "-o reconnect" in script
    assert "-o ServerAliveInterval=15" in script
    assert "-o StrictHostKeyChecking=yes" in script
    assert "MOUNT_LINE=$(mount | grep -F" in script
    assert "stale, unexpected, or unwritable SSHFS mount" in script
    assert "sudo apt-get install -y sshfs" in script
    assert "--share-check-only" in script
    assert "--remote-cluster-share /Users/jpm/clustershare/agilab-two-node" in script


def test_apply_share_setup_runs_idempotent_remote_commands(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    plan = cfv.build_validation_plan(
        _args(
            scheduler="192.168.3.103",
            workers="jpm@192.168.3.35",
            cluster_share="clustershare/agilab-two-node",
            remote_cluster_share="/Users/jpm/clustershare/agilab-two-node",
        ),
        home=tmp_path,
        environ={"USER": "agi"},
    )
    commands: list[list[str]] = []
    responses = iter(
        [
            subprocess.CompletedProcess([], 0, stdout="/usr/local/bin/sshfs\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="/Users/jpm/.agilab/.env\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="mounted\n", stderr=""),
        ]
    )

    def fake_run(argv, *, timeout=None):
        commands.append(list(argv))
        assert timeout == 17
        return next(responses)

    monkeypatch.setattr(cfv, "_run_command", fake_run)

    summaries = cfv.apply_share_setup(plan, "sshfs", timeout=17, local_user="agi")

    assert (tmp_path / "clustershare/agilab-two-node").is_dir()
    assert [summary.action for summary in summaries] == [
        "mkdir",
        "check-sshfs",
        "write-env",
        "mkdir",
        "mount",
    ]
    assert summaries[2].path == "/Users/jpm/.agilab/.env"
    assert commands[0][:4] == ["ssh", "-o", "BatchMode=yes", "jpm@192.168.3.35"]
    assert "command -v sshfs" in commands[0][-1]
    assert "AGI_CLUSTER_SHARE" in commands[1][-1]
    assert "mkdir -p \"$REMOTE_CLUSTER_SHARE\"" in commands[2][-1]
    assert "SCHEDULER_CLUSTER_SHARE=agi@192.168.3.103:" in commands[3][-1]
    assert "sshfs \"$SCHEDULER_CLUSTER_SHARE\"" in commands[3][-1]
    assert "-o reconnect" in commands[3][-1]
    assert "-o ServerAliveInterval=15" in commands[3][-1]
    assert "-o StrictHostKeyChecking=yes" in commands[3][-1]
    assert "fusermount3 -u" in commands[3][-1]


def test_validation_success_requires_local_visibility_for_remote_runs():
    local_ok = cfv.OutputSummary(
        location="local",
        path="/shared/out",
        parquet_files=("60.parquet",),
        reduce_artifacts=(),
        row_count=0,
        aircraft=(),
    )
    remote_ok = cfv.OutputSummary(
        location="jpm@192.168.3.35",
        path="/Users/jpm/shared/out",
        parquet_files=("60.parquet",),
        reduce_artifacts=(),
        row_count=0,
        aircraft=(),
    )
    missing = cfv.OutputSummary(
        location="local",
        path="/shared/out",
        parquet_files=(),
        reduce_artifacts=(),
        row_count=0,
        aircraft=(),
    )
    remote_targets = (cfv.WorkerSpec(host="192.168.3.35", user="jpm"),)

    assert cfv.validation_success((local_ok,), ()) is True
    assert cfv.validation_success((remote_ok,), remote_targets) is False
    assert cfv.validation_success((local_ok,), remote_targets) is False
    assert cfv.validation_success((missing, remote_ok), remote_targets) is False
    assert cfv.validation_success((local_ok, remote_ok), remote_targets) is True


def test_remote_output_root_settings_deduplicate_default_cluster_share(tmp_path: Path):
    plan = cfv.build_validation_plan(
        _args(remote_cluster_share="clustershare"),
        home=tmp_path,
        environ={"USER": "agi"},
    )

    assert cfv.remote_output_root_settings(plan) == (
        "clustershare",
        "clustershare/jpm",
    )
    assert cfv.remote_output_root_settings(replace(plan, remote_user="")) == ("clustershare",)


def test_reset_agi_state_ignores_read_only_targets():
    class ReadOnly:
        def __setattr__(self, name, value):
            raise RuntimeError("read-only")

    cfv._reset_agi_state(ReadOnly())


def test_collect_remote_outputs_parses_payload_and_ignores_bad_json(tmp_path: Path, monkeypatch):
    plan = cfv.build_validation_plan(
        _args(workers="jpm@192.168.3.35"),
        home=tmp_path,
        environ={"USER": "agi"},
    )
    responses = iter(
        [
            json.dumps(
                [
                    {
                        "path": "/Users/jpm/clustershare/out",
                        "parquet_files": ["60.parquet"],
                        "reduce_artifacts": ["reduce_summary_worker_0.json"],
                        "row_count": 3,
                        "aircraft": ["60"],
                    }
                ]
            ),
            "not json",
        ]
    )
    calls: list[list[str]] = []

    def fake_run(argv, *, timeout=None):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout=next(responses), stderr="")

    monkeypatch.setattr(cfv, "_run_command", fake_run)

    summaries = cfv.collect_remote_outputs(plan, timeout=9)
    bad_json = cfv.collect_remote_outputs(plan, timeout=9)

    assert calls[0][:4] == ["ssh", "-o", "BatchMode=yes", "jpm@192.168.3.35"]
    assert summaries == (
        cfv.OutputSummary(
            location="jpm@192.168.3.35",
            path="/Users/jpm/clustershare/out",
            parquet_files=("60.parquet",),
            reduce_artifacts=("reduce_summary_worker_0.json",),
            row_count=3,
            aircraft=("60",),
        ),
    )
    assert bad_json == ()


def test_clean_validation_outputs_cleans_local_and_remote(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    plan = cfv.build_validation_plan(
        _args(cluster_share="shared", workers="jpm@192.168.3.35"),
        home=tmp_path,
        environ={"USER": "agi"},
    )
    output_dir = tmp_path / "shared/flight_cluster_validation/dataframe_cluster_validation"
    output_dir.mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_run(argv, *, timeout=None):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(cfv, "_run_command", fake_run)

    cfv.clean_validation_outputs(plan, timeout=8)

    assert not output_dir.exists()
    assert calls
    assert "shutil.rmtree" in calls[0][-1]


def test_clean_local_outputs_removes_dedicated_validation_dirs(tmp_path: Path):
    plan = cfv.build_validation_plan(
        _args(cluster_share="shared"),
        home=tmp_path,
        environ={"USER": "agi"},
    )
    output_dir = tmp_path / "shared/flight_cluster_validation/dataframe_cluster_validation"
    output_dir.mkdir(parents=True)
    (output_dir / "stale.parquet").write_text("old", encoding="utf-8")

    cfv.clean_local_outputs(plan, home=tmp_path)

    assert not output_dir.exists()


def test_configure_process_env_sets_cluster_variables(tmp_path: Path, monkeypatch):
    plan = cfv.build_validation_plan(
        _args(cluster_share="shared"),
        home=tmp_path,
        environ={"USER": "agi"},
    )
    monkeypatch.delenv("AGI_CLUSTER_ENABLED", raising=False)

    cfv._configure_process_env(plan)

    assert cfv.os.environ["AGI_CLUSTER_ENABLED"] == "1"
    assert cfv.os.environ["AGI_LOCAL_SHARE"] == "localshare"
    assert cfv.os.environ["AGI_CLUSTER_SHARE"] == "shared"


def test_main_dry_run_writes_summary_and_prints_plan(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    summary_path = tmp_path / "summary.json"

    rc = cfv.main(
        [
            "--cluster",
            "--scheduler",
            "127.0.0.1",
            "--workers",
            "127.0.0.1",
            "--aircraft",
            "60",
            "--summary-json",
            str(summary_path),
            "--dry-run",
        ]
    )

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["success"] is True
    assert payload["dry_run"] is True
    assert payload["plan"]["workers"] == {"127.0.0.1": 1}
    assert "AGILAB Flight cluster validation plan" in capsys.readouterr().out


def test_main_share_check_only_skips_dataset_and_writes_summary(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    monkeypatch.setenv("HOME", str(tmp_path))
    summary_path = tmp_path / "share.json"

    def fail_dataset(*args, **kwargs):
        raise AssertionError("share check should not synthesize Flight data")

    monkeypatch.setattr(cfv, "write_synthetic_flight_dataset", fail_dataset)
    monkeypatch.setattr(
        cfv,
        "validate_shared_cluster_share",
        lambda plan, *, timeout: (
            cfv.ShareProbeSummary(location="local", path="/shared/sentinel.json"),
            cfv.ShareProbeSummary(location="jpm@192.168.3.35", path="/remote/sentinel.json"),
        ),
    )

    rc = cfv.main(
        [
            "--cluster",
            "--scheduler",
            "192.168.3.103",
            "--workers",
            "jpm@192.168.3.35",
            "--cluster-share",
            "shared",
            "--summary-json",
            str(summary_path),
            "--share-check-only",
        ]
    )

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    output = capsys.readouterr().out
    assert rc == 0
    assert payload["share_check_only"] is True
    assert len(payload["shared_cluster_share"]) == 2
    assert "AGILAB cluster-share preflight" in output
    assert "ok: jpm@192.168.3.35" in output


def test_main_print_share_setup_skips_dataset(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))

    def fail_dataset(*args, **kwargs):
        raise AssertionError("share setup printing should not synthesize Flight data")

    monkeypatch.setattr(cfv, "write_synthetic_flight_dataset", fail_dataset)

    rc = cfv.main(
        [
            "--cluster",
            "--scheduler",
            "192.168.3.103",
            "--workers",
            "jpm@192.168.3.35",
            "--cluster-share",
            "/Users/agi/clustershare/agilab-two-node",
            "--remote-cluster-share",
            "/Users/jpm/clustershare/agilab-two-node",
            "--print-share-setup",
            "sshfs",
        ]
    )

    output = capsys.readouterr().out
    assert rc == 0
    assert "AGILAB cluster-share setup using SSHFS" in output
    assert "sshfs" in output
    assert "--share-check-only" in output


def test_main_setup_share_apply_runs_setup_and_share_check(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    monkeypatch.setenv("HOME", str(tmp_path))
    summary_path = tmp_path / "setup.json"

    def fail_dataset(*args, **kwargs):
        raise AssertionError("share setup should not synthesize Flight data")

    monkeypatch.setattr(cfv, "write_synthetic_flight_dataset", fail_dataset)
    monkeypatch.setattr(
        cfv,
        "apply_share_setup",
        lambda plan, backend, *, timeout: (
            cfv.ShareSetupSummary(location="local", action="mkdir", path="/shared"),
            cfv.ShareSetupSummary(location="jpm@192.168.3.35", action="mount", path="mounted"),
        ),
    )
    monkeypatch.setattr(
        cfv,
        "validate_shared_cluster_share",
        lambda plan, *, timeout: (
            cfv.ShareProbeSummary(location="local", path="/shared/sentinel.json"),
            cfv.ShareProbeSummary(location="jpm@192.168.3.35", path="/remote/sentinel.json"),
        ),
    )

    rc = cfv.main(
        [
            "--cluster",
            "--scheduler",
            "192.168.3.103",
            "--workers",
            "jpm@192.168.3.35",
            "--cluster-share",
            "shared",
            "--setup-share",
            "sshfs",
            "--apply",
            "--summary-json",
            str(summary_path),
        ]
    )

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    output = capsys.readouterr().out
    assert rc == 0
    assert payload["setup_applied"] is True
    assert payload["setup_backend"] == "sshfs"
    assert payload["share_setup"][1]["action"] == "mount"
    assert len(payload["shared_cluster_share"]) == 2
    assert "AGILAB cluster-share setup" in output
    assert "AGILAB cluster-share preflight" in output


def test_main_returns_failure_on_validation_error(capsys):
    rc = cfv.main(
        [
            "--cluster",
            "--scheduler",
            "127.0.0.1",
            "--workers",
            "127.0.0.1",
            "--output-rel",
            "/tmp/out",
        ]
    )

    assert rc == 1
    assert "cluster doctor failed" in capsys.readouterr().err


def test_main_prints_non_dry_run_output_summary(monkeypatch, capsys, tmp_path: Path):
    async def fake_run_cluster_validation(args):
        return {
            "success": False,
            "outputs": [
                {
                    "location": "local",
                    "path": str(tmp_path / "missing"),
                    "parquet_files": [],
                    "reduce_artifacts": [],
                    "row_count": 0,
                },
                {
                    "location": "jpm@192.168.3.35",
                    "path": "/Users/jpm/clustershare/out",
                    "parquet_files": ["60.parquet"],
                    "reduce_artifacts": ["reduce_summary_worker_0.json"],
                    "row_count": 3,
                },
            ],
        }

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(cfv, "run_cluster_validation", fake_run_cluster_validation)

    rc = cfv.main(
        [
            "--cluster",
            "--scheduler",
            "127.0.0.1",
            "--workers",
            "127.0.0.1",
            "--aircraft",
            "60",
        ]
    )

    output = capsys.readouterr().out
    assert rc == 1
    assert "missing: local" in output
    assert "ok: jpm@192.168.3.35" in output


def test_run_cluster_validation_with_mocked_agi_success(tmp_path: Path, monkeypatch):
    install_calls: list[dict[str, object]] = []
    run_requests: list[object] = []

    class FakeAgiEnv:
        reset_called = False

        @classmethod
        def reset(cls):
            cls.reset_called = True

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.user = None
            self.password = "set later"

    class FakeRunRequest:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            run_requests.append(self)

    class FakeAGI:
        DASK_MODE = 4
        _TIMEOUT = 0

        @staticmethod
        async def install(**kwargs):
            install_calls.append(kwargs)

        @staticmethod
        async def run(env, *, request):
            return "run-ok"

    agi_distributor = types.ModuleType("agi_cluster.agi_distributor")
    agi_distributor.AGI = FakeAGI
    agi_distributor.RunRequest = FakeRunRequest
    agi_cluster = types.ModuleType("agi_cluster")
    agi_cluster.agi_distributor = agi_distributor
    agi_env = types.ModuleType("agi_env")
    agi_env.AgiEnv = FakeAgiEnv
    monkeypatch.setitem(sys.modules, "agi_cluster", agi_cluster)
    monkeypatch.setitem(sys.modules, "agi_cluster.agi_distributor", agi_distributor)
    monkeypatch.setitem(sys.modules, "agi_env", agi_env)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(cfv, "clean_validation_outputs", lambda plan, *, timeout: None)
    monkeypatch.setattr(cfv, "sync_remote_inputs", lambda plan, files, *, timeout: None)
    monkeypatch.setattr(
        cfv,
        "collect_local_outputs",
        lambda plan: (
            cfv.OutputSummary(
                location="local",
                path=str(tmp_path / "out"),
                parquet_files=("60.parquet",),
                reduce_artifacts=(),
                row_count=0,
                aircraft=(),
            ),
        ),
    )
    monkeypatch.setattr(cfv, "collect_remote_outputs", lambda plan, *, timeout: ())

    payload = asyncio.run(
        cfv.run_cluster_validation(
            _args(
                scheduler="127.0.0.1",
                workers="127.0.0.1",
                aircraft="60",
                timeout=5,
                verbose=2,
                ssh_key=str(tmp_path / "id_ed25519"),
            )
        )
    )

    assert payload["success"] is True
    assert payload["run_result"] == "run-ok"
    assert payload["outputs"][0]["parquet_files"] == ("60.parquet",)
    assert FakeAgiEnv.reset_called is True
    assert FakeAGI._TIMEOUT == 5
    assert install_calls[0]["workers"] == {"127.0.0.1": 1}
    assert run_requests[0].kwargs["mode"] == 4
    assert run_requests[0].kwargs["data_out"] == "flight_cluster_validation/dataframe_cluster_validation"
