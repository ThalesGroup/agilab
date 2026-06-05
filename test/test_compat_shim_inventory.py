from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

TOOL_PATH = Path("tools/compat_shim_inventory.py").resolve()

spec = importlib.util.spec_from_file_location("compat_shim_inventory_test_module", TOOL_PATH)
assert spec and spec.loader
compat_shim_inventory = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = compat_shim_inventory
spec.loader.exec_module(compat_shim_inventory)


def test_compat_shim_inventory_is_capped() -> None:
    inventory = compat_shim_inventory.build_inventory()

    assert inventory["total"] <= compat_shim_inventory.DEFAULT_MAX_COUNT
    assert inventory["total"] > 0
    assert "src/agilab" in inventory["by_area"]
    assert inventory["files"] == sorted(inventory["files"])


def test_compat_shim_inventory_cli_fails_on_growth() -> None:
    inventory = compat_shim_inventory.build_inventory()

    result = subprocess.run(
        [
            sys.executable,
            "tools/compat_shim_inventory.py",
            "--max-count",
            str(inventory["total"] - 1),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "exceeds cap" in result.stderr
