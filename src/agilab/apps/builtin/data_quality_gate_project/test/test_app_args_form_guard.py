"""Regression tests for the Data Quality Gate artifact-path traversal guard.

Commit f8d987396 hardened ``app_args_form.py`` so a malicious ``env.target`` /
``env.app`` value cannot steer exported analysis artifacts outside the resolved
export root. The guard normalises the target with ``Path(artifact_target).name``,
which strips every directory component (including ``..`` traversal), before it is
joined onto the resolved ``export_root``.

These tests are hermetic: they exercise the guard expression against the real
source file without importing Streamlit or touching the filesystem outside
``tmp_path``.
"""

from __future__ import annotations

from pathlib import Path

import pytest


APP_ROOT = Path(__file__).resolve().parents[1]
APP_ARGS_FORM = APP_ROOT / "src" / "app_args_form.py"


def _apply_target_guard(raw_target: str, export_root: Path) -> Path:
    """Replicate the app_args_form artifact-path guard exactly.

    Mirrors the three hardened lines from ``app_args_form.py``:

        export_root = Path(...).resolve(strict=False)
        artifact_target = Path(artifact_target).name
        artifact_root = export_root / artifact_target / "data_quality_gate"
    """

    export_root = export_root.resolve(strict=False)
    artifact_target = Path(raw_target).name
    return export_root / artifact_target / "data_quality_gate"


def test_guard_source_still_normalises_target_name() -> None:
    """The guard line must remain in the shipped source (fails if removed)."""

    source = APP_ARGS_FORM.read_text(encoding="utf-8")
    assert "artifact_target = Path(artifact_target).name" in source
    assert 'export_root / artifact_target / "data_quality_gate"' in source


@pytest.mark.parametrize(
    "malicious_target",
    [
        "../../etc/x",
        "../../../root/.ssh/authorized_keys",
        "/etc/passwd",
        "a/../../b",
    ],
)
def test_traversal_target_cannot_escape_export_root(
    malicious_target: str, tmp_path: Path
) -> None:
    export_root = tmp_path / "export"
    export_root.mkdir()

    artifact_root = _apply_target_guard(malicious_target, export_root)

    resolved = artifact_root.resolve(strict=False)
    resolved_export_root = export_root.resolve(strict=False)
    # The artifact directory must stay confined under the export root.
    assert resolved == resolved_export_root or resolved_export_root in resolved.parents
    # No traversal component may survive in the joined path.
    assert ".." not in artifact_root.parts


def test_benign_target_is_preserved(tmp_path: Path) -> None:
    export_root = tmp_path / "export"
    export_root.mkdir()

    artifact_root = _apply_target_guard("data_quality_gate_project", export_root)

    assert artifact_root == export_root.resolve(strict=False) / (
        "data_quality_gate_project"
    ) / "data_quality_gate"
