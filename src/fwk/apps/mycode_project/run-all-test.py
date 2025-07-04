#!/usr/bin/env python3
import os
from pathlib import Path
import sys
import subprocess


def main():
    # Project root = where this script is located
    repo_root = Path(__file__).parent.absolute()

    # Path to output badges, adjust as needed
    try:
        badges_root = repo_root.parents[3] / 'docs/html'
    except IndexError:
        badges_root = repo_root / 'badges'
    os.makedirs(badges_root, exist_ok=True)

    # Gather all test*.py recursively under repo_root
    test_files = sorted([
        str(p) for p in repo_root.rglob("test*.py")
        if p.is_file() and ".venv" not in p.parts
    ])
    if not test_files:
        print("No test files found.")
        sys.exit(1)

    coverage_packages = [
        "mycode",
        "mycode_worker"
    ]
    cov_args = [f"--cov={pkg}" for pkg in coverage_packages]

    # Build pytest command
    cmd = [
              sys.executable, "-m", "pytest",
              "--rootdir", str(repo_root),
              *cov_args,
              "--cov-report=term",
              "--cov-report=xml",
              "--import-mode=importlib",
              "--local-badge-output-dir", str(badges_root),
          ] + test_files

    print("Running pytest with command:")
    print(" ".join(cmd))
    # Direct handoff to pytest: unified output, one summary
    proc = subprocess.run(cmd, env=os.environ.copy())
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
