from __future__ import annotations

import hashlib
import json
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agilab.pipeline import pipeline_run_controls as pipeline_automation  # noqa: E402
from agilab.pipeline import pipeline_stages  # noqa: E402


def test_automation_manifest_schema_contract_is_versioned() -> None:
    assert (
        pipeline_automation.PIPELINE_AUTOMATION_SCHEMA
        == "agilab.pipeline.automation.v2"
    )
    assert pipeline_automation.PIPELINE_AUTOMATION_COMPATIBLE_SCHEMAS == [
        "agilab.pipeline.automation.v1"
    ]
    assert (
        pipeline_automation.PIPELINE_AUTOMATION_PRODUCER
        == "agilab.pipeline.run_all_stages"
    )
    assert (
        pipeline_automation.PIPELINE_SEQUENCE_METADATA_SCHEMA
        == "agilab.pipeline.sequence.v2"
    )
    assert pipeline_automation.PIPELINE_SEQUENCE_METADATA_COMPATIBLE_SCHEMAS == [
        "agilab.pipeline.sequence.v1"
    ]


def test_pipeline_sequence_metadata_records_dependency_waves(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline_automation,
        "_pipeline_automation_producer_version",
        lambda: "9.9.9",
    )
    env = SimpleNamespace(app="demo_app", target="demo_target")

    payload = pipeline_automation._pipeline_sequence_metadata(
        env=env,
        lab_dir=tmp_path,
        stages_file=tmp_path / "lab_stages.toml",
        sequence=[0, 1, 2],
        profile="fast",
        run_id="run-123",
        max_workers=3,
        waves=[[0, 2], [1]],
        stage_ids={0: "flight", 1: "link", 2: "sat"},
        stage_deps={0: [], 1: ["flight", "sat"], 2: []},
    )

    assert payload["schema"] == "agilab.pipeline.sequence.v2"
    assert payload["compatible_schemas"] == ["agilab.pipeline.sequence.v1"]
    assert payload["producer"] == "agilab.pipeline.run_all_stages"
    assert payload["producer_version"] == "9.9.9"
    assert payload["local_only"] is True
    assert payload["app"] == "demo_app"
    assert payload["target"] == "demo_target"
    assert payload["profile"] == "fast"
    assert payload["run_id"] == "run-123"
    assert payload["max_workers"] == 3
    assert payload["sequence"] == [1, 2, 3]
    assert payload["waves"] == [[1, 3], [2]]
    assert payload["stage_ids"] == {"1": "flight", "2": "link", "3": "sat"}
    assert payload["stage_deps"] == {
        "flight": [],
        "link": ["flight", "sat"],
        "sat": [],
    }


def test_mlflow_parent_payload_records_waved_sequence_artifact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline_automation,
        "_pipeline_automation_producer_version",
        lambda: "9.9.9",
    )
    monkeypatch.setattr(
        pipeline_automation,
        "_optional_mlflow_tracking_uri",
        lambda env: "file:///tmp/mlruns",
    )
    env = SimpleNamespace(app="demo_app", target="demo_target")

    _run_name, _tags, _params, text_artifacts = pipeline_automation._mlflow_parent_payload(
        env,
        tmp_path,
        tmp_path / "lab_stages.toml",
        [0, 1, 2],
        profile="fast",
        run_id="run-123",
        max_workers=3,
        waves=[[0, 2], [1]],
        stage_ids={0: "flight", 1: "link", 2: "sat"},
        stage_deps={0: [], 1: ["flight", "sat"], 2: []},
    )

    payload = json.loads(text_artifacts["pipeline_metadata/sequence.json"])

    assert payload["schema"] == "agilab.pipeline.sequence.v2"
    assert payload["producer_version"] == "9.9.9"
    assert payload["profile"] == "fast"
    assert payload["run_id"] == "run-123"
    assert payload["max_workers"] == 3
    assert payload["sequence"] == [1, 2, 3]
    assert payload["waves"] == [[1, 3], [2]]
    assert payload["stage_ids"] == {"1": "flight", "2": "link", "3": "sat"}
    assert payload["stage_deps"] == {
        "flight": [],
        "link": ["flight", "sat"],
        "sat": [],
    }


