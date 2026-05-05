from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
INSTALL_ENDUSER_SH = REPO_ROOT / "tools" / "install_enduser.sh"
INSTALL_ENDUSER_PS1 = REPO_ROOT / "tools" / "install_enduser.ps1"
APPS_INSTALL_PY = REPO_ROOT / "src" / "agilab" / "apps" / "install.py"


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
            _extract_function(script_text, "default_agi_share_user", "default_agi_share_dir"),
            _extract_function(script_text, "default_agi_share_dir"),
        ]
    )
    bash_script = f"""#!/usr/bin/env bash
set -euo pipefail
{function_body}
USER='alice@example.com' default_agi_share_dir
"""
    completed = subprocess.run(
        ["bash", "-c", bash_script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == "clustershare/alice_example.com"
    assert 'AGI_SHARE_DIR="${AGI_SHARE_DIR:-clustershare}"' not in script_text


def test_app_installer_uses_same_user_scoped_share_default() -> None:
    apps_install_text = APPS_INSTALL_PY.read_text(encoding="utf-8")
    compact_text = re.sub(r"\s+", "", apps_install_text)

    assert "from agi_env.runtime_bootstrap_support import default_cluster_share" in apps_install_text
    assert "Path(default_cluster_share(environ=os.environ))" in apps_install_text
    assert 'os.environ.get("AGI_SHARE_DIR",default_cluster_share(environ=os.environ),' in compact_text


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


def test_installers_expose_and_wire_install_local_models_flag() -> None:
    root_text = INSTALL_SH.read_text(encoding="utf-8")
    enduser_text = INSTALL_ENDUSER_SH.read_text(encoding="utf-8")

    assert "--install-local-models gpt-oss,qwen,deepseek,qwen3,qwen3-coder,ministral,phi4-mini" in root_text
    assert "--install-local-models gpt-oss,qwen,deepseek,qwen3,qwen3-coder,ministral,phi4-mini" in enduser_text
    assert 'setup_requested_local_models "$requested_local_models" "requested local models"' in root_text
    assert 'install_requested_local_models "${INSTALL_LOCAL_MODELS}"' in enduser_text


def test_windows_enduser_local_source_installs_core_packages_with_dependencies() -> None:
    ps1_text = INSTALL_ENDUSER_PS1.read_text(encoding="utf-8")

    assert "$localCorePaths = @()" in ps1_text
    assert 'Invoke-UvPreview -Args (@("pip", "install", "--upgrade") + $localCorePaths)' in ps1_text
    assert 'Invoke-UvPreview -Args @("pip", "install", "--upgrade", "--no-deps", $corePath)' not in ps1_text
    assert 'Invoke-UvPreview -Args @("pip", "install", "--upgrade", "--no-deps", $AgiInstallRoot)' in ps1_text
