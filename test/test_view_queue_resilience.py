from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from agi_pages.queue_resilience import (
    QUEUE_SUMMARY_GLOB,
    load_queue_summary,
    queue_peer_csv_paths,
)

PAGE_PATH = "src/agilab/apps-pages/view_queue_resilience/src/view_queue_resilience/view_queue_resilience.py"
PAGE_META_PATH = Path(
    "src/agilab/apps-pages/view_queue_resilience/src/view_queue_resilience/page_meta.py"
)


def _page_title() -> str:
    spec = importlib.util.spec_from_file_location(
        "view_queue_resilience_page_meta", PAGE_META_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PAGE_TITLE


def _load_queue_helpers() -> ModuleType:
    source = Path(PAGE_PATH).read_text(encoding="utf-8")
    prefix = source.split("\npage_context = prepare_queue_resilience_page(", 1)[0]
    module = ModuleType("view_queue_resilience_test_module")
    module.__file__ = str(Path(PAGE_PATH).resolve())
    module.__package__ = None
    exec(compile(prefix, str(Path(PAGE_PATH)), "exec"), module.__dict__)
    return module


def test_view_queue_resilience_renders_exported_artifacts(
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
        "relay,packets_delivered,packets_dropped\nrelay-a,18,2\nrelay-b,24,1\n",
        encoding="utf-8",
    )

    at = run_page_app_test(PAGE_PATH, project_dir, export_root=tmp_path / "export")

    assert not at.exception
    assert any(title.value == _page_title() for title in at.title)
    assert any(metric.label == "PDR" for metric in at.metric)
    assert len(at.dataframe) >= 1
    assert len(at.selectbox) >= 1
    assert len(at.text_input) >= 2


def test_view_queue_resilience_reports_missing_peer_artifacts(
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
        "packet_id,origin_kind,status,e2e_delay_ms\n1,source,delivered,85.0\n",
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_node_positions.csv").write_text(
        "time_s,node,role,y_m\n0.0,relay-a,relay,100\n",
        encoding="utf-8",
    )

    at = run_page_app_test(PAGE_PATH, project_dir, export_root=tmp_path / "export")

    assert not at.exception
    assert any(title.value == _page_title() for title in at.title)
    assert any(
        "Related queue artifacts are missing" in error.value for error in at.error
    )
    assert len(at.code) >= 1


def test_view_queue_resilience_warns_when_artifact_directory_is_missing(
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
    assert any(
        "Artifact directory does not exist yet" in warning.value
        for warning in at.warning
    )


def test_view_queue_resilience_reports_missing_delivered_source_packets(
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
        "time_s,relay,queue_depth_pkts\n0.0,relay-a,1\n",
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_packet_events.csv").write_text(
        "packet_id,origin_kind,status,e2e_delay_ms\n"
        "1,source,dropped,\n"
        "2,background,delivered,12.0\n",
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_node_positions.csv").write_text(
        "time_s,node,role,y_m\n0.0,relay-a,relay,100\n",
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_routing_summary.csv").write_text(
        "relay,packets_delivered,packets_dropped\nrelay-a,0,1\n",
        encoding="utf-8",
    )

    at = run_page_app_test(PAGE_PATH, project_dir, export_root=tmp_path / "export")

    assert not at.exception
    assert any(
        "No delivered source packet is available in this run." in info.value
        for info in at.info
    )
    assert any(subheader.value == "Notes" for subheader in at.subheader)


def test_view_queue_resilience_helper_branches(monkeypatch, tmp_path) -> None:
    module = _load_queue_helpers()

    repo_root = tmp_path / "repo"
    src_root = repo_root / "src"
    module_path = (
        src_root
        / "agilab"
        / "apps-pages"
        / "view_queue_resilience"
        / "src"
        / "view_queue_resilience"
        / "view_queue_resilience.py"
    )
    module_path.parent.mkdir(parents=True)
    module_path.write_text("# stub\n", encoding="utf-8")
    (module_path.parent / "page_meta.py").write_text(
        "PAGE_LOGO = 'queued.svg'\nPAGE_TITLE = 'Queue Analysis'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "__file__", str(module_path))
    monkeypatch.setattr(sys, "path", [])
    module.ensure_repo_on_path(module.__file__)
    assert str(src_root) in sys.path
    assert str(repo_root) in sys.path

    logo, title = module._load_page_meta()
    assert logo == "queued.svg"
    assert title == "Queue Analysis"

    peer_paths = queue_peer_csv_paths(tmp_path / "demo_summary_metrics.json")
    assert peer_paths["queue_timeseries"] == tmp_path / "demo_queue_timeseries.csv"
    assert peer_paths["routing_summary"] == tmp_path / "demo_routing_summary.csv"


def test_view_queue_resilience_package_meta(monkeypatch) -> None:
    module = _load_queue_helpers()
    monkeypatch.setitem(
        sys.modules, "view_queue_resilience", ModuleType("view_queue_resilience")
    )
    page_meta_name = "view_queue_resilience.page_meta"
    monkeypatch.setitem(
        sys.modules,
        page_meta_name,
        SimpleNamespace(PAGE_LOGO="pkg-logo.svg", PAGE_TITLE="Pkg Queue"),
    )
    monkeypatch.setattr(module, "__package__", "view_queue_resilience")
    assert module._load_page_meta() == ("pkg-logo.svg", "Pkg Queue")


def test_queue_resilience_support_stays_dataframe_and_streamlit_free(tmp_path) -> None:
    support_path = Path("src/agilab/lib/agi-pages/src/agi_pages/queue_resilience.py")
    tree = ast.parse(support_path.read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        (node.module or "").split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0
    )
    assert imported_roots.isdisjoint({"pandas", "streamlit"})

    summary_path = tmp_path / "demo_summary_metrics.json"
    summary_path.write_text('{"pdr": 0.9}', encoding="utf-8")
    assert load_queue_summary(summary_path) == {"pdr": 0.9}
    assert QUEUE_SUMMARY_GLOB == "**/*_summary_metrics.json"


def test_view_queue_resilience_reuses_existing_session_env(
    tmp_path, create_temp_app_project, monkeypatch
) -> None:
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
            apps_path=project_dir.parent,
            app=project_dir.name,
        )
        at.session_state["queue_resilience_active_app_scope"] = str(
            project_dir.resolve()
        )
        at.run()

    assert not at.exception
    assert any(title.value == _page_title() for title in at.title)


def test_view_queue_resilience_warns_when_summary_glob_is_empty(
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
    assert any(
        "No summary metrics file found" in warning.value for warning in at.warning
    )
