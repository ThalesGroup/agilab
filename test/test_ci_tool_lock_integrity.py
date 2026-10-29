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
        "ci-free-threaded-coverage.in",
        "ci-hf-release.in",
        "ci-lock-audit.in",
        "ci-publish.in",
        "ci-pypi-web.in",
    ]


def test_ci_tool_lock_workflow_audits_release_locks() -> None:
    workflow = Path(".github/workflows/ci-tool-lock-integrity.yml").read_text(
        encoding="utf-8"
    )

    assert "requirements: .github/requirements/ci-lock-audit.txt" in workflow
    for lock_name in (
        "ci-lock-audit.txt",
        "ci-publish.txt",
        "ci-pypi-web.txt",
        "ci-hf-release.txt",
    ):
        assert f".github/requirements/{lock_name}" in workflow
    assert "pip-audit" in workflow
    assert '--requirement "$requirements"' in workflow
    assert "--no-deps" in workflow
    assert "--disable-pip" in workflow
    assert (
        workflow.index("Clean-install publishing lock")
        < workflow.index("python tools/testing/pypi_metadata_smoke.py")
        < workflow.index("Clean-install PyPI web lock")
    )


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

def test_pypi_web_workflow_smoke_executes_the_supported_guarded_cli() -> None:
    import os
    import shlex
    import subprocess
    import sys

    import yaml

    workflow = yaml.load(
        Path(".github/workflows/ci-tool-lock-integrity.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    step = next(
        item for item in workflow["jobs"]["verify-locks"]["steps"]
        if item.get("name") == "Import-smoke PyPI web tools"
    )
    # Execute the real workflow entrypoint, so removed binaries cannot remain
    # in the clean-install smoke after their dependency is removed.
    command = shlex.split(step["run"].strip().splitlines()[-1].removesuffix(">/dev/null"))
    assert command[0] == "python"
    command[0] = sys.executable
    result = subprocess.run(
        command, check=True, capture_output=True, text=True,
        env={**os.environ, "PIP_NO_INDEX": "1", "PYTHONNOUSERSITE": "1"},
    )
    assert "--delete-release" in result.stdout
    assert "--backup-dir" in result.stdout
    assert "--confirm-delete" in result.stdout


@pytest.mark.parametrize(
    ("input_pin", "lock_pin"),
    [
        ("cachecontrol==0.14.4", "cachecontrol[filecache]==0.14.4"),
        ("example-package==2.0", "example_package[cache,ssl]==2.0"),
        ("CacheControl==0.14.4", "cachecontrol[filecache]==0.14.4"),
    ],
)
def test_ci_tool_lock_integrity_accepts_exact_pins_with_extras(
    tmp_path: Path, input_pin: str, lock_pin: str
) -> None:
    input_path, lock_path = _write_lock_pair(
        tmp_path, input_pin=input_pin, lock_pin=lock_pin
    )

    ci_tool_lock_integrity.validate_lock_pair(input_path, lock_path)


def test_ci_tool_lock_integrity_binds_short_reference_to_lock_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    input_path, lock_path = _write_lock_pair(
        lock_root,
        input_pin="example-package==2.0",
        lock_pin="example-package==2.0",
    )
    lock_path.write_text(
        lock_path.read_text(encoding="utf-8").replace(
            str(input_path), input_path.name
        ),
        encoding="utf-8",
    )
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / input_path.name).write_text(
        "example-package==9.0\n", encoding="utf-8"
    )
    monkeypatch.chdir(unrelated)

    ci_tool_lock_integrity.validate_lock_pair(input_path, lock_path)


def test_ci_tool_lock_integrity_rejects_other_input_with_same_basename(
    tmp_path: Path,
) -> None:
    input_path, lock_path = _write_lock_pair(
        tmp_path,
        input_pin="example-package==2.0",
        lock_pin="example-package==2.0",
    )
    other_root = tmp_path / "other"
    other_root.mkdir()
    other_input = other_root / input_path.name
    other_input.write_text("example-package==2.0\n", encoding="utf-8")
    lock_path.write_text(
        lock_path.read_text(encoding="utf-8").replace(
            str(input_path), str(other_input)
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ci_tool_lock_integrity.LockIntegrityError,
        match="missing compiled direct pins: example-package",
    ):
        ci_tool_lock_integrity.validate_lock_pair(input_path, lock_path)


@pytest.mark.parametrize(
    ("lock_pin", "with_hash", "message"),
    [
        (
            "example-package[cache]==1.0",
            True,
            "input version 2.0 != compiled version 1.0",
        ),
        ("example-package[cache]==2.0", False, "has no SHA256 hash"),
    ],
)
def test_ci_tool_lock_integrity_preserves_extra_pin_guards(
    tmp_path: Path, lock_pin: str, with_hash: bool, message: str
) -> None:
    input_path, lock_path = _write_lock_pair(
        tmp_path,
        input_pin="example-package==2.0",
        lock_pin=lock_pin,
        with_hash=with_hash,
    )

    with pytest.raises(ci_tool_lock_integrity.LockIntegrityError, match=message):
        ci_tool_lock_integrity.validate_lock_pair(input_path, lock_path)


@pytest.mark.parametrize(
    "lock_pin",
    [
        "example-package[]==2.0",
        "example-package[cache,]==2.0",
        "example-package[cache]>=2.0",
    ],
)
def test_ci_tool_lock_integrity_rejects_malformed_or_unpinned_extras(
    tmp_path: Path, lock_pin: str
) -> None:
    input_path, lock_path = _write_lock_pair(
        tmp_path, input_pin="example-package==2.0", lock_pin=lock_pin
    )

    with pytest.raises(
        ci_tool_lock_integrity.LockIntegrityError,
        match="expected an exact",
    ):
        ci_tool_lock_integrity.validate_lock_pair(input_path, lock_path)


def test_ci_tool_lock_integrity_does_not_silently_drop_direct_input_extras(
    tmp_path: Path,
) -> None:
    input_path, lock_path = _write_lock_pair(
        tmp_path,
        input_pin="example-package[cache]==2.0",
        lock_pin="example-package[cache]==2.0",
    )

    with pytest.raises(
        ci_tool_lock_integrity.LockIntegrityError,
        match="expected an exact",
    ):
        ci_tool_lock_integrity.validate_lock_pair(input_path, lock_path)