def test_pipeline_automation_metadata_records_identity_and_waves(monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline_automation,
        "_pipeline_automation_producer_version",
        lambda: "9.9.9",
    )
    env = SimpleNamespace(app="demo_app", target="demo_target")

    payload = pipeline_automation._pipeline_automation_metadata(
        env=env,
        workflow_source="demo/lab_stages.toml",
        profile="fast",
        run_id="run-123",
        sequence=[0, 1, 2],
        max_workers=3,
        waves=[[0, 2], [1]],
        stage_ids={0: "flight", 1: "link", 2: "sat"},
        stage_deps={0: [], 1: ["flight", "sat"], 2: []},
    )

    assert payload["schema"] == "agilab.pipeline.automation.v2"
    assert payload["compatible_schemas"] == ["agilab.pipeline.automation.v1"]
    assert payload["producer"] == "agilab.pipeline.run_all_stages"
    assert payload["producer_version"] == "9.9.9"
    assert payload["local_only"] is True
    assert payload["workflow_source"] == "demo/lab_stages.toml"
    assert payload["app"] == "demo_app"
    assert payload["target"] == "demo_target"
    assert payload["profile"] == "fast"
    assert payload["run_id"] == "run-123"
    assert payload["max_workers"] == 3
    assert payload["sequence"] == [1, 2, 3]
    assert payload["waves"] == [[1, 3], [2]]
    assert payload["stage_ids"] == {"1": "flight", "2": "link", "3": "sat"}
    assert payload["stage_deps"] == {
        "flight": [],
        "link": ["flight", "sat"],
        "sat": [],
    }


def test_automation_manifest_schema_caption_handles_compatible_readers() -> None:
    assert pipeline_automation._automation_manifest_schema_caption(
        {
            "schema": "agilab.pipeline.automation.v2",
            "compatible_schemas": ["agilab.pipeline.automation.v1"],
        }
    ) == (
        "Manifest schema: agilab.pipeline.automation.v2 "
        "(current; compatible readers: agilab.pipeline.automation.v1)"
    )
    assert pipeline_automation._automation_manifest_schema_caption({}) == (
        "Manifest schema: unknown (unknown)"
    )


def test_automation_manifest_schema_status_flags_reader_compatibility() -> None:
    assert pipeline_automation._automation_manifest_schema_status(
        {"schema": "agilab.pipeline.automation.v2"}
    ) == "current"
    assert pipeline_automation._automation_manifest_schema_status(
        {"schema": "agilab.pipeline.automation.v1"}
    ) == "compatible legacy"
    assert pipeline_automation._automation_manifest_schema_status({}) == "unknown"
    assert pipeline_automation._automation_manifest_schema_status(
        {"schema": "example.future"}
    ) == "unsupported"
    assert pipeline_automation._automation_manifest_schema_caption(
        {"schema": "example.future"}
    ) == "Manifest schema: example.future (unsupported)"


