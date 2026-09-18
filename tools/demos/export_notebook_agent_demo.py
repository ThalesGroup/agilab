"""Export only the verified, public files of a completed notebook-agent run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil


def export_demo(run: Path, destination: Path) -> dict:
    report = json.loads((run / "result.json").read_text())
    if report.get("status") != "passed":
        raise ValueError("Only a passed autonomous run can be exported")
    project = run / "decision_lab_project"
    names = ("app.py", "models.py", "solution.ipynb", "lab_stages.toml")
    for name in names:
        path = project / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != report["files"][name]:
            raise ValueError(f"Verified artifact changed: {name}")
    destination.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copyfile(project / name, destination / name)
    shutil.copyfile(project / "source" / "LICENSE", destination / "LICENSE")
    public = {
        "schema": "agilab.notebook_agent.public_demo.v1",
        "status": "passed",
        "run_id": run.name,
        "seconds": report["seconds"],
        "workflow_stages": report["workflow_stages"],
        "source": {key: report["source"][key] for key in (
            "repository", "commit", "url", "author", "license", "sha256", "retrieved_at"
        )},
        "verification": report["verification"],
        "files": {name: report["files"][name] for name in names},
    }
    (destination / "result.json").write_text(json.dumps(public, indent=2) + "\n")
    return public


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = export_demo(args.run.resolve(), args.destination.resolve())
    print(json.dumps({"status": result["status"], "files": sorted(result["files"])}))


if __name__ == "__main__":
    main()
