#!/usr/bin/env python3
import os
from pathlib import Path
import sys
import subprocess

# Prepare PYTHONPATH to include cluster/src and node/src
paths = []
pp = os.environ.get("PYTHONPATH", "")
if pp:
    paths.extend(pp.split(os.pathsep))

cluster_src = str((Path(__file__).parent / "cluster" / "src").resolve())
node_src = str((Path(__file__).parent / "node" / "src").resolve())

if cluster_src not in paths:
    paths.insert(0, cluster_src)
if node_src not in paths:
    paths.insert(0, node_src)

os.environ["PYTHONPATH"] = os.pathsep.join(paths)

def main():
    repo_root = Path(__file__).parent.absolute()
    badges_root = repo_root.parent.parent.parent / 'docs/html'
    os.makedirs(badges_root, exist_ok=True)

    test_files = sorted(
        p for p in repo_root.rglob("test*.py")
        if p.is_file() and ".venv" not in p.parts
    )
    if not test_files:
        print("No test files found.")
        sys.exit(1)

    coverage_packages = [
        "agi_runner",
        "agi_manager",
        "agent_worker",
        "dag_worker",
        "pandas_worker",
        "polars_worker",
    ]

    cov_args = [f"--cov={pkg}" for pkg in coverage_packages]

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
