"""Source-bound local workflow evidence. Hashes establish identity, not attestation."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from importlib import metadata
import shutil
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

SCHEMA = "agilab.local_validation.v1"
ENV_KEYS = (
    "PYTHONPATH",
    "UV_PROJECT_ENVIRONMENT",
    "AGILAB_DISABLE_BACKGROUND_SERVICES",
    "UV_NO_SYNC",
    "CI",
    "PATH",
    "AGILAB_SECURITY_CHECK_STRICT",
    "AGILAB_REQUIRE_PLAYWRIGHT_LAYOUT_REGRESSION",
)
VERIFIER = "tools/testing/local_validation_receipt.py"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def source_snapshot(root: Path) -> dict:
    paths = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
        )
        .decode()
        .split("\0")
    )
    files = {}
    for name in sorted(set(paths) - {""}):
        path = root / name
        if not path.exists() and not path.is_symlink():
            continue  # Deleted inputs must match the eventual committed file inventory.
        # Do not follow source symlinks into an unrelated tree.
        files[name] = (
            {"symlink": os.readlink(path)}
            if path.is_symlink()
            else sha256(path)
            if path.is_file()
            else None
        )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    return {"head": head, "files": files, "sha256": digest(files)}


def runtime_identity() -> dict:
    executable = Path(sys.executable).resolve()
    return {
        "python": platform.python_version(),
        "executable": str(executable),
        "executable_sha256": sha256(executable),
        "platform": platform.system(),
        "machine": platform.machine(),
        "configuration": {key: os.environ.get(key, "") for key in ENV_KEYS},
        "dependencies": [
            list(row)
            for row in sorted(
                (
                    dist.metadata["Name"],
                    dist.version,
                    digest(dist.read_text("METADATA") or ""),
                    digest(dist.read_text("RECORD") or ""),
                )
                for dist in metadata.distributions()
            )
        ],
        "tools": {
            name: sha256(Path(path).resolve())
            for name in ("uv", "git", "node", "npm", "dot")
            if (path := shutil.which(name)) and Path(path).is_file()
        },
    }


def artifact_inventory(specs: dict, root: Path) -> dict:
    records = {}
    root = root.resolve()
    for commands in specs.values():
        for spec in commands:
            for name in spec.get("artifact_paths", []):
                relative = Path(name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("artifact pattern escapes the declared root")
                targets = (
                    sorted(root.glob(name))
                    if any(c in name for c in "*?[")
                    else [root / name]
                )
                files = []
                for target in targets:
                    if target.is_symlink() or any(
                        parent.is_symlink()
                        for parent in target.parents
                        if parent != root and parent.is_relative_to(root)
                    ):
                        raise ValueError("artifact symlinks are prohibited")
                    if not target.resolve().is_relative_to(root):
                        raise ValueError("artifact escapes the declared root")
                    if target.is_file():
                        files.append(target)
                if not files:
                    records[name] = {"status": "missing"}
                for target in files:
                    stat = target.stat()
                    record = {"sha256": sha256(target), "size": stat.st_size}
                    after = target.stat()
                    if (
                        after.st_dev,
                        after.st_ino,
                        after.st_size,
                        after.st_mtime_ns,
                    ) != (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns):
                        raise ValueError("artifact changed while hashing")
                    records[target.relative_to(root).as_posix()] = record
    return records


def _junit_has_executed_tests(path: Path) -> bool:
    import xml.etree.ElementTree as ET

    cases = ET.parse(path).findall(".//testcase")
    return (
        bool(cases)
        and any(case.find("skipped") is None for case in cases)
        and not any(
            case.find("failure") is not None or case.find("error") is not None
            for case in cases
        )
    )


def write_receipt(
    path: Path,
    *,
    root: Path,
    before: dict,
    profiles: list[str],
    results: list[dict],
    specs: dict,
    started_at: str,
    options: dict | None = None,
    runtime_before: dict | None = None,
) -> dict:
    after = source_snapshot(root)
    options = dict(options or {})
    if "polars-2-runtime" in specs and not options.get("polars_output_dir"):
        command = specs["polars-2-runtime"][0]["argv"]
        options["polars_output_dir"] = command[command.index("--output-dir") + 1]
    executed = {result["profile"] for result in results}
    statuses = {
        profile: (
            "passed"
            if next(row for row in results if row["profile"] == profile)["success"]
            else "failed"
        )
        if profile in executed
        else "skipped"
        for profile in profiles
    }
    artifacts = artifact_inventory(specs, root)
    runtime = runtime_identity()
    runtime_unchanged = runtime_before is None or runtime_before == runtime
    payload = {
        "schema": SCHEMA,
        "producer": "tools/workflow_parity.py",
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
        "source": before,
        "source_unchanged": before["files"] == after["files"],
        "verifier": {"path": VERIFIER, "sha256": sha256(root / VERIFIER)},
        "runtime": runtime,
        "runtime_unchanged": runtime_unchanged,
        "profiles": statuses,
        "commands": specs,
        "results": results,
        "artifacts": artifacts,
        "options": options or {},
        "source_root": str(root.resolve()),
        "python_invocation": sys.executable,
        "status": "passed"
        if statuses
        and all(s == "passed" for s in statuses.values())
        and before["files"] == after["files"]
        and runtime_unchanged
        and not any(record.get("status") == "missing" for record in artifacts.values())
        else "failed",
        "claim": "Maintainer local execution evidence; not authenticated producer identity or independent attestation.",
        "verification_limits": [
            "Driver Python executable, distribution METADATA/RECORD inventories, effective configuration and tool file bytes are compared. Installed distribution payload files are not independently attested.",
            "Isolated child environments and native libraries retain their command and artifact contracts; this receipt is not an attestation of all mapped child binaries.",
        ],
    }
    try:
        validation = _validate_receipt_payload(payload, root=root)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        SyntaxError,
    ) as exc:
        validation = {"status": "failed", "failures": [str(exc)]}
    if validation["status"] != "passed":
        payload["status"] = "failed"
        payload["validation_failures"] = validation["failures"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def _validate_receipt_payload(payload: dict, *, root: Path) -> dict:
    failures = []
    if payload.get("schema") != SCHEMA:
        raise ValueError("unsupported local validation schema")
    source = payload["source"]
    if source["files"] != source_snapshot(root)["files"] or source["sha256"] != digest(
        source["files"]
    ):
        failures.append("source inputs differ from the executed snapshot")
    if not payload.get("source_unchanged"):
        failures.append("source changed during execution")
    verifier = payload["verifier"]
    if verifier != {"path": VERIFIER, "sha256": sha256(root / VERIFIER)}:
        failures.append("verifier identity differs")
    runtime = payload["runtime"]
    if runtime != runtime_identity():
        failures.append("effective runtime, dependencies or configuration differ")
    if not payload.get("runtime_unchanged"):
        failures.append("runtime changed during execution")
    if not all(
        runtime.get(key)
        for key in (
            "python",
            "platform",
            "machine",
            "executable",
            "executable_sha256",
        )
    ):
        failures.append("runtime identity is incomplete")
    if re.fullmatch(r"[0-9a-f]{64}", str(runtime.get("executable_sha256", ""))) is None:
        failures.append("runtime executable hash is invalid")
    profiles = payload["profiles"]
    results = payload["results"]
    if not profiles or any(status != "passed" for status in profiles.values()):
        failures.append("failed or skipped profiles remain")
    if len(results) != len(profiles) or set(profiles) != {
        row["profile"] for row in results
    }:
        failures.append("profile execution is incomplete")
    from dataclasses import asdict
    from types import SimpleNamespace
    from tools import workflow_parity

    options = payload.get("options", {})
    allowed = {
        "components",
        "skills",
        "app_path",
        "worker_copy",
        "polars_output_dir",
    }
    if set(options) - allowed:
        failures.append("unsupported profile configuration")
    args = SimpleNamespace(**{key: options.get(key) for key in allowed})
    canonical = workflow_parity._profile_commands(args)

    def normalize(value):
        if isinstance(value, str):
            return value.replace(payload["python_invocation"], sys.executable).replace(
                payload["source_root"], str(workflow_parity.REPO_ROOT)
            )
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        return value

    trusted_specs = {}
    if set(payload["commands"]) != set(profiles):
        failures.append("command profile inventory differs")
    for row in results:
        plan = payload["commands"][row["profile"]]
        expected = [asdict(spec) for spec in canonical.get(row["profile"], [])]
        trusted_specs[row["profile"]] = expected
        if not expected or normalize(plan) != expected:
            failures.append("command plan does not match the current profile contract")

        commands = row["commands"]
        if row["success"] is not True or not commands or len(expected) != len(commands):
            failures.append("command execution is incomplete")
            continue
        for actual, expected in zip(commands, expected, strict=True):
            if (
                type(actual["returncode"]) is not int
                or actual["returncode"] != 0
                or actual.get("terminal") != "completed"
                or isinstance(actual.get("duration_seconds"), bool)
                or not isinstance(actual.get("duration_seconds"), (int, float))
                or not 0 <= actual["duration_seconds"] < float("inf")
                or actual["argv"] != expected["argv"]
                or actual["env"] != expected["env"]
                or not Path(actual["cwd"]).is_absolute()
                or Path(actual["cwd"]).resolve()
                != (root / (expected.get("cwd") or "")).resolve()
            ):
                failures.append("command result differs from its plan")
    expected_artifacts = artifact_inventory(trusted_specs, root)
    if payload.get("artifacts") != expected_artifacts:
        failures.append("required artifact inventory, size or digest differs")
    if any(record.get("status") == "missing" for record in expected_artifacts.values()):
        failures.append("required artifacts are missing")
    for name in expected_artifacts:
        if Path(name).name.startswith("junit-") and not _junit_has_executed_tests(
            root / name
        ):
            failures.append(
                "JUnit has failed, entirely skipped or zero executed tests: " + name
            )
    if payload.get("status") != "passed":
        failures.append("receipt has no successful terminal result")
    # A receipt is not a signature or a trust assertion about its producer.
    return {
        "status": "failed" if failures else "passed",
        "profiles": profiles,
        "source_sha256": source["sha256"],
        "runtime": runtime,
        "verification_limits": payload.get("verification_limits", []),
        "failures": failures,
    }


def verify_receipt(
    path: Path, *, root: Path, expected_sha256: str | None = None
) -> dict:
    """Fail closed on stale source, changed artifacts, plan-only or incomplete execution."""
    if path.is_symlink():
        return {
            "status": "failed",
            "path": str(path),
            "profiles": {},
            "failures": ["receipt symlink is prohibited"],
        }
    if not path.is_file():
        return {
            "status": "missing",
            "path": str(path),
            "failures": ["receipt is missing"],
            "profiles": {},
        }
    try:
        file_hash = sha256(path)
        if expected_sha256 and file_hash != expected_sha256:
            raise ValueError("receipt digest mismatch")
        report = _validate_receipt_payload(json.loads(path.read_text()), root=root)
        return {"path": str(path), "sha256": file_hash, **report}
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        SyntaxError,
    ) as exc:
        return {
            "status": "failed",
            "path": str(path),
            "profiles": {},
            "failures": [f"invalid local receipt: {exc}"],
        }
