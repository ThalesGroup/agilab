from __future__ import annotations

from types import SimpleNamespace

from agilab.environment_health import build_environment_health, compact_path_caption


def _card_map(health):
    return {card.label: card for card in health.cards}


def test_environment_health_model_covers_first_run_diagnostics(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("AGILAB_LLM_API_KEY", raising=False)

    active_app = tmp_path / "apps" / "demo_project"
    active_app.mkdir(parents=True)
    manager_python = active_app / ".venv" / "bin" / "python"
    manager_python.parent.mkdir(parents=True)
    manager_python.touch()
    data_share = tmp_path / "share" / "demo_project"
    data_share.mkdir(parents=True)
    (data_share / "sample.bin").write_bytes(b"x" * 1536)
    settings_file = tmp_path / ".agilab" / "apps" / "demo_project" / "app_settings.toml"
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text("[args]\n", encoding="utf-8")
    cluster_share = tmp_path / "cluster-share"
    cluster_share.mkdir()
    runenv = tmp_path / "runenv"
    runenv.mkdir()
    (runenv / "run_20260506_010203.log").write_text("first\n", encoding="utf-8")
    (runenv / "run_20260506_020304.log").write_text("second\n", encoding="utf-8")

    env = SimpleNamespace(
        active_app=active_app,
        app="demo_project",
        target="demo_project",
        app_data_rel=data_share,
        app_settings_file=settings_file,
        runenv=runenv,
        home_abs=tmp_path,
        envars={"AGILAB_LLM_API_KEY": "sk-local-compatible-demo-key"},
    )

    health = build_environment_health(
        env,
        app_settings={
            "cluster": {
                "cluster_enabled": True,
                "workers": {"10.0.0.5": 1},
                "workers_data_path": str(cluster_share),
            }
        },
        install_status={
            "workerless": False,
            "manager_ready": True,
            "worker_ready": False,
            "manager_exists": True,
            "worker_exists": False,
            "manager_venv": active_app / ".venv",
            "worker_venv": tmp_path / "worker" / ".venv",
        },
    )

    cards = _card_map(health)
    assert set(cards) == {
        "Project path",
        "Manager env",
        "Worker env",
        "Settings",
        "Data share",
        "Cluster share",
        "API keys",
        "Runs",
    }
    assert cards["Project path"].value == "ready"
    assert cards["Manager env"].value == "ready"
    assert cards["Worker env"].value == "missing"
    assert cards["Settings"].value == "Workspace"
    assert cards["Data share"].value == "1.5 KB"
    assert cards["Data share"].caption == "1 file"
    assert cards["Cluster share"].value == "Configured"
    assert cards["API keys"].value == "Configured"
    assert cards["API keys"].caption == "OpenAI-compatible"
    assert cards["Runs"].value == "2"
    assert "sk-local-compatible-demo-key" not in "\n".join(value for _, value in health.details)


def test_environment_health_cluster_share_is_local_when_cluster_has_no_remote_workers(tmp_path):
    env = SimpleNamespace(
        active_app=tmp_path,
        app="demo_project",
        target="demo_project",
        app_data_rel=tmp_path / "missing-share",
        app_settings_file=tmp_path / "missing-settings.toml",
        runenv=tmp_path / "runenv",
        home_abs=tmp_path,
        envars={},
    )

    health = build_environment_health(
        env,
        app_settings={"cluster": {"cluster_enabled": True, "scheduler": "127.0.0.1:8786"}},
        install_status={"workerless": True, "manager_ready": False, "manager_exists": False},
    )

    cards = _card_map(health)
    assert cards["Cluster share"].value == "Local Dask"
    assert cards["Cluster share"].state == "ready"
    assert cards["API keys"].value == "Optional"
    assert cards["API keys"].state == "incomplete"
    assert compact_path_caption(tmp_path / "apps" / "demo_project" / ".venv") == ".venv in demo_project"
