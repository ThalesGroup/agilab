from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
INSTALL_PS1 = REPO_ROOT / "install.ps1"
INSTALL_ENDUSER_SH = REPO_ROOT / "tools" / "install_enduser.sh"
INSTALL_ENDUSER_PS1 = REPO_ROOT / "tools" / "install_enduser.ps1"
APPS_INSTALL_PY = REPO_ROOT / "src" / "agilab" / "apps" / "install.py"
CORE_INSTALL_PS1 = REPO_ROOT / "src" / "agilab" / "core" / "install.ps1"


_FUNCTION_DEF_RE = re.compile(r"(?m)^[A-Za-z0-9_]+\(\) \{")


def _extract_function(script_text: str, function_name: str, next_function_name: str = "") -> str:
    start = script_text.index(f"{function_name}() {{")
    end = -1
    if next_function_name:
        end = script_text.find(f"\n{next_function_name}()", start)
    if end == -1:
        search_start = start + len(f"{function_name}() {{")
        next_match = _FUNCTION_DEF_RE.search(script_text, pos=search_start)
        end = next_match.start() if next_match else len(script_text)
    return script_text[start:end]


def _run_shell_function(
    script_path: Path,
    function_name: str,
    next_function_name: str,
    invoked_function_name: str,
    argument: str,
) -> str:
    script_text = script_path.read_text(encoding="utf-8")
    function_chunks = [_extract_function(script_text, function_name, next_function_name)]
    if invoked_function_name != function_name:
        function_chunks.append(_extract_function(script_text, invoked_function_name))
    function_body = "\n".join(function_chunks)
    bash_script = f"""#!/usr/bin/env bash
set -euo pipefail
warn() {{
  printf '%s\\n' "$*" >&2
}}
{function_body}
{invoked_function_name} "$1"
"""
    completed = subprocess.run(
        ["bash", "-c", bash_script, "install_local_models_test", argument],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _extract_until_marker(script_text: str, function_name: str, marker: str) -> str:
    start = script_text.index(f"{function_name}() {{")
    end = script_text.index(marker, start)
    return script_text[start:end]


def test_root_installer_normalizes_requested_local_models_and_deduplicates_aliases() -> None:
    normalized = _run_shell_function(
        INSTALL_SH,
        "normalize_local_model_name",
        "local_model_requested",
        "normalize_local_models_csv",
        " qwen2.5-coder ; deepseek-coder:latest, gpt-oss:20b, qwen , qwen3-coder:30b-a3b-q4_K_M, qwen3:30b-a3b-instruct-2507-q4_K_M, ministral-3:14b, phi4-mini:3.8b-q4_K_M, mistral ",
    )

    assert normalized == "qwen deepseek gpt-oss qwen3-coder qwen3 ministral phi4-mini"


def test_installers_normalize_empty_local_model_list_under_nounset() -> None:
    for script_path, next_function_name in (
        (INSTALL_SH, "local_model_requested"),
        (INSTALL_ENDUSER_SH, "ollama_tag_for_family"),
    ):
        normalized = _run_shell_function(
            script_path,
            "normalize_local_model_name",
            next_function_name,
            "normalize_local_models_csv",
            "",
        )

        assert normalized == ""


def test_root_installer_propagates_env_before_core_and_app_installs() -> None:
    script_text = INSTALL_SH.read_text(encoding="utf-8")
    main_text = script_text[script_text.index("check_internet\n") :]

    update_pos = main_text.index("update_environment\n")
    write_pos = main_text.index("write_env_values\n")
    install_core_pos = main_text.index("install_core\n")
    core_tests_pos = main_text.index("maybe_run_core_tests\n")
    app_install_pos = main_text.index("if (( INSTALL_APPS_FLAG )); then")

    assert update_pos < write_pos < install_core_pos < core_tests_pos < app_install_pos


def test_root_installer_default_share_dir_is_user_scoped() -> None:
    script_text = INSTALL_SH.read_text(encoding="utf-8")
    function_body = "\n".join(
        [
            _extract_function(script_text, "default_agi_share_user", "default_agi_cluster_share"),
            _extract_function(script_text, "default_agi_cluster_share"),
        ]
    )
    bash_script = f"""#!/usr/bin/env bash
set -euo pipefail
{function_body}
USER='alice@example.com' default_agi_cluster_share
"""
    completed = subprocess.run(
        ["bash", "-c", bash_script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == "clustershare/alice_example.com"
    assert 'AGI_CLUSTER_SHARE="${AGI_CLUSTER_SHARE:-clustershare}"' not in script_text


def test_root_installer_refuses_ephemeral_validation_paths_with_real_home() -> None:
    script_text = INSTALL_SH.read_text(encoding="utf-8")
    function_body = "\n".join(
        [
            _extract_function(script_text, "looks_ephemeral_validation_path", "guard_ephemeral_validation_env"),
            _extract_until_marker(script_text, "guard_ephemeral_validation_env", "\nUSER_ENV_FILE="),
        ]
    )
    bash_script = f"""#!/usr/bin/env bash
set -euo pipefail
RED=''
YELLOW=''
NC=''
HOME=/home/agilab-user
AGI_INSTALL_PATH=/home/agilab-user/agilab-release-check-demo/agilab
AGI_CLUSTER_SHARE=/home/agilab-user/agilab-release-check-demo/agilab/clustershare
AGI_LOCAL_SHARE=/home/agilab-user/agilab-release-check-demo/agilab/localshare
{function_body}
guard_ephemeral_validation_env
"""
    completed = subprocess.run(
        ["bash", "-c", bash_script],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert "Refusing to persist ephemeral validation paths" in completed.stdout


def test_root_installer_allows_ephemeral_validation_paths_with_isolated_home() -> None:
    script_text = INSTALL_SH.read_text(encoding="utf-8")
    function_body = "\n".join(
        [
            _extract_function(script_text, "looks_ephemeral_validation_path", "guard_ephemeral_validation_env"),
            _extract_until_marker(script_text, "guard_ephemeral_validation_env", "\nUSER_ENV_FILE="),
        ]
    )
    bash_script = f"""#!/usr/bin/env bash
set -euo pipefail
RED=''
YELLOW=''
NC=''
HOME=/home/agilab-user/agilab-release-check-demo/home
AGI_INSTALL_PATH=/home/agilab-user/agilab-release-check-demo/agilab
AGI_CLUSTER_SHARE=/home/agilab-user/agilab-release-check-demo/agilab/clustershare
AGI_LOCAL_SHARE=/home/agilab-user/agilab-release-check-demo/agilab/localshare
{function_body}
guard_ephemeral_validation_env
"""
    completed = subprocess.run(
        ["bash", "-c", bash_script],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0


def test_app_installer_uses_same_user_scoped_share_default() -> None:
    apps_install_text = APPS_INSTALL_PY.read_text(encoding="utf-8")
    compact_text = re.sub(r"\s+", "", apps_install_text)

    assert "from agi_env.runtime_bootstrap_support import default_cluster_share" in apps_install_text
    assert "Path(default_cluster_share(environ=os.environ))" in apps_install_text
    assert 'os.environ.get("AGI_CLUSTER_SHARE",default_cluster_share(environ=os.environ),' in compact_text


def test_enduser_installer_normalizes_requested_local_models_and_deduplicates_aliases() -> None:
    normalized = _run_shell_function(
        INSTALL_ENDUSER_SH,
        "normalize_local_model_name",
        "ollama_tag_for_family",
        "normalize_local_models_csv",
        " deepseek, foo , gpt_oss, qwen2.5 , deepseek-coder, qwen3, qwen3-coder, ministral3, phi-4-mini ",
    )

    assert normalized == "deepseek gpt-oss qwen qwen3 qwen3-coder ministral phi4-mini"


def test_installers_map_supported_local_model_families_to_expected_ollama_tags() -> None:
    root_text = INSTALL_SH.read_text(encoding="utf-8")
    enduser_text = INSTALL_ENDUSER_SH.read_text(encoding="utf-8")

    for script_text in (root_text, enduser_text):
        assert "mistral) echo" not in script_text
        assert 'qwen) echo "qwen2.5-coder:latest" ;;' in script_text
        assert 'deepseek) echo "deepseek-coder:latest" ;;' in script_text
        assert 'gpt-oss) echo "gpt-oss:20b" ;;' in script_text
        assert 'qwen3) echo "qwen3:30b-a3b-instruct-2507-q4_K_M" ;;' in script_text
        assert 'qwen3-coder) echo "qwen3-coder:30b-a3b-q4_K_M" ;;' in script_text
        assert 'ministral) echo "ministral-3:14b-instruct-2512-q4_K_M" ;;' in script_text
        assert 'phi4-mini) echo "phi4-mini:3.8b-q4_K_M" ;;' in script_text


def test_installers_map_local_model_families_to_workflow_providers() -> None:
    cases = [
        ("gpt-oss", "ollama-gpt-oss"),
        ("qwen3-coder", "ollama-qwen3-coder"),
        ("phi4-mini", "ollama-phi4-mini"),
    ]
    for script_path, next_function_name in (
        (INSTALL_SH, "persist_local_llm_env_for_family"),
        (INSTALL_ENDUSER_SH, "ensure_ollama_runtime"),
    ):
        for family, expected in cases:
            provider = _run_shell_function(
                script_path,
                "provider_for_local_model_family",
                next_function_name,
                "provider_for_local_model_family",
                family,
            )
            assert provider == expected


def test_windows_installers_map_local_models_to_workflow_provider_defaults() -> None:
    root_ps1 = INSTALL_PS1.read_text(encoding="utf-8")
    enduser_ps1 = INSTALL_ENDUSER_PS1.read_text(encoding="utf-8")

    for ps1_text in (root_ps1, enduser_ps1):
        assert "[string]$InstallLocalModels" in ps1_text
        assert 'Set-PersistEnvVar -Key "LAB_LLM_PROVIDER" -Value $provider' in ps1_text
        assert 'Set-PersistEnvVar -Key "UOAIC_OLLAMA_ENDPOINT" -Value "http://127.0.0.1:11434"' in ps1_text
        assert 'Set-PersistEnvVar -Key "UOAIC_MODEL" -Value $tag' in ps1_text
        assert 'Set-PersistEnvVar -Key "AGILAB_LLM_BASE_URL" -Value "http://127.0.0.1:11434/v1"' in ps1_text
        assert '"gpt-oss" { return "ollama-gpt-oss" }' in ps1_text
        assert '"qwen3-coder" { return "ollama-qwen3-coder" }' in ps1_text
        assert '"phi4-mini" { return "ollama-phi4-mini" }' in ps1_text
        assert '"gpt-oss" { return "gpt-oss:20b" }' in ps1_text
        assert '"qwen3-coder" { return "qwen3-coder:30b-a3b-q4_K_M" }' in ps1_text

    assert '$enduserArgs += "-InstallLocalModels"' in root_ps1
    assert 'Set-LocalLlmSelection -RequestedModels $script:RequestedLocalModels' in root_ps1
    assert 'Set-LocalLlmSelection -RequestedModels $RequestedLocalModels -EnvFile $EnvFile' in enduser_ps1
    assert root_ps1.index("function Normalize-LocalModelsCsv") < root_ps1.index(
        "$script:RequestedLocalModels = Normalize-LocalModelsCsv -Raw $InstallLocalModels"
    )


def test_installers_expose_and_wire_install_local_models_flag() -> None:
    root_text = INSTALL_SH.read_text(encoding="utf-8")
    enduser_text = INSTALL_ENDUSER_SH.read_text(encoding="utf-8")

    assert "--install-local-models gpt-oss,qwen,deepseek,qwen3,qwen3-coder,ministral,phi4-mini" in root_text
    assert "--install-local-models gpt-oss,qwen,deepseek,qwen3,qwen3-coder,ministral,phi4-mini" in enduser_text
    assert 'setup_requested_local_models "$requested_local_models" "requested local models"' in root_text
    assert 'install_requested_local_models "${INSTALL_LOCAL_MODELS}"' in enduser_text
    for script_text in (root_text, enduser_text):
        assert 'persist_env_var "LAB_LLM_PROVIDER" "$provider"' in script_text
        assert 'persist_env_var "UOAIC_OLLAMA_ENDPOINT" "http://127.0.0.1:11434"' in script_text
        assert 'persist_env_var "UOAIC_MODEL" "$tag"' in script_text
        assert 'persist_env_var "AGILAB_LLM_BASE_URL" "http://127.0.0.1:11434/v1"' in script_text


def test_installers_expose_dry_run_plans_before_dependency_installation() -> None:
    root_text = INSTALL_SH.read_text(encoding="utf-8")
    enduser_text = INSTALL_ENDUSER_SH.read_text(encoding="utf-8")

    for script_text in (root_text, enduser_text):
        assert "--dry-run" in script_text
        assert "dry-run plan" in script_text
        assert "steps_would_run:" in script_text
        assert "exit 0" in script_text

    assert root_text.index("if (( DRY_RUN )); then") < root_text.index("find . \\(")
    assert enduser_text.index("if (( DRY_RUN )); then") < enduser_text.index("if [[ \"$SOURCE\" == \"local\" ]]")


def test_installers_do_not_unconditionally_delete_existing_venvs() -> None:
    root_text = INSTALL_SH.read_text(encoding="utf-8")
    enduser_ps1_text = INSTALL_ENDUSER_PS1.read_text(encoding="utf-8")
    core_install_ps1_text = CORE_INSTALL_PS1.read_text(encoding="utf-8")

    assert 'find . \\( -name ".venv"' not in root_text
    assert "[switch]$ForceRebuild" in enduser_ps1_text
    assert "$existingVenvPython = Get-VenvPython -VenvRoot $Venv" in enduser_ps1_text
    assert "if ($ForceRebuild)" in enduser_ps1_text
    assert "Remove-Item -LiteralPath $venvPath" not in core_install_ps1_text


def test_shell_installers_stage_remote_scripts_before_execution() -> None:
    root_text = INSTALL_SH.read_text(encoding="utf-8")
    enduser_text = INSTALL_ENDUSER_SH.read_text(encoding="utf-8")

    for script_text in (root_text, enduser_text):
        assert "run_remote_shell_installer()" in script_text
        assert "curl --proto '=https' --tlsv1.2 -fsSL" in script_text
        assert "curl -fsSL https://ollama.com/install.sh | sh" not in script_text
        assert "curl -LsSf https://astral.sh/uv/install.sh | sh" not in script_text
        assert '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"' not in script_text

    assert (
        'run_remote_shell_installer "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh" '
        '"Homebrew" "/bin/bash"'
    ) in root_text


def test_windows_enduser_local_source_installs_core_packages_with_dependencies() -> None:
    ps1_text = INSTALL_ENDUSER_PS1.read_text(encoding="utf-8")

    assert "$localCorePaths = @()" in ps1_text
    assert 'Invoke-UvPreview -Args (@("pip", "install", "--upgrade") + $localCorePaths)' in ps1_text
    assert 'Invoke-UvPreview -Args @("pip", "install", "--upgrade", "--no-deps", $corePath)' not in ps1_text
    assert 'Invoke-UvPreview -Args @("pip", "install", "--upgrade", "--no-deps", $AgiInstallRoot)' in ps1_text