def test_automation_manifest_identity_captions_expose_path_and_hash() -> None:
    assert pipeline_automation._automation_manifest_identity_captions(
        {
            "producer": "agilab.pipeline.run_all_stages",
            "producer_version": "9.9.9",
            "run_id": "run-123",
            "profile": "fast",
            "max_workers": 3,
            "local_only": True,
            "workflow_source": "demo/lab_stages.toml",
            "app": "demo_app",
            "target": "demo_target",
            "lab_dir": "/tmp/demo_lab",
            "stages_file": "/tmp/lab_stages.toml",
            "stages_file_sha256": "def456",
            "started_at": "2026-07-03T00:00:00Z",
            "finished_at": "2026-07-03T00:00:01Z",
            "run_manifest_path": "/tmp/pipeline_automation_run-123.json",
            "manifest_path": "/tmp/pipeline_automation_run-123.json",
            "latest_manifest_path": "/tmp/pipeline_automation_manifest.json",
            "manifest_sha256": "abc123",
        },
        path="/tmp/latest.json",
    ) == [
        "Manifest producer: agilab.pipeline.run_all_stages",
        "Producer version: 9.9.9",
        "Run ID: run-123",
        "Automation profile: fast",
        "Max workers: 3",
        "Local-only evidence: yes",
        "Workflow source: demo/lab_stages.toml",
        "App: demo_app",
        "Target: demo_target",
        "Lab directory: /tmp/demo_lab",
        "Stages file: /tmp/lab_stages.toml",
        "Stages file SHA-256: def456",
        "Started at: 2026-07-03T00:00:00Z",
        "Finished at: 2026-07-03T00:00:01Z",
        "Run manifest file: /tmp/pipeline_automation_run-123.json",
        "Latest manifest file: /tmp/pipeline_automation_manifest.json",
        "Manifest SHA-256: abc123",
    ]
    assert pipeline_automation._automation_manifest_identity_captions(
        {},
        path="/tmp/latest.json",
    ) == ["Manifest file: /tmp/latest.json"]


def test_automation_manifest_identity_captions_support_legacy_manifest_path() -> None:
    assert pipeline_automation._automation_manifest_identity_captions(
        {"manifest_path": "/tmp/pipeline_automation_run-123.json"},
        path="/tmp/pipeline_automation_manifest.json",
    ) == [
        "Run manifest file: /tmp/pipeline_automation_run-123.json",
        "Latest manifest file: /tmp/pipeline_automation_manifest.json",
    ]
    assert pipeline_automation._automation_manifest_paths(
        {
            "run_manifest_path": "/tmp/run.json",
            "manifest_path": "/tmp/compat.json",
            "latest_manifest_path": "/tmp/latest.json",
        },
        path="/tmp/fallback.json",
    ) == ("/tmp/run.json", "/tmp/latest.json")


def test_automation_manifest_duration_label_formats_seconds() -> None:
    assert pipeline_automation._automation_manifest_duration_label(
        {"duration_seconds": 1.25}
    ) == "1.2s"
    assert pipeline_automation._automation_manifest_duration_label(
        {"duration_seconds": 65.5}
    ) == "1m 5.5s"
    assert pipeline_automation._automation_manifest_duration_label(
        {"duration_seconds": 3665.25}
    ) == "1h 1m 5.2s"
    assert pipeline_automation._automation_manifest_duration_label({}) == "unknown"


def test_automation_manifest_error_caption_shows_failed_run_error() -> None:
    assert pipeline_automation._automation_manifest_error_caption(
        {"error": "Stage 3 failed"}
    ) == "Run error: Stage 3 failed"
    assert pipeline_automation._automation_manifest_error_caption({}) == ""


