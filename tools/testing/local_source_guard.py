"""Portable tracked-source policy; native platform behaviour has separate gates."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import agi_core_change_guard  # noqa: E402
from tools.dataset_release_assets import looks_like_lfs_pointer  # noqa: E402


CRITICAL_ENTRYPOINTS = (
    "src/agilab/main_page.py",
    "src/agilab/first_proof_cli.py",
    "src/agilab/orchestrate_execute.py",
    "src/agilab/pipeline_openai.py",
    "tools/agilab_audit.py",
    "tools/agilab_web_robot.py",
    "tools/newcomer_first_proof.py",
    "tools/first_launch_robot.py",
    "tools/robustness_matrix.py",
    "tools/production_readiness_report.py",
    "tools/security_hygiene_report.py",
    "tools/install_release_proof_package.py",
    "tools/public_proof_scenarios.py",
    "tools/release_proof_report.py",
    "tools/pypi_project_preflight.py",
    "tools/release_status.py",
    "tools/release_handoff.py",
    "tools/release_handoff_guard.py",
    "tools/agi_core_change_guard.py",
    "tools/app_contract_matrix.py",
    "tools/ui_robot_evidence.py",
    "tools/ui_robot_matrix_aggregate.py",
    "tools/pypi_publish.py",
)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True)


def check_source() -> None:
    entries = git("ls-files", "--stage", "-z").split("\0")
    symlinks = [row.split("\t", 1)[-1] for row in entries if row.startswith("120000 ")]
    if symlinks:
        raise ValueError("Tracked symlinks are forbidden: " + ", ".join(symlinks))
    if git("ls-files", "docs/html").strip():
        raise ValueError("Generated docs/html must not be tracked.")
    # Include committed task changes, staged/unstaged edits and untracked files.
    changed = set(git("diff", "--name-only", "origin/main", "--").splitlines())
    changed.update(git("ls-files", "--others", "--exclude-standard").splitlines())
    result = agi_core_change_guard.evaluate(
        sorted(changed),
        actor=__import__("os").environ.get("AGILAB_CORE_CHANGE_ACTOR", ""),
    )
    if not result.passed:
        raise ValueError(agi_core_change_guard.render_result(result))
    for name in CRITICAL_ENTRYPOINTS:
        path = ROOT / name
        compile(path.read_bytes(), name, "exec")
    print(f"Tracked source policy and {len(CRITICAL_ENTRYPOINTS)} entrypoints passed.")


def verify_first_launch_dataset(
    path: Path, expected_sha256: str, expected_size: int
) -> None:
    if not path.is_file():
        raise ValueError("First-launch flight dataset is not available.")
    if looks_like_lfs_pointer(path):
        raise ValueError(
            "First-launch flight dataset is still a Git LFS pointer; materialize this exact dataset explicitly with git lfs."
        )
    if path.stat().st_size != expected_size:
        raise ValueError("First-launch flight dataset size mismatch.")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("First-launch flight dataset SHA256 mismatch.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-launch-dataset", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.first_launch_dataset:
            verify_first_launch_dataset(
                ROOT
                / "src/agilab/apps/builtin/flight_telemetry_project/src/flight_telemetry_worker/dataset.7z",
                "593536ccdc4889b79a7ccd5ab1056a8e6d6f132d760e499d5233ec0c62a08de0",
                1630280,
            )
        else:
            check_source()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
