#!/usr/bin/env python3
import os
from pathlib import Path
import sys
from pathlib import Path
import subprocess


def main():
    repo_root = Path(__file__).parent.absolute()

    # Find all test files (excluding those in .venv)
    test_files = sorted(
        p for p in repo_root.rglob("test*.py")
        if p.is_file() and ".venv" not in p.parts
    )
    if not test_files:
        print("No test files found.")
        sys.exit(1)

    cmd = [
        sys.executable, "-m", "pytest",
        "--rootdir", str(repo_root),
        "--cov=agi-core",
        "--cov-report=term",
        "--cov-report=xml",
        "--import-mode=importlib",
        "--local-badge-output-dir",
    ] + [str(f) for f in test_files]

    print("Running pytest with command:")
    print(" ".join(cmd))
    proc = subprocess.run(cmd, env=os.environ.copy())
    sys.exit(proc.returncode)

if __name__ == "__main__":
    main()