def test_automation_manifest_writer_emits_schema_contract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(pipeline_automation.st, "session_state", {})
    monkeypatch.setattr(
        pipeline_automation,
        "_pipeline_automation_producer_version",
        lambda: "9.9.9",
    )
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text(
        """
[[demo]]
id = "stage_one"
D = "demo/pipeline"
C = "print('demo')"
""".lstrip(),
        encoding="utf-8",
    )
    env = SimpleNamespace(
        runenv=tmp_path / "logs",
        app="demo_app",
        target="demo_target",
    )

    manifest_path = pipeline_automation._write_pipeline_automation_manifest(
        env=env,
        index_page="demo/lab_stages.toml",
        run_id="run-123",
        profile="balanced",
        status="completed",
        lab_dir=tmp_path,
        stages_file=stages_file,
        sequence=[0],
        waves=[[0]],
        max_workers=2,
        stage_ids={0: "stage_one"},
        stage_deps={0: []},
        stages=[{"stage_index": 1, "status": "completed", "outputs": []}],
        started_at="2026-07-03T00:00:00Z",
        finished_at="2026-07-03T00:00:01Z",
        duration_seconds=1.0,
        executed=1,
        skipped=0,
        error="",
    )

    assert manifest_path is not None
    latest_path = Path(env.runenv) / pipeline_automation.PIPELINE_AUTOMATION_MANIFEST_FILENAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    latest_payload = json.loads(latest_path.read_text(encoding="utf-8"))

    for written_payload in (payload, latest_payload):
        assert written_payload["schema"] == "agilab.pipeline.automation.v2"
        assert written_payload["compatible_schemas"] == [
            "agilab.pipeline.automation.v1"
        ]
        assert written_payload["producer"] == "agilab.pipeline.run_all_stages"
        assert written_payload["producer_version"] == "9.9.9"
        assert written_payload["local_only"] is True
        assert written_payload["run_id"] == "run-123"
        assert written_payload["workflow_source"] == "demo/lab_stages.toml"
        assert written_payload["profile"] == "balanced"
        assert written_payload["app"] == "demo_app"
        assert written_payload["target"] == "demo_target"
        assert written_payload["lab_dir"] == str(tmp_path)
        assert written_payload["stages_file"] == str(stages_file)
        assert written_payload["stages_file_sha256"] == hashlib.sha256(
            stages_file.read_bytes()
        ).hexdigest()
        assert written_payload["started_at"] == "2026-07-03T00:00:00Z"
        assert written_payload["finished_at"] == "2026-07-03T00:00:01Z"
        assert written_payload["duration_seconds"] == 1.0
        assert written_payload["sequence"] == [1]
        assert written_payload["waves"] == [[1]]
        assert written_payload["max_workers"] == 2
        assert written_payload["run_manifest_path"] == str(manifest_path)
        assert written_payload["manifest_path"] == str(manifest_path)
        assert written_payload["latest_manifest_path"] == str(latest_path)
        assert written_payload["summary"] == {
            "executed": 1,
            "skipped": 0,
            "failed": 0,
            "stage_count": 1,
        }
        assert written_payload["stage_ids"] == {"1": "stage_one"}
        assert written_payload["stage_deps"] == {"stage_one": []}
        assert written_payload["manifest_sha256"]


def test_build_stage_waves_keeps_legacy_sequence_without_deps() -> None:
    stages = [
        {"id": "one", "C": "print('one')"},
        {"id": "two", "C": "print('two')"},
        {"id": "three", "C": "print('three')"},
    ]

    waves, error, ids, deps = pipeline_automation._build_stage_waves(
        stages,
        [0, 1, 2],
        "balanced",
    )

    assert error is None
    assert waves == [[0], [1], [2]]
    assert ids == {0: "one", 1: "two", 2: "three"}
    assert deps == {0: [], 1: [], 2: []}


def test_build_stage_waves_groups_independent_ready_stages() -> None:
    stages = [
        {"id": "install_a", "deps": [], "C": "print('install a')"},
        {"id": "run_a", "deps": ["install_a"], "C": "print('run a')"},
        {"id": "install_b", "deps": [], "C": "print('install b')"},
        {"id": "run_b", "deps": ["install_b"], "C": "print('run b')"},
        {"id": "summary", "deps": ["run_a", "run_b"], "C": "print('summary')"},
    ]

    waves, error, _ids, deps = pipeline_automation._build_stage_waves(
        stages,
        [0, 1, 2, 3, 4],
        "balanced",
    )

    assert error is None
    assert waves == [[0, 2], [1, 3], [4]]
    assert deps[4] == ["run_a", "run_b"]


