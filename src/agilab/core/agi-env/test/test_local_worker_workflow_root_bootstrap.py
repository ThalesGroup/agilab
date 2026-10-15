"""Worker workflow-root bootstrap must preserve shares and persisted configuration."""
from __future__ import annotations

from types import MethodType, SimpleNamespace

import pytest

from agi_env import AgiEnv
from agi_env.runtime import agi_env_instance_initialization as initialization
from agi_env.runtime.env_config_support import load_dotenv_values
from agi_env.shares import share_mount_support


@pytest.mark.parametrize(
    ("process_value", "persisted_value", "expected_source"),
    [
        ("current", "stale", "current"),
        ("current", None, "current"),
        (None, "persisted", "persisted"),
        ("", "persisted", "persisted"),
        ("   ", "persisted", "persisted"),
        (None, None, None),
        ("", None, None),
        (None, None, "existing_sdk"),
        ("", None, "existing_sdk"),
    ],
)
def test_worker_bootstrap_honors_process_workflow_root_without_rewriting_dotenv_or_share(
    tmp_path, monkeypatch, process_value, persisted_value, expected_source,
):
    # Mount readiness is an I/O boundary; bootstrap/normalization helpers stay real.
    monkeypatch.setattr(share_mount_support, "is_mounted", lambda *_a, **_k: True)
    scope_key = "AGILAB_WORKFLOW_DATA_ROOT"
    physical_share = tmp_path / "physical share"
    local_share = tmp_path / "local share"
    current = physical_share / "workflows" / "current with spaces"
    persisted = physical_share / "workflows" / ("stale" if persisted_value == "stale" else "persisted")
    dotenv = tmp_path / ".env"
    contents = "DOTENV_SENTINEL=unchanged\n"
    if persisted_value is not None:
        contents += f"{scope_key}='{persisted}'\n"
    dotenv.write_text(contents, encoding="utf-8")
    dotenv_before = dotenv.read_bytes()
    monkeypatch.setenv("AGI_CLUSTER_SHARE", str(physical_share))
    monkeypatch.setenv("AGI_LOCAL_SHARE", str(local_share))
    if process_value is None:
        monkeypatch.delenv(scope_key, raising=False)
    else:
        monkeypatch.setenv(scope_key, str(current) if process_value == "current" else process_value)
    envars = load_dotenv_values(dotenv)
    env = SimpleNamespace(
        is_worker_env=True, home_abs=tmp_path, envars=envars,
        _share_root_cache=None, _share_target_name=lambda: "uav_queue",
        resolve_user_app_settings_file=lambda **_kwargs: None,
        find_source_app_settings_file=lambda: None,
    )
    env.share_root_path = MethodType(AgiEnv.share_root_path, env)
    env.workflow_data_root_path = MethodType(AgiEnv.workflow_data_root_path, env)
    existing_sdk_root = physical_share / "workflows" / "existing-sdk-scope"
    if expected_source == "existing_sdk":
        env.AGILAB_WORKFLOW_DATA_ROOT = str(existing_sdk_root)
        env.agi_workflow_data_root = str(existing_sdk_root)

    initialization._configure_share_runtime(env, envars=envars, env_path=dotenv)

    expected_root = current if expected_source == "current" else (
        persisted if expected_source == "persisted" else (
            existing_sdk_root if expected_source == "existing_sdk" else physical_share
        )
    )
    assert env.workflow_data_root_path() == expected_root
    assert env.AGI_CLUSTER_SHARE == str(physical_share)
    assert env.AGI_LOCAL_SHARE == str(local_share)
    assert env.agi_share_path_abs == physical_share
    assert env.share_root_path() == physical_share
    assert dotenv.read_bytes() == dotenv_before
    assert load_dotenv_values(dotenv).get(scope_key) == (
        str(persisted) if persisted_value is not None else None
    )
    if expected_source == "current":
        assert env.AGILAB_WORKFLOW_DATA_ROOT == str(current)
        assert envars[scope_key] == str(current)
