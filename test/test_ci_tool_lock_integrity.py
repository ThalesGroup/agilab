from __future__ import annotations

from pathlib import Path

import pytest

from tools import ci_tool_lock_integrity

REQUIREMENTS_ROOT = Path(".github/requirements")


def _write_lock_pair(
    root: Path,
    *,
    input_pin: str,
    lock_pin: str,
    with_hash: bool = True,
) -> tuple[Path, Path]:
    input_path = root / "ci-example.in"
    lock_path = root / "ci-example.txt"
    input_path.write_text(f"{input_pin}\n", encoding="utf-8")
    hash_line = "    --hash=sha256:" + ("a" * 64) if with_hash else ""
    lock_path.write_text(
        f"{lock_pin} \\\n{hash_line}\n    # via -r {input_path}\n",
        encoding="utf-8",
    )
    return input_path, lock_path


def test_current_ci_tool_locks_match_direct_inputs() -> None:
    pairs = ci_tool_lock_integrity.validate_requirement_directory(REQUIREMENTS_ROOT)

    assert [input_path.name for input_path, _lock_path in pairs] == [
        "ci-hf-release.in",
        "ci-publish.in",
        "ci-pypi-web.in",
    ]


def test_ci_tool_lock_integrity_rejects_stale_direct_version(tmp_path: Path) -> None:
    input_path, lock_path = _write_lock_pair(
        tmp_path,
        input_pin="example-package==2.0",
        lock_pin="example_package==1.0",
    )

    with pytest.raises(
        ci_tool_lock_integrity.LockIntegrityError,
        match="input version 2.0 != compiled version 1.0",
    ):
        ci_tool_lock_integrity.validate_lock_pair(input_path, lock_path)


def test_ci_tool_lock_integrity_requires_hash_for_direct_pin(tmp_path: Path) -> None:
    input_path, lock_path = _write_lock_pair(
        tmp_path,
        input_pin="example-package==2.0",
        lock_pin="example-package==2.0",
        with_hash=False,
    )

    with pytest.raises(
        ci_tool_lock_integrity.LockIntegrityError,
        match="has no SHA256 hash",
    ):
        ci_tool_lock_integrity.validate_lock_pair(input_path, lock_path)
