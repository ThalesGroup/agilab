from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


PAGE_PATH = (
    "src/agilab/apps-pages/view_uav_queue_analysis/src/view_uav_queue_analysis/view_uav_queue_analysis.py"
)


def test_view_uav_queue_analysis_renders_exported_artifacts(tmp_path, monkeypatch) -> None:
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    project_dir = apps_dir / "uav_queue_project"
    (project_dir / "src" / "uav_queue").mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text("[project]\nname='uav-queue-project'\n", encoding="utf-8")
    (project_dir / "src" / "app_settings.toml").write_text("[args]\n", encoding="utf-8")
    (project_dir / "src" / "uav_queue" / "__init__.py").write_text("", encoding="utf-8")

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

    argv = [Path(PAGE_PATH).name, "--active-app", str(project_dir)]
    with patch.object(sys, "argv", argv):
        monkeypatch.setenv("AGI_EXPORT_DIR", str(tmp_path / "export"))
        monkeypatch.setenv("AGI_LOCAL_SHARE", str(tmp_path / "localshare"))
        monkeypatch.setenv("AGI_CLUSTER_SHARE", str(tmp_path / "clustershare"))
        monkeypatch.setenv("OPENAI_API_KEY", "dummy")
        monkeypatch.setenv("IS_SOURCE_ENV", "1")
        at = AppTest.from_file(PAGE_PATH, default_timeout=20)
        at.run()

    assert not at.exception
    assert any(title.value == "UAV queue analysis" for title in at.title)
    assert any(metric.label == "PDR" for metric in at.metric)
    assert len(at.dataframe) >= 1
    assert len(at.selectbox) >= 1
    assert len(at.text_input) >= 2


def test_view_uav_queue_analysis_reports_missing_peer_artifacts(tmp_path, monkeypatch) -> None:
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    project_dir = apps_dir / "uav_queue_project"
    (project_dir / "src" / "uav_queue").mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text("[project]\nname='uav-queue-project'\n", encoding="utf-8")
    (project_dir / "src" / "app_settings.toml").write_text("[args]\n", encoding="utf-8")
    (project_dir / "src" / "uav_queue" / "__init__.py").write_text("", encoding="utf-8")

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

    argv = [Path(PAGE_PATH).name, "--active-app", str(project_dir)]
    with patch.object(sys, "argv", argv):
        monkeypatch.setenv("AGI_EXPORT_DIR", str(tmp_path / "export"))
        monkeypatch.setenv("AGI_LOCAL_SHARE", str(tmp_path / "localshare"))
        monkeypatch.setenv("AGI_CLUSTER_SHARE", str(tmp_path / "clustershare"))
        monkeypatch.setenv("OPENAI_API_KEY", "dummy")
        monkeypatch.setenv("IS_SOURCE_ENV", "1")
        at = AppTest.from_file(PAGE_PATH, default_timeout=20)
        at.run()

    assert not at.exception
    assert any(title.value == "UAV queue analysis" for title in at.title)
    assert any("Related queue artifacts are missing" in error.value for error in at.error)
    assert len(at.code) >= 1
