"""Export only the verified, public files of a completed notebook-agent run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def export_demo(run: Path, destination: Path) -> dict:
    report = json.loads((run / "result.json").read_text())
    if report.get("status") != "passed" or report.get("verification", {}).get("status") != "passed":
        raise ValueError("Only a passed autonomous run can be exported")
    project = run / "decision_lab_project"
    if project.is_symlink() or (project / "source").is_symlink():
        raise ValueError("The verified project and source must not be symlinks")
    names = ("app.py", "models.py", "solution.ipynb", "lab_stages.toml")
    payload = {}
    for name in names:
        path = project / name
        if path.is_symlink():
            raise ValueError(f"Verified artifact changed: {name}")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != report.get("files", {}).get(name):
            raise ValueError(f"Verified artifact changed: {name}")
        payload[name] = data
    license_path = project / "source" / "LICENSE"
    if license_path.is_symlink():
        raise ValueError("The source license must not be a symlink")
    payload["LICENSE"] = license_path.read_bytes()
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
    payload["result.json"] = (json.dumps(public, indent=2) + "\n").encode()
    # Validate and snapshot all inputs before creating or replacing any output.
    if (destination.is_symlink() or any(p.is_symlink() for p in destination.absolute().parents)
            or (destination.exists() and (not destination.is_dir() or any(destination.iterdir())))):
        raise ValueError("Export destination must be an empty real directory")
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in payload.items():
        (destination / name).write_bytes(data)
    return public


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = export_demo(args.run, args.destination)
    print(json.dumps({"status": result["status"], "files": sorted(result["files"])}))


if __name__ == "__main__":
    main()
