"""Export the checked, public forecast assets of a real notebook-agent run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil


CORE_FILES = {"app.py", "forecast_core.py", "solution.ipynb", "lab_stages.toml"}
PUBLIC_FILES = CORE_FILES | {
    "LICENSE", "MODEL_LICENSE", "NOTICE", "README.md", "requirements.txt", "data/series.csv",
    "data/forecast.json", "source/original.ipynb", "source/LICENSE",
}


def checked_file(root: Path, name: str, expected: str) -> Path:
    """Refuse traversal and symlinks, including symlinked parent directories."""
    relative = PurePosixPath(name)
    if name not in PUBLIC_FILES or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Not a public forecast asset: {name}")
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError(f"Symlinked forecast asset: {name}")
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f"Verified artifact changed: {name}")
    return path


def export_demo(run: Path, destination: Path, validation: Path) -> dict:
    """Require both the autonomous interface check and independent forecast checks.

    The independent receipt is produced after the actual model evaluation. Its
    file hashes cover every public asset, including data absent from the generic
    notebook-agent receipt. It is evidence of those checks, not a signature.
    """
    report = json.loads((run / "result.json").read_text())
    checked = json.loads(validation.read_text())
    if report.get("status") != "passed" or report.get("verification", {}).get("status") != "passed":
        raise ValueError("Only a passed autonomous run can be exported")
    checks = checked.get("checks")
    if (checked.get("status") != "passed" or not isinstance(checks, list)
            or not checks or not all(isinstance(check, str) and check.strip() for check in checks)):
        raise ValueError("Independent forecast validation must pass")
    if checked.get("run_id") != run.name:
        raise ValueError("Forecast validation belongs to another run")
    files = checked.get("files", {})
    if not isinstance(files, dict) or not CORE_FILES.union({"LICENSE"}).issubset(files):
        raise ValueError("Forecast validation must cover all required public files")
    project = run / "notebook_app_project"
    if project.is_symlink():
        raise ValueError("The verified project must not be a symlink")
    paths = {name: checked_file(project, name, digest) for name, digest in files.items()}
    for name in CORE_FILES:
        if report.get("files", {}).get(name) != files[name]:
            raise ValueError(f"Autonomous-run artifact changed: {name}")
    source = dict(report["source"])
    for key in ("repository", "commit", "url", "sha256"):
        if source.get(key) != checked.get("source", {}).get(key):
            raise ValueError(f"Source provenance changed: {key}")
    source = {key: checked["source"][key] for key in (
        "repository", "commit", "url", "sha256", "license", "author",
    )}
    source["retrieved_at"] = report["source"]["retrieved_at"]
    if "source/original.ipynb" in files and files["source/original.ipynb"] != source["sha256"]:
        raise ValueError("Original notebook hash does not match its provenance")
    model = {key: checked["model"][key] for key in ("id", "revision", "license")}
    demo = {key: checked["demo"][key] for key in ("title", "description", "request")}
    public = {
        "schema": "agilab.notebook_agent.public_demo.v1",
        "status": "passed",
        "run_id": run.name,
        "seconds": report["seconds"],
        "workflow_stages": report["workflow_stages"],
        "source": source,
        "model": model,
        "demo": demo,
        "verification_scope": checked["verification_scope"],
        "verification": {
            **report["verification"],
            "forecast": {key: checked[key] for key in ("status", "checks", "measurements")},
        },
        "files": files,
    }
    if "build_model" in report:
        model = report["build_model"]
        if not isinstance(model, dict) or any(
            not isinstance(model.get(key), str) or not model[key].strip()
            for key in ("id", "provider", "execution")
        ):
            raise ValueError("Invalid build model metadata")
        string_fields = {
            "id", "provider", "execution", "revision", "upstream", "upstream_revision",
            "quantization", "method", "coordination",
        }
        bool_fields = {"cloud_codegen_fallback", "tokki_agent_offload"}
        if any(key in model and not isinstance(model[key], str) for key in string_fields):
            raise ValueError("Invalid build model string metadata")
        if any(key in model and not isinstance(model[key], bool) for key in bool_fields):
            raise ValueError("Invalid build model routing metadata")
        public["build_model"] = {key: model[key] for key in sorted(string_fields | bool_fields) if key in model}
    # Verify everything before changing the destination. Require a fresh export
    # so a previous run cannot leave unlisted executable files behind.
    if any(parent.is_symlink() for parent in destination.absolute().parents):
        raise ValueError("Export destination must not traverse symlinks")
    if destination.is_symlink() or (destination.exists() and any(destination.iterdir())):
        raise ValueError("Export destination must be an empty, real directory")
    destination.mkdir(parents=True, exist_ok=True)
    for name, path in paths.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    (destination / "result.json").write_text(json.dumps(public, indent=2) + "\n")
    return public


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--validation", required=True, type=Path)
    args = parser.parse_args()
    result = export_demo(args.run, args.destination, args.validation)
    print(json.dumps({"status": result["status"], "files": sorted(result["files"])}))


if __name__ == "__main__":
    main()
