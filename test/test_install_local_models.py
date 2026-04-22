from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
INSTALL_ENDUSER_SH = REPO_ROOT / "tools" / "install_enduser.sh"


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
        " qwen2.5-coder ; deepseek-coder:latest, qwen , mistral:instruct ",
    )

    assert normalized == "qwen deepseek mistral"


def test_enduser_installer_normalizes_requested_local_models_and_deduplicates_aliases() -> None:
    normalized = _run_shell_function(
        INSTALL_ENDUSER_SH,
        "normalize_local_model_name",
        "ollama_tag_for_family",
        "normalize_local_models_csv",
        " deepseek, foo , qwen2.5 , deepseek-coder ",
    )

    assert normalized == "deepseek qwen"


def test_installers_map_supported_local_model_families_to_expected_ollama_tags() -> None:
    root_text = INSTALL_SH.read_text(encoding="utf-8")
    enduser_text = INSTALL_ENDUSER_SH.read_text(encoding="utf-8")

    for script_text in (root_text, enduser_text):
        assert 'mistral) echo "mistral:instruct" ;;' in script_text
        assert 'qwen) echo "qwen2.5-coder:latest" ;;' in script_text
        assert 'deepseek) echo "deepseek-coder:latest" ;;' in script_text


def test_installers_expose_and_wire_install_local_models_flag() -> None:
    root_text = INSTALL_SH.read_text(encoding="utf-8")
    enduser_text = INSTALL_ENDUSER_SH.read_text(encoding="utf-8")

    assert "--install-local-models mistral,qwen,deepseek" in root_text
    assert "--install-local-models mistral,qwen,deepseek" in enduser_text
    assert 'setup_requested_local_models "$requested_local_models" "requested local models"' in root_text
    assert 'install_requested_local_models "${INSTALL_LOCAL_MODELS}"' in enduser_text
