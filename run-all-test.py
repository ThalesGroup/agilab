#!/usr/bin/env python3
import os
from pathlib import Path
import sys
import subprocess


def main():
    repo_root = Path(__file__).parent.absolute()
    repo_test = repo_root / "test"
    badges_root = repo_root / 'docs/html'
    os.makedirs(badges_root, exist_ok=True)

    test_files = sorted(
        p for p in repo_test.glob("test*.py")
        if p.is_file() and ".venv" not in p.parts
    )
    if not test_files:
        print("No test files found.")
        sys.exit(1)

    cov_modules = [
        "agilab.agilab",
    ]

    cmd = [
        sys.executable, "-m", "pytest",
        "--rootdir", str(repo_root),
        *(f"--cov={mod}" for mod in cov_modules),
        "--cov-report=term",
        "--cov-report=xml",
        "--import-mode=importlib",
        f"--local-badge-output-dir={badges_root}",
    ] + [str(f) for f in test_files]

    print("Running pytest with command:")
    print(" ".join(cmd))
    proc = subprocess.run(cmd, env=os.environ.copy())
    sys.exit(proc.returncode)

if __name__ == "__main__":
    main()
