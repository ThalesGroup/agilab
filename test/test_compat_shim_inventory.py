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
    assert inventory["baseline"] == compat_shim_inventory.COMPAT_SHIM_BASELINE
    assert inventory["baseline"]["owner"]
    assert inventory["baseline"]["removal_milestone"] == (
        "2027.01 compatibility cleanup"
    )
    assert inventory["total"] > 0
    assert "src/agilab" in inventory["by_area"]
    assert inventory["files"] == sorted(inventory["files"])


def test_prose_about_shims_is_not_counted_as_a_shim(tmp_path: Path) -> None:
    """Documentation may say "compatibility shim" without becoming one.

    Regression: a docstring in tools/render_package_maps.py explaining that it
    collapses compatibility shims was itself counted, pushing the inventory one
    over its cap and turning main red.
    """

    prose = tmp_path / "renderer.py"
    prose.write_text(
        '"""Render maps.\n\n'
        "Members are read from the filesystem. Compatibility shims are collapsed\n"
        'into their canonical module responsibility.\n"""\n',
        encoding="utf-8",
    )
    assert not compat_shim_inventory.is_compat_shim(prose)


def test_real_shim_banners_are_still_detected(tmp_path: Path) -> None:
    for index, body in enumerate(
        (
            '"""Compatibility shim for agi_env.legacy."""\n',
            '"""Legacy entrypoint.\n\nCompatibility shim retained for downstream imports.\n"""\n',
            "# Compatibility import for the classified layout\n",
        )
    ):
        path = tmp_path / f"shim_{index}.py"
        path.write_text(body, encoding="utf-8")
        assert compat_shim_inventory.is_compat_shim(path), body


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
