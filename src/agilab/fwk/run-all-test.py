#!/usr/bin/env python3
import sys
import subprocess
from pathlib import Path

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
              "--cov=agi_core",  # measure coverage for your package
              "--cov-report=term",  # add terminal report for percentage output
              "--cov-report=xml",  # retain XML report if needed
              "--import-mode=importlib",
              "--local-badge-output-dir",
              str(repo_root / "badges"),
          ] + [str(f) for f in test_files]

    print("Running pytest with command:")
    print(" ".join(cmd))
    proc = subprocess.run(cmd)
    sys.exit(proc.returncode)

if __name__ == "__main__":
    main()