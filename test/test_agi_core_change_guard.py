from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "agi_core_change_guard.py"

spec = importlib.util.spec_from_file_location("agi_core_change_guard", MODULE_PATH)
assert spec is not None and spec.loader is not None
guard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard
spec.loader.exec_module(guard)


def test_protected_path_detection_is_limited_to_agi_core() -> None:
    assert guard.protected_changed_files(
        [
            "src/agilab/core/agi-core/src/agi_core/runtime.py",
            "src/agilab/core/agi-node/src/agi_node/runtime.py",
            "test/test_agi_core_change_guard.py",
        ]
    ) == ("src/agilab/core/agi-core/src/agi_core/runtime.py",)


def test_jpmorard_can_change_protected_agi_core_path() -> None:
    result = guard.evaluate(
        ["src/agilab/core/agi-core/pyproject.toml"],
        actor="jpmorard",
    )

    assert result.passed
    assert result.actor_allowed


def test_other_actor_is_blocked_for_protected_agi_core_path() -> None:
    result = guard.evaluate(
        ["src/agilab/core/agi-core/pyproject.toml"],
        actor="other-user",
    )

    assert not result.passed
    assert not result.actor_allowed
    assert "other-user" in guard.render_result(result)
    assert "src/agilab/core/agi-core/pyproject.toml" in guard.render_result(result)


def test_other_actor_can_change_unprotected_paths() -> None:
    result = guard.evaluate(
        ["src/agilab/core/agi-node/pyproject.toml"],
        actor="other-user",
    )

    assert result.passed
