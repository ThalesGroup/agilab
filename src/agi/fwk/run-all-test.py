#!/usr/bin/env python3
import os
from pathlib import Path
import sys
import subprocess

# Set PYTHONPATH to include core/src for imports
core_src_path = str((Path(__file__).parent / "core" / "src").resolve())
pp = os.environ.get("PYTHONPATH", "")
if core_src_path not in pp.split(os.pathsep):
    os.environ["PYTHONPATH"] = core_src_path + (os.pathsep + pp if pp else "")

def main():
    repo_root = Path(__file__).parent.absolute()
    badges_root = repo_root.parent.parent.parent / 'docs/html'
    os.makedirs(badges_root, exist_ok=True)

    # Find all test files (excluding those in .venv)
    test_files = sorted(
        p for p in repo_root.rglob("test*.py")
        if p.is_file() and ".venv" not in p.parts
    )
    if not test_files:
        print("No test files found.")
        sys.exit(1)

    # Coverage packages updated (base_worker removed)
    coverage_packages = [
        "agi_manager",
        "agi_runner",
        "agent_worker",
        "dag_worker",
        "pandas_worker",
        "polars_worker",
    ]

    cov_args = []
    for pkg in coverage_packages:
        cov_args.append(f"--cov={pkg}")

    cmd = [
        sys.executable, "-m", "pytest",
        "--rootdir", str(repo_root),
        *cov_args,
        "--cov-report=term",
        "--cov-report=xml",
        "--import-mode=importlib",
        "--local-badge-output-dir",
        str(badges_root),
    ] + [str(f) for f in test_files]

    print("Running pytest with command:")
    print(" ".join(cmd))
    proc = subprocess.run(cmd, env=os.environ.copy())
    sys.exit(proc.returncode)

if __name__ == "__main__":
    main()