def test_build_stage_waves_rejects_unknown_duplicate_and_cycle() -> None:
    unknown = [
        {"id": "one", "deps": ["missing"], "C": "print('one')"},
    ]
    duplicate = [
        {"id": "same", "deps": [], "C": "print('one')"},
        {"id": "same", "deps": [], "C": "print('two')"},
    ]
    cycle = [
        {"id": "one", "deps": ["two"], "C": "print('one')"},
        {"id": "two", "deps": ["one"], "C": "print('two')"},
    ]

    assert "unknown stage id" in pipeline_automation._build_stage_waves(
        unknown,
        [0],
        "balanced",
    )[1]
    assert "Duplicate workflow stage id" in pipeline_automation._build_stage_waves(
        duplicate,
        [0, 1],
        "balanced",
    )[1]
    assert "cycle" in pipeline_automation._build_stage_waves(
        cycle,
        [0, 1],
        "balanced",
    )[1]


def test_dependency_suggestions_use_install_and_data_paths() -> None:
    stages = [
        {
            "id": "flight_install",
            "D": "flight_trajectory/install",
            "C": "print('install')",
        },
        {
            "id": "flight_pipeline",
            "D": "flight_trajectory/pipeline",
            "C": "agi_run(data_out='flight_trajectory/pipeline')",
        },
        {
            "id": "link_pipeline",
            "D": "link_sim/pipeline",
            "C": "agi_run(data_in='flight_trajectory/pipeline', data_out='link_sim/pipeline')",
        },
        {
            "id": "network_pipeline",
            "D": "network_sim/pipeline",
            "C": "agi_run(data_in='link_sim/pipeline', data_out='network_sim/pipeline')",
        },
    ]

    suggestions = pipeline_automation.infer_stage_dependency_suggestions(
        stages,
        [0, 1, 2, 3],
    )

    assert suggestions["flight_pipeline"] == ["flight_install"]
    assert suggestions["link_pipeline"] == ["flight_pipeline"]
    assert suggestions["network_pipeline"] == ["link_pipeline"]


def test_profile_override_deep_merges_automation_settings() -> None:
    entry = {
        "id": "demo",
        "automation": {
            "skip_if_outputs_exist": False,
            "outputs": ["demo/full"],
        },
        "profiles": {
            "fast": {
                "automation": {
                    "skip_if_outputs_exist": True,
                    "outputs": ["demo/fast"],
                },
            },
        },
    }

    base_entry, base_override = pipeline_automation._apply_stage_profile(entry, "balanced")
    fast_entry, fast_override = pipeline_automation._apply_stage_profile(entry, "fast")

    assert base_override == {}
    assert pipeline_automation._stage_output_skip_rule(base_entry) == {
        "enabled": False,
        "outputs": ["demo/full"],
    }
    assert fast_override == {
        "automation": {
            "skip_if_outputs_exist": True,
            "outputs": ["demo/fast"],
        }
    }
    assert pipeline_automation._stage_output_skip_rule(fast_entry) == {
        "enabled": True,
        "outputs": ["demo/fast"],
    }


def test_output_skip_rule_preserves_absolute_output_paths(tmp_path: Path) -> None:
    absolute_output = tmp_path / "absolute" / "pipeline"
    absolute_output.mkdir(parents=True)
    env = SimpleNamespace(workflow_data_root_path=lambda: tmp_path / "share")
    entry = {
        "automation": {
            "skip_if_outputs_exist": True,
            "outputs": [str(absolute_output)],
        },
    }

    skip_current, records = pipeline_automation._should_skip_current_outputs(
        entry,
        env=env,
        stages_file=tmp_path / "lab_stages.toml",
    )

    assert skip_current is True
    assert pipeline_automation._stage_output_skip_rule(entry) == {
        "enabled": True,
        "outputs": [str(absolute_output)],
    }
    assert records[0]["path"] == str(absolute_output)
    assert records[0]["exists"] is True
    assert records[0]["sha256"] == ""
    assert records[0]["sha256_status"] == "directory"


