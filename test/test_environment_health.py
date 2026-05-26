from __future__ import annotations

from types import SimpleNamespace

from agilab import environment_health
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


def test_environment_health_helper_edges_and_render_panel(tmp_path, monkeypatch):
    class BadPath:
        def __fspath__(self):
            raise TypeError("bad path")

        def __str__(self):
            return "bad-path"

    assert environment_health.safe_display_path(None) == "not configured"
    assert environment_health.safe_display_path(BadPath()) == "bad-path"
    assert environment_health.compact_path_caption("x" * 80) == "see environment details"
    assert environment_health.header_value_state("", "") == "incomplete"
    assert environment_health.header_value_state("OK", explicit="ready") == "ready"
    assert environment_health.format_byte_size(-1) == "0 B"
    assert environment_health.format_byte_size(1024 * 1024 * 12) == "12 MB"

    empty_file = tmp_path / "empty.bin"
    empty_file.touch()
    full_file = tmp_path / "full.bin"
    full_file.write_bytes(b"x" * 32)
    assert environment_health.data_share_content_summary(empty_file)[0] == "empty"
    assert environment_health.data_share_content_summary(full_file)[0] == "32 B"
    assert environment_health.path_status(full_file, file=True)[0] == "ready"

    data_dir = tmp_path / "share"
    data_dir.mkdir()
    for index in range(environment_health.DATA_SHARE_SCAN_LIMIT + 1):
        (data_dir / f"item-{index}.txt").write_text("x", encoding="utf-8")
    size, caption = environment_health.data_share_content_summary(data_dir)
    assert size.endswith("+")
    assert "200+ files" in caption

    broken_venv = tmp_path / "broken-venv"
    broken_venv.mkdir()
    assert environment_health.path_status(broken_venv, venv=True)[0] == "incomplete"
    assert environment_health.latest_project_mtime(None) == "unknown"

    monkeypatch.setenv("GPT_OSS_ENDPOINT", "http://localhost:8000")
    local_card, _detail = environment_health._api_key_card(SimpleNamespace(envars={}))
    assert local_card.value == "Local"

    class FakeColumn:
        def __init__(self, streamlit):
            self.streamlit = streamlit

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeContext(FakeColumn):
        pass

    class FakeStreamlit:
        def __init__(self):
            self.markdown_calls: list[tuple[str, bool]] = []
            self.code_calls: list[str] = []

        def container(self, *, border=False):
            assert border is True
            return FakeContext(self)

        def columns(self, count):
            return [FakeColumn(self) for _ in range(count)]

        def expander(self, label, *, expanded=False):
            assert label == "Environment details"
            assert expanded is False
            return FakeContext(self)

        def markdown(self, body, *, unsafe_allow_html=False):
            self.markdown_calls.append((body, unsafe_allow_html))

        def code(self, body, *, language):
            assert language == "text"
            self.code_calls.append(body)

    env = SimpleNamespace(
        active_app=tmp_path,
        app="demo_project",
        target="demo_project",
        app_data_rel=full_file,
        app_settings_source_file=full_file,
        runenv=tmp_path / "missing-runenv",
        envars={},
    )
    streamlit = FakeStreamlit()
    health = environment_health.render_environment_health_panel(
        streamlit,
        env,
        install_status={
            "workerless": True,
            "manager_ready": False,
            "manager_exists": True,
            "manager_problem": "stale manager",
            "manager_venv": broken_venv,
        },
    )

    assert len(health.cards) == 8
    assert any("agilab-header-card" in body for body, _unsafe in streamlit.markdown_calls)
    assert streamlit.code_calls


def test_environment_health_resolvers_and_cluster_edges(tmp_path, monkeypatch):
    source_settings = tmp_path / "seed.toml"
    source_settings.write_text("[args]\n", encoding="utf-8")
    relative_share = tmp_path / "relative-share"
    relative_share.mkdir()

    class TypeErrorResolver:
        app_settings_file = None
        app_settings_source_file = source_settings
        home_abs = tmp_path
        active_app = tmp_path / "missing-app"
        app = "demo_project"
        target = "demo_project"
        app_data_rel = relative_share
        envars = {"OPENAI_API_KEY": "sk-realistic-openai-key"}

        def resolve_user_app_settings_file(self, *args, **kwargs):
            if kwargs.get("ensure_exists") is False:
                raise TypeError("legacy resolver")
            return source_settings

    settings_card, settings_detail = environment_health._settings_card(TypeErrorResolver())
    assert settings_card.value == "Workspace"
    assert settings_detail == ("Settings", str(source_settings))

    class FailingResolver(TypeErrorResolver):
        app_settings_source_file = None

        def resolve_user_app_settings_file(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    missing_card, _missing_detail = environment_health._settings_card(FailingResolver())
    assert missing_card.value == "Missing"

    cluster_card, cluster_detail = environment_health._cluster_share_card(
        TypeErrorResolver(),
        {"cluster": {"cluster_enabled": True, "workers": {"ssh://worker": 1}}},
    )
    assert cluster_card.value == "Missing"
    assert cluster_detail[1] == "remote workers need workers_data_path"

    check_card, check_detail = environment_health._cluster_share_card(
        TypeErrorResolver(),
        {
            "cluster": {
                "cluster_enabled": True,
                "workers": {"ssh://worker": 1},
                "workers_data_path": "missing-relative-share",
            }
        },
    )
    assert check_card.value == "Check path"
    assert str(tmp_path / "missing-relative-share") == check_detail[1]

    monkeypatch.setattr(environment_health, "_default_install_status", lambda _env: {"workerless": True})
    health = environment_health.build_environment_health(TypeErrorResolver(), app_settings={})
    assert _card_map(health)["API keys"].value == "Configured"
