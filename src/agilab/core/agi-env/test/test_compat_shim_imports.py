from __future__ import annotations

import importlib

import pytest


SHIM_MODULES = (
    "agi_env._optional_ui",
    "agi_env.agi_env",
    "agi_env.agi_env_app_switch_support",
    "agi_env.agi_env_execution_methods",
    "agi_env.agi_env_instance_initialization",
    "agi_env.agi_env_meta_support",
    "agi_env.agi_logger",
    "agi_env.app_args",
    "agi_env.app_provider_registry",
    "agi_env.app_settings_support",
    "agi_env.bootstrap_support",
    "agi_env.connector_registry",
    "agi_env.content_renamer_support",
    "agi_env.credential_store_support",
    "agi_env.data_archive_support",
    "agi_env.defaults",
    "agi_env.env_config_support",
    "agi_env.env_runtime_initialization_support",
    "agi_env.execution_support",
    "agi_env.hook_support",
    "agi_env.host_runtime_support",
    "agi_env.installation_support",
    "agi_env.mlflow_store",
    "agi_env.package_layout_support",
    "agi_env.pagelib",
    "agi_env.pagelib_data_support",
    "agi_env.pagelib_execution_support",
    "agi_env.pagelib_navigation_support",
    "agi_env.pagelib_preview_support",
    "agi_env.pagelib_project_support",
    "agi_env.pagelib_resource_support",
    "agi_env.pagelib_runtime_support",
    "agi_env.pagelib_selection_support",
    "agi_env.pagelib_session_support",
    "agi_env.process_support",
    "agi_env.project_clone_support",
    "agi_env.project_initialization_support",
    "agi_env.rename_gitignore_support",
    "agi_env.repository_support",
    "agi_env.runtime_bootstrap_support",
    "agi_env.share_mount_support",
    "agi_env.share_runtime_support",
    "agi_env.snippet_contract",
    "agi_env.source_analysis_ast",
    "agi_env.source_analysis_support",
    "agi_env.streamlit_args",
    "agi_env.ui_docs_support",
    "agi_env.ui_state_support",
    "agi_env.ui_support",
    "agi_env.windows_link_support",
    "agi_env.worker_runtime_support",
    "agi_env.worker_source_support",
)


@pytest.mark.parametrize("module_name", SHIM_MODULES)
def test_agi_env_legacy_shim_imports_target_module(module_name: str) -> None:
    module = importlib.import_module(module_name)

    assert module.__name__ == module_name
    assert module.__dict__.get("_COMPAT_TARGET_MODULE") is not None