def test_output_records_hash_small_declared_files(tmp_path: Path) -> None:
    share_root = tmp_path / "share"
    output_file = share_root / "demo" / "result.txt"
    output_file.parent.mkdir(parents=True)
    output_file.write_text("workflow evidence\n", encoding="utf-8")
    env = SimpleNamespace(workflow_data_root_path=lambda: share_root)

    records = pipeline_automation._stage_output_records(
        {
            "automation": {
                "outputs": ["demo/result.txt"],
            },
        },
        env=env,
        stages_file=tmp_path / "lab_stages.toml",
    )

    assert records[0]["exists"] is True
    assert records[0]["is_file"] is True
    assert records[0]["sha256"] == hashlib.sha256(b"workflow evidence\n").hexdigest()
    assert records[0]["sha256_status"] == "ok"


def test_output_records_skip_hash_for_large_declared_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(pipeline_automation, "PIPELINE_AUTOMATION_OUTPUT_HASH_MAX_BYTES", 4)
    share_root = tmp_path / "share"
    output_file = share_root / "demo" / "large.bin"
    output_file.parent.mkdir(parents=True)
    output_file.write_bytes(b"larger than cap")
    env = SimpleNamespace(workflow_data_root_path=lambda: share_root)

    records = pipeline_automation._stage_output_records(
        {
            "automation": {
                "outputs": ["demo/large.bin"],
            },
        },
        env=env,
        stages_file=tmp_path / "lab_stages.toml",
    )

    assert records[0]["exists"] is True
    assert records[0]["is_file"] is True
    assert records[0]["size_bytes"] == len(b"larger than cap")
    assert records[0]["sha256"] == ""
    assert records[0]["sha256_status"] == "too_large"


def test_automation_manifest_output_rows_are_ui_ready() -> None:
    manifest = {
        "stages": [
            {
                "stage_index": 1,
                "status": "completed",
                "outputs": [
                    {
                        "spec": "demo/result.txt",
                        "exists": True,
                        "is_file": True,
                        "is_dir": False,
                        "size_bytes": 42,
                        "sha256_status": "ok",
                        "sha256": "abc123",
                        "path": "/tmp/demo/result.txt",
                    },
                    {
                        "spec": "demo/folder",
                        "exists": True,
                        "is_file": False,
                        "is_dir": True,
                        "size_bytes": 128,
                        "sha256_status": "directory",
                        "sha256": "",
                        "path": "/tmp/demo/folder",
                    },
                ],
            },
            {
                "stage_index": 2,
                "status": "skipped_after_failure",
                "outputs": [
                    {
                        "spec": "demo/missing",
                        "exists": False,
                        "is_file": False,
                        "is_dir": False,
                        "sha256_status": "missing",
                        "path": "/tmp/demo/missing",
                    }
                ],
            },
            {
                "stage_index": 3,
                "status": "completed",
                "outputs": [
                    {
                        "spec": "demo/large.bin",
                        "exists": True,
                        "is_file": True,
                        "is_dir": False,
                        "size_bytes": 99,
                        "sha256_status": "too_large",
                        "sha256": "",
                        "path": "/tmp/demo/large.bin",
                    }
                ],
            },
        ],
    }

    rows = pipeline_automation._automation_manifest_output_rows(manifest)

    assert rows == [
        {
            "stage": 1,
            "status": "completed",
            "spec": "demo/result.txt",
            "exists": True,
            "kind": "file",
            "size_bytes": 42,
            "sha256_status": "ok",
            "sha256": "abc123",
            "path": "/tmp/demo/result.txt",
        },
        {
            "stage": 1,
            "status": "completed",
            "spec": "demo/folder",
            "exists": True,
            "kind": "directory",
            "size_bytes": 128,
            "sha256_status": "directory",
            "sha256": "",
            "path": "/tmp/demo/folder",
        },
        {
            "stage": 2,
            "status": "skipped_after_failure",
            "spec": "demo/missing",
            "exists": False,
            "kind": "other",
            "size_bytes": None,
            "sha256_status": "missing",
            "sha256": "",
            "path": "/tmp/demo/missing",
        },
        {
            "stage": 3,
            "status": "completed",
            "spec": "demo/large.bin",
            "exists": True,
            "kind": "file",
            "size_bytes": 99,
            "sha256_status": "too_large",
            "sha256": "",
            "path": "/tmp/demo/large.bin",
        },
    ]
    assert pipeline_automation._automation_manifest_output_summary(manifest) == {
        "outputs": 4,
        "existing": 3,
        "hashed": 1,
        "too_large": 1,
        "missing": 1,
    }


