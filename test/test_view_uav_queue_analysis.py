from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

PAGE_PATH = (
    "src/agilab/apps-pages/view_uav_queue_analysis/src/view_uav_queue_analysis/view_uav_queue_analysis.py"
)
PAGE_META_PATH = Path(
    "src/agilab/apps-pages/view_uav_queue_analysis/src/view_uav_queue_analysis/page_meta.py"
)


def _page_title() -> str:
    spec = importlib.util.spec_from_file_location("view_uav_queue_analysis_page_meta", PAGE_META_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PAGE_TITLE


def _load_uav_queue_helpers() -> ModuleType:
    source = Path(PAGE_PATH).read_text(encoding="utf-8")
    prefix = source.split('\nst.set_page_config(layout="wide")\n', 1)[0]
    module = ModuleType("view_uav_queue_analysis_test_module")
    module.__file__ = str(Path(PAGE_PATH).resolve())
    module.__package__ = None
    exec(compile(prefix, str(Path(PAGE_PATH)), "exec"), module.__dict__)
    return module


def test_view_uav_queue_analysis_renders_exported_artifacts(
    tmp_path, create_temp_app_project, run_page_app_test
) -> None:
    project_dir = create_temp_app_project(
        "uav_queue_project",
        package_name="uav_queue",
        app_settings_text="[args]\n",
        pyproject_name="uav-queue-project",
    )
    artifact_dir = tmp_path / "export" / "uav_queue" / "queue_analysis"
    artifact_dir.mkdir(parents=True)
    stem = "hotspot_queue_aware_seed2026"
    (artifact_dir / f"{stem}_summary_metrics.json").write_text(
        json.dumps(
            {
                "scenario": "hotspot-demo",
                "routing_policy": "queue_aware",
                "source_rate_pps": 14.0,
                "random_seed": 2026,
                "bottleneck_relay": "relay-b",
                "pdr": 0.91,
                "mean_e2e_delay_ms": 87.4,
                "mean_queue_wait_ms": 23.1,
                "max_queue_depth_pkts": 7,
                "notes": "Queue-aware relay selection avoids the busiest relay.",
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_queue_timeseries.csv").write_text(
        "time_s,relay,queue_depth_pkts\n"
        "0.0,relay-a,1\n"
        "0.5,relay-a,2\n"
        "0.0,relay-b,3\n"
        "0.5,relay-b,1\n",
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_packet_events.csv").write_text(
        "packet_id,origin_kind,status,e2e_delay_ms\n"
        "1,source,delivered,85.0\n"
        "2,source,delivered,110.5\n"
        "3,background,dropped,\n",
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_node_positions.csv").write_text(
        "time_s,node,role,y_m\n"
        "0.0,relay-a,relay,100\n"
        "0.5,relay-a,relay,101\n"
        "0.0,relay-b,relay,210\n"
        "0.5,relay-b,relay,212\n",
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_routing_summary.csv").write_text(
        "relay,packets_delivered,packets_dropped\n"
        "relay-a,18,2\n"
        "relay-b,24,1\n",
        encoding="utf-8",
    )

    at = run_page_app_test(PAGE_PATH, project_dir, export_root=tmp_path / "export")

    assert not at.exception
    assert any(title.value == _page_title() for title in at.title)
    assert any(metric.label == "PDR" for metric in at.metric)
    assert len(at.dataframe) >= 1
    assert len(at.selectbox) >= 1
    assert len(at.text_input) >= 2

def test_view_uav_queue_analysis_reports_missing_peer_artifacts(
    tmp_path, create_temp_app_project, run_page_app_test
) -> None:
    project_dir = create_temp_app_project(
        "uav_queue_project",
        package_name="uav_queue",
        app_settings_text="[args]\n",
        pyproject_name="uav-queue-project",
    )
    artifact_dir = tmp_path / "export" / "uav_queue" / "queue_analysis"
    artifact_dir.mkdir(parents=True)
    stem = "hotspot_queue_aware_seed2026"
    (artifact_dir / f"{stem}_summary_metrics.json").write_text(
        json.dumps(
            {
                "scenario": "hotspot-demo",
                "routing_policy": "queue_aware",
                "source_rate_pps": 14.0,
                "random_seed": 2026,
                "bottleneck_relay": "relay-b",
                "pdr": 0.91,
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_packet_events.csv").write_text(
        "packet_id,origin_kind,status,e2e_delay_ms\n"
        "1,source,delivered,85.0\n",
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_node_positions.csv").write_text(
        "time_s,node,role,y_m\n"
        "0.0,relay-a,relay,100\n",
        encoding="utf-8",
    )

    at = run_page_app_test(PAGE_PATH, project_dir, export_root=tmp_path / "export")

    assert not at.exception
    assert any(title.value == _page_title() for title in at.title)
    assert any("Related queue artifacts are missing" in error.value for error in at.error)
    assert len(at.code) >= 1


def test_view_uav_queue_analysis_warns_when_artifact_directory_is_missing(
    tmp_path, create_temp_app_project, run_page_app_test
) -> None:
    project_dir = create_temp_app_project(
        "uav_queue_project",
        package_name="uav_queue",
        app_settings_text="[args]\n",
        pyproject_name="uav-queue-project",
    )

    at = run_page_app_test(PAGE_PATH, project_dir, export_root=tmp_path / "export")

    assert not at.exception
    assert any("Artifact directory does not exist yet" in warning.value for warning in at.warning)


def test_view_uav_queue_analysis_reports_missing_delivered_source_packets(
    tmp_path, create_temp_app_project, run_page_app_test
) -> None:
    project_dir = create_temp_app_project(
        "uav_queue_project",
        package_name="uav_queue",
        app_settings_text="[args]\n",
        pyproject_name="uav-queue-project",
    )
    artifact_dir = tmp_path / "export" / "uav_queue" / "queue_analysis"
    artifact_dir.mkdir(parents=True)
    stem = "hotspot_queue_aware_seed2026"
    (artifact_dir / f"{stem}_summary_metrics.json").write_text(
        json.dumps(
            {
                "scenario": "hotspot-demo",
                "routing_policy": "queue_aware",
                "source_rate_pps": 14.0,
                "random_seed": 2026,
                "bottleneck_relay": "relay-b",
                "pdr": 0.91,
                "notes": "Queue-aware relay selection avoids the busiest relay.",
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_queue_timeseries.csv").write_text(
        "time_s,relay,queue_depth_pkts\n"
        "0.0,relay-a,1\n",
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_packet_events.csv").write_text(
        "packet_id,origin_kind,status,e2e_delay_ms\n"
        "1,source,dropped,\n"
        "2,background,delivered,12.0\n",
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_node_positions.csv").write_text(
        "time_s,node,role,y_m\n"
        "0.0,relay-a,relay,100\n",
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_routing_summary.csv").write_text(
        "relay,packets_delivered,packets_dropped\n"
        "relay-a,0,1\n",
        encoding="utf-8",
    )

    at = run_page_app_test(PAGE_PATH, project_dir, export_root=tmp_path / "export")

    assert not at.exception
    assert any("No delivered source packet is available in this run." in info.value for info in at.info)
    assert any(subheader.value == "Notes" for subheader in at.subheader)


def test_view_uav_queue_analysis_helper_branches(monkeypatch, tmp_path) -> None:
    module = _load_uav_queue_helpers()

    repo_root = tmp_path / "repo"
    src_root = repo_root / "src"
    module_path = src_root / "agilab" / "apps-pages" / "view_uav_queue_analysis" / "src" / "view_uav_queue_analysis" / "view_uav_queue_analysis.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("# stub\n", encoding="utf-8")
    (module_path.parent / "page_meta.py").write_text(
        "PAGE_LOGO = 'queued.svg'\nPAGE_TITLE = 'Queue Analysis'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "__file__", str(module_path))
    monkeypatch.setattr(module.sys, "path", [])
    module._ensure_repo_on_path()
    assert str(src_root) in module.sys.path
    assert str(repo_root) in module.sys.path

    logo, title = module._load_page_meta()
    assert logo == "queued.svg"
    assert title == "Queue Analysis"

    errors: list[str] = []
    def stop_now():
        raise RuntimeError("stop")
    module.st = SimpleNamespace(error=errors.append, stop=stop_now)
    monkeypatch.setattr(module.sys, "argv", [Path(PAGE_PATH).name, "--active-app", str(tmp_path / "missing_app")])
    with pytest.raises(RuntimeError, match="stop"):
        module._resolve_active_app()
    assert any("Provided --active-app path not found" in message for message in errors)

    assert module._discover_files(tmp_path / "missing", "[") == []
    assert module._safe_metric(object()) == "n/a"


def test_view_uav_queue_analysis_package_meta_and_discover_exception(monkeypatch, tmp_path) -> None:
    module = _load_uav_queue_helpers()
    monkeypatch.setitem(sys.modules, "view_uav_queue_analysis", ModuleType("view_uav_queue_analysis"))
    page_meta_name = "view_uav_queue_analysis.page_meta"
    monkeypatch.setitem(
        sys.modules,
        page_meta_name,
        SimpleNamespace(PAGE_LOGO="pkg-logo.svg", PAGE_TITLE="Pkg Queue"),
    )
    monkeypatch.setattr(module, "__package__", "view_uav_queue_analysis")
    assert module._load_page_meta() == ("pkg-logo.svg", "Pkg Queue")

    broken_base = SimpleNamespace(glob=lambda _pattern: (_ for _ in ()).throw(RuntimeError("broken glob")))
    assert module._discover_files(broken_base, "*.json") == []


def test_view_uav_queue_analysis_reuses_existing_session_env(tmp_path, create_temp_app_project, monkeypatch) -> None:
    project_dir = create_temp_app_project(
        "uav_queue_project",
        package_name="uav_queue",
        app_settings_text="[args]\n",
        pyproject_name="uav-queue-project",
    )
    export_root = tmp_path / "export"
    artifact_dir = export_root / "uav_queue" / "queue_analysis"
    artifact_dir.mkdir(parents=True)
    stem = "hotspot_queue_aware_seed2026"
    (artifact_dir / f"{stem}_summary_metrics.json").write_text(
        json.dumps(
            {
                "scenario": "hotspot-demo",
                "routing_policy": "queue_aware",
                "source_rate_pps": 14.0,
                "random_seed": 2026,
                "notes": "ok",
            }
        ),
        encoding="utf-8",
    )

    argv = [Path(PAGE_PATH).name, "--active-app", str(project_dir)]
    with patch.object(sys, "argv", argv):
        monkeypatch.setenv("AGI_EXPORT_DIR", str(export_root))
        monkeypatch.setenv("AGI_LOCAL_SHARE", str(tmp_path / "localshare"))
        monkeypatch.setenv("AGI_CLUSTER_SHARE", str(tmp_path / "clustershare"))
        monkeypatch.setenv("OPENAI_API_KEY", "dummy")
        monkeypatch.setenv("IS_SOURCE_ENV", "1")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(PAGE_PATH, default_timeout=20)
        at.session_state["env"] = SimpleNamespace(
            AGILAB_EXPORT_ABS=export_root,
            target="uav_queue",
            st_resources=tmp_path / "resources",
        )
        at.run()

    assert not at.exception
    assert any(title.value == _page_title() for title in at.title)


def test_view_uav_queue_analysis_warns_when_summary_glob_is_empty(
    tmp_path, create_temp_app_project, run_page_app_test
) -> None:
    project_dir = create_temp_app_project(
        "uav_queue_project",
        package_name="uav_queue",
        app_settings_text="[args]\n",
        pyproject_name="uav-queue-project",
    )
    artifact_dir = tmp_path / "export" / "uav_queue" / "queue_analysis"
    artifact_dir.mkdir(parents=True)

    at = run_page_app_test(PAGE_PATH, project_dir, export_root=tmp_path / "export")

    assert not at.exception
    assert any("No summary metrics file found" in warning.value for warning in at.warning)
