"""Import the real worker CLI under the manager's text-capture conditions."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from textwrap import dedent

import pytest


_WORKER_CLI = (
    Path(__file__).resolve().parents[1]
    / "src/agilab/core/agi-node/src/agi_node/agi_dispatcher/cli.py"
)

_IMPORT_PROBE = dedent(
    """
    import contextlib
    import faulthandler
    import io
    import json
    import os
    import runpy
    import sys

    original_stderr = sys.__stderr__
    descriptor = original_stderr.fileno()
    os.fstat(descriptor)
    captured = io.StringIO()
    capture_enabled = sys.argv[2] == "capture"
    result = {
        "handler_enabled_before": faulthandler.is_enabled(),
        "original_descriptor": descriptor,
        "import_succeeded": False,
    }
    context = (
        contextlib.redirect_stderr(captured)
        if capture_enabled
        else contextlib.nullcontext()
    )
    with context:
        try:
            namespace = runpy.run_path(
                sys.argv[1], run_name="agi_node_worker_cli_import_regression"
            )
        except Exception as error:
            result["error_type"] = type(error).__name__
            result["error_message"] = str(error)
        else:
            result["import_succeeded"] = True
            result["module_name"] = namespace["__name__"]
            result["optional_process_module_loaded"] = namespace["psutil"]._module is not None
            if capture_enabled:
                sys.stderr.write("ordinary captured error output\\n")
    os.fstat(descriptor)
    result["handler_enabled_after"] = faulthandler.is_enabled()
    result["stderr_restored"] = sys.stderr is original_stderr
    result["captured_error_output"] = captured.getvalue()
    print(json.dumps(result))
    """
)


def _probe_worker_cli_import(*, capture: bool, invalid_timeout: bool = False) -> dict:
    # Defaults in this dedicated child must not inherit an operator's CLI tuning.
    child_env = {
        key: value for key, value in os.environ.items() if not key.startswith("CLI_")
    }
    if invalid_timeout:
        child_env["CLI_PS_TIMEOUT"] = "invalid-timeout-for-import-regression"
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            _IMPORT_PROBE,
            str(_WORKER_CLI),
            "capture" if capture else "native",
        ],
        env=child_env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.mark.parametrize("capture", [False, True])
def test_worker_cli_import_retains_fault_handler_with_error_capture(capture):
    result = _probe_worker_cli_import(capture=capture)

    assert not result["handler_enabled_before"]
    assert result["import_succeeded"], result
    assert result["handler_enabled_after"]
    assert result["original_descriptor"] == 2
    assert result["stderr_restored"]
    assert result["module_name"] == "agi_node_worker_cli_import_regression"
    assert not result["optional_process_module_loaded"]
    assert result["captured_error_output"] == (
        "ordinary captured error output\n" if capture else ""
    )


def test_worker_cli_capture_preserves_real_import_errors():
    result = _probe_worker_cli_import(capture=True, invalid_timeout=True)

    assert not result["import_succeeded"]
    assert result["error_type"] == "ValueError"
    assert "invalid-timeout-for-import-regression" in result["error_message"]
    assert result["handler_enabled_after"]
    assert result["stderr_restored"]