def test_automation_manifest_stage_summary_counts_stage_statuses() -> None:
    assert pipeline_automation._automation_manifest_stage_summary(
        {
            "summary": {
                "stage_count": 4,
                "executed": 2,
                "skipped": 1,
                "failed": 1,
            }
        }
    ) == {
        "stage_count": 4,
        "executed": 2,
        "skipped": 1,
        "failed": 1,
    }
    assert pipeline_automation._automation_manifest_stage_summary(
        {"summary": "invalid"}
    ) == {
        "stage_count": 0,
        "executed": 0,
        "skipped": 0,
        "failed": 0,
    }


def test_output_skip_rule_requires_all_declared_outputs(tmp_path: Path) -> None:
    share_root = tmp_path / "share"
    existing_output = share_root / "demo" / "pipeline"
    existing_output.mkdir(parents=True)
    stages_file = tmp_path / "lab_stages.toml"
    env = SimpleNamespace(workflow_data_root_path=lambda: share_root)
    entry = {
        "automation": {
            "skip_if_outputs_exist": True,
            "outputs": ["demo/pipeline", "demo/missing"],
        },
    }

    skip_current, records = pipeline_automation._should_skip_current_outputs(
        entry,
        env=env,
        stages_file=stages_file,
    )

    assert skip_current is False
    assert [record["spec"] for record in records] == ["demo/missing", "demo/pipeline"]
    assert [record["exists"] for record in records] == [False, True]

    top_level_skip, top_level_records = pipeline_automation._should_skip_current_outputs(
        {
            "skip_if_outputs_exist": True,
            "outputs": ["demo/pipeline"],
        },
        env=env,
        stages_file=stages_file,
    )

    assert top_level_skip is True
    assert [record["spec"] for record in top_level_records] == ["demo/pipeline"]

    (share_root / "demo" / "missing").mkdir(parents=True)

    skip_current, records = pipeline_automation._should_skip_current_outputs(
        entry,
        env=env,
        stages_file=stages_file,
    )

    assert skip_current is True
    assert [record["spec"] for record in records] == ["demo/missing", "demo/pipeline"]


def test_automation_preferences_round_trip_through_lab_stages_meta(tmp_path: Path) -> None:
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text(
        """
[[demo]]
D = "demo/pipeline"
Q = "Run demo"
C = "print('demo')"
""".lstrip(),
        encoding="utf-8",
    )

    pipeline_stages.persist_automation_preferences(
        "demo",
        stages_file,
        {"profile": "fast", "max_workers": 4},
    )

    assert pipeline_stages.load_automation_preferences("demo", stages_file) == {
        "profile": "fast",
        "max_workers": 4,
    }
    payload = tomllib.loads(stages_file.read_text(encoding="utf-8"))
    assert payload["__meta__"]["demo__automation"] == {
        "profile": "fast",
        "max_workers": 4,
    }


def test_automation_preferences_ignore_invalid_or_empty_values(tmp_path: Path) -> None:
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text(
        """
[[demo]]
D = "demo/pipeline"
C = "print('demo')"
""".lstrip(),
        encoding="utf-8",
    )

    pipeline_stages.persist_automation_preferences(
        "demo",
        stages_file,
        {"profile": "", "max_workers": "bad"},
    )

    assert pipeline_stages.load_automation_preferences("demo", stages_file) == {}
