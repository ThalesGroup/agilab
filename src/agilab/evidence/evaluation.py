"""App-owned, finite evaluations of frozen public fixtures and candidate artifacts.

Only explicit operator requests execute an authored standalone Python scorer.
The scorer runs with the standard library in an isolated child process; this is
not an operating-system sandbox. Receipts prove local observations, not model
quality outside the declared cohort or independent execution attestation.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence

from agilab.evidence import evidence_contract, run_manifest

MANIFEST_SCHEMA = "agilab.eval_manifest.v1"
RECEIPT_SCHEMA = "agilab.evaluation_receipt.v1"
SCORE_SCHEMA = "agilab.eval_score.v1"
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_JSON_BYTES = 1024 * 1024
_DIR_FD_AVAILABLE = os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd
CLAIM_SCOPE = (
    "Local observations from an explicitly requested, frozen app-owned scorer. "
    "Execution trust requires a separate controller pin captured after actual execution. "
    "Self-sealed receipts establish internal consistency only. No LLM grading, deployment, "
    "population-wide quality claim or independent attestation."
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
        raise ValueError(f"{label} must be nonempty text of at most 1000 characters")
    return value


def _digest(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("A lowercase SHA-256 digest is required")
    return value


def _pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in rows:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _number(value: Any) -> float:
    try:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("Metric values must be finite numbers")
        return float(value)
    except OverflowError as exc:
        raise ValueError("Metric values must be finite numbers") from exc


def _invalid_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON value: {value}")


def _float(value: str) -> float:
    return _number(float(value))


def read_evidence_json(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("JSON evidence exceeds the 1 MiB limit")
    try:
        result = json.loads(
            data,
            object_pairs_hook=_pairs,
            parse_constant=_invalid_constant,
            parse_float=_float,
        )
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("Invalid JSON evidence") from exc
    if not isinstance(result, dict):
        raise ValueError("JSON evidence must be an object")
    return result


def confined_path(root: Path, value: str | Path) -> Path:
    """Resolve a path inside an explicit root, rejecting symbolic aliases."""
    root = root.resolve(strict=True)
    candidate = Path(value)
    if candidate.is_absolute():
        try:
            relative = candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("Evidence paths must stay inside the app root") from exc
    else:
        relative = candidate
    stored = relative.as_posix()
    if not stored or stored == "." or ".." in relative.parts or "\\" in stored:
        raise ValueError("Use a normalized app-root-relative evidence path")
    if PurePosixPath(stored).as_posix() != stored:
        raise ValueError("Use a normalized app-root-relative evidence path")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Evidence paths cannot contain symlinks")
    if not current.resolve(strict=False).is_relative_to(root):
        raise ValueError("Evidence paths must stay inside the app root")
    return current


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


class _EvidencePathAbsent(FileNotFoundError):
    """An absent entry observed through stable no-follow parent descriptors."""


def _raise_observed_absence(parent, name, unchanged, error):
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        unchanged()
        raise _EvidencePathAbsent(
            error.errno, error.strerror, error.filename
        ) from error
    raise ValueError("Evidence path changed during absence observation") from error


@contextmanager
def _evidence_parent(root: Path, value: str | Path, *, create: bool = False):
    """Hold root/parent descriptors, refusing aliases and renamed directory entries."""
    root = root.resolve(strict=True)
    path = confined_path(root, value)
    parts = path.relative_to(root).parts
    if not parts or len(root.parts) + len(parts) > 128 or len(str(path)) > 4096:
        raise ValueError("Evidence paths exceed the bounded component limit")
    if not all(hasattr(os, key) for key in ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK")):
        raise ValueError(
            "Descriptor-confined evidence I/O requires POSIX no-follow support"
        )
    if not _DIR_FD_AVAILABLE:
        raise ValueError(
            "Descriptor-confined evidence I/O requires directory descriptors"
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptors = []
    chain = []

    def unchanged():
        for directory, name, child in chain:
            named = os.stat(name, dir_fd=directory, follow_symlinks=False)
            opened = os.fstat(child)
            if not stat.S_ISDIR(named.st_mode) or (named.st_dev, named.st_ino) != (
                opened.st_dev,
                opened.st_ino,
            ):
                raise ValueError("Evidence parent directory changed during I/O")

    try:
        parent = os.open(root.anchor, flags)
        descriptors.append(parent)
        components = [(part, False) for part in root.parts[1:]]
        components += [(part, create) for part in parts[:-1]]
        for index, (name, may_create) in enumerate(components):
            if may_create:
                try:
                    os.mkdir(name, mode=0o700, dir_fd=parent)
                except FileExistsError:
                    pass
            try:
                child = os.open(name, flags, dir_fd=parent)
            except FileNotFoundError as exc:
                # A missing root is a failed trust context, not an absent artifact.
                if index < len(root.parts) - 1:
                    raise
                _raise_observed_absence(parent, name, unchanged, exc)
            descriptors.append(child)
            chain.append((parent, name, child))
            parent = child

        unchanged()
        yield parent, parts[-1], unchanged
        unchanged()
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def read_evidence_file(root: Path, value: str | Path) -> bytes:
    """Read bounded regular bytes through held no-follow directory descriptors."""
    with _evidence_parent(root, value) as (parent, name, unchanged):
        try:
            descriptor = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
            )
        except FileNotFoundError as exc:
            _raise_observed_absence(parent, name, unchanged, exc)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
                raise ValueError(
                    "Evidence files must be regular files of at most 16 MiB"
                )
            chunks = []
            total = 0
            while total <= MAX_FILE_BYTES:
                chunk = os.read(descriptor, min(65536, MAX_FILE_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            after = os.fstat(descriptor)
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (
                total > MAX_FILE_BYTES
                or _identity(before) != _identity(after)
                or (_identity(after) != _identity(named) or total != after.st_size)
            ):
                raise ValueError("Evidence file changed during descriptor read")
            unchanged()
            return b"".join(chunks)
        finally:
            os.close(descriptor)


def file_reference(root: Path, value: str | Path) -> dict[str, Any]:
    path = confined_path(root, value)
    data = read_evidence_file(root, value)
    return {
        "path": path.relative_to(root.resolve()).as_posix(),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def check_file_reference(root: Path, row: Any) -> bytes:
    if not isinstance(row, dict) or set(row) != {"path", "size_bytes", "sha256"}:
        raise ValueError("Invalid evidence file reference")
    _digest(row["sha256"])
    data = read_evidence_file(root, row["path"])
    if (
        type(row["size_bytes"]) is not int
        or len(data) != row["size_bytes"]
        or hashlib.sha256(data).hexdigest() != row["sha256"]
    ):
        raise ValueError(f"Evidence input changed: {row['path']}")
    return data


def seal_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    clean = dict(payload)
    clean.pop("sha256", None)
    return {**clean, "sha256": evidence_contract.sha256_payload(clean)}


def check_evidence_seal(payload: Mapping[str, Any], schema: str) -> None:
    if (
        payload.get("schema") != schema
        or _digest(payload.get("sha256")) != seal_evidence(payload)["sha256"]
    ):
        raise ValueError("Evidence schema or content checksum is invalid")


def persist_evaluation(
    root: Path, output: str | Path, payload: Mapping[str, Any]
) -> Path:
    """Create one immutable artifact through confined descriptors; never follow aliases."""
    path = confined_path(root, output)
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    if len(encoded) > MAX_JSON_BYTES:
        raise ValueError("JSON evidence exceeds the 1 MiB limit")
    with _evidence_parent(root, output, create=True) as (parent, name, unchanged):
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=parent,
        )
        identity = os.fstat(descriptor)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(encoded)
                stream.flush()
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(current.st_mode) or (
                current.st_dev,
                current.st_ino,
                current.st_size,
            ) != (identity.st_dev, identity.st_ino, len(encoded)):
                raise ValueError("Evidence output changed during descriptor write")
            unchanged()
        except BaseException:
            try:
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == (
                    identity.st_dev,
                    identity.st_ino,
                ):
                    os.unlink(name, dir_fd=parent)
            except FileNotFoundError:
                pass
            raise
        finally:
            os.close(descriptor)
    return path


def _metric(metric: Any) -> dict[str, Any]:
    if not isinstance(metric, dict) or set(metric) != {
        "name",
        "unit",
        "direction",
        "sample_count",
    }:
        raise ValueError("Declare metric name, unit, direction and sample_count")
    _text(metric["name"], "Metric name")
    _text(metric["unit"], "Metric unit")
    if metric["direction"] not in {"minimize", "maximize"}:
        raise ValueError("Metric direction must be minimize or maximize")
    if type(metric["sample_count"]) is not int or metric["sample_count"] < 1:
        raise ValueError("Metric sample_count must be a positive integer")
    return metric


def _run_artifact_path(
    root: Path,
    manifest: run_manifest.RunManifest,
    reference: Mapping[str, Any],
    value: str,
) -> Path:
    declared = Path(value)
    if declared.is_absolute() and not declared.is_relative_to(root):
        # Original absolute app metadata remains byte-identical in portable bundles.
        original = Path(manifest.environment.active_app)
        if not original.is_absolute() or original.name != root.name:
            raise ValueError("Run artifact is outside the declared app root")
        try:
            declared = declared.relative_to(original)
        except ValueError as exc:
            raise ValueError("Run artifact is outside the declared app root") from exc
    elif not declared.is_absolute():
        declared = Path(reference["path"]).parent / declared
    return confined_path(root, declared)


def _run_artifact(
    root: Path,
    manifest: run_manifest.RunManifest,
    manifest_ref: Mapping[str, Any],
    artifact: Mapping[str, Any],
) -> None:
    selected = confined_path(root, artifact["path"])
    matches = []
    for row in manifest.artifacts:
        declared = _run_artifact_path(root, manifest, manifest_ref, row.path)
        if declared == selected:
            matches.append(row)
    if len(matches) != 1 or not matches[0].exists or matches[0].kind == "directory":
        raise ValueError(
            "The evaluated artifact must be declared by its exact run manifest"
        )
    if matches[0].sha256 and matches[0].sha256.lower() != artifact["sha256"]:
        raise ValueError(
            "The selected evaluation artifact differs from its recorded run digest"
        )


def build_eval_manifest(
    app_root: Path,
    *,
    fixture: str | Path,
    scorer: str | Path,
    config: str | Path,
    baseline_run: str | Path,
    baseline_artifact: str | Path,
    baseline_reference: str,
    candidate_run: str | Path,
    candidate_artifact: str | Path,
    candidate_reference: str,
    metric: Mapping[str, Any],
) -> dict[str, Any]:
    """Freeze exact file identities without executing any scorer or app."""
    root = app_root.resolve(strict=True)
    inputs = {
        name: file_reference(root, path)
        for name, path in (("fixture", fixture), ("scorer", scorer), ("config", config))
    }
    if confined_path(root, scorer).suffix != ".py":
        raise ValueError("The scorer must be an app-owned standalone .py file")
    metric_row = _metric(dict(metric))
    sides = {}
    for name, run, artifact, reference in (
        ("baseline", baseline_run, baseline_artifact, baseline_reference),
        ("candidate", candidate_run, candidate_artifact, candidate_reference),
    ):
        artifact_row = file_reference(root, artifact)
        run_row = file_reference(root, run)
        manifest = run_manifest.RunManifest.from_dict(
            read_evidence_json(check_file_reference(root, run_row))
        )
        _run_artifact(root, manifest, run_row, artifact_row)
        if manifest.environment.app_name != root.name:
            raise ValueError("Run manifests must identify the declared app root")
        sides[name] = {
            "run_manifest": run_row,
            "run_id": manifest.run_id,
            "artifact": artifact_row,
            "identity": {
                "reference": _text(reference, "Immutable reference"),
                "sha256": artifact_row["sha256"],
            },
        }
    if (
        sides["baseline"]["identity"]["reference"]
        == sides["candidate"]["identity"]["reference"]
    ):
        raise ValueError(
            "Baseline and candidate must have distinct immutable references"
        )
    return seal_evidence(
        {
            "schema": MANIFEST_SCHEMA,
            "producer": __name__,
            "created_at": _now(),
            "app_name": root.name,
            "inputs": inputs,
            "metric": metric_row,
            **sides,
            "claim_scope": CLAIM_SCOPE,
        }
    )


def _manifest(root: Path, path: str | Path) -> dict[str, Any]:
    plan = read_evidence_json(read_evidence_file(root, path))
    check_evidence_seal(plan, MANIFEST_SCHEMA)
    if plan.get("app_name") != root.resolve().name:
        raise ValueError("Evaluation app root does not match")
    _metric(plan.get("metric"))
    if not isinstance(plan.get("inputs"), dict) or set(plan["inputs"]) != {
        "fixture",
        "scorer",
        "config",
    }:
        raise ValueError("Evaluation inputs must bind fixture, scorer and config")
    for row in plan["inputs"].values():
        check_file_reference(root, row)
    if confined_path(root, plan["inputs"]["scorer"]["path"]).suffix != ".py":
        raise ValueError("The scorer must be a standalone .py file")
    for name in ("baseline", "candidate"):
        side = plan[name]
        check_file_reference(root, side["artifact"])
        raw = check_file_reference(root, side["run_manifest"])
        manifest = run_manifest.RunManifest.from_dict(read_evidence_json(raw))
        _run_artifact(root, manifest, side["run_manifest"], side["artifact"])
        if (
            manifest.run_id != side["run_id"]
            or manifest.environment.app_name != plan["app_name"]
        ):
            raise ValueError("Evaluation run identity does not match")
        identity = side["identity"]
        _text(identity["reference"], "Immutable reference")
        if identity["sha256"] != side["artifact"]["sha256"]:
            raise ValueError("Evaluation artifact identity does not match")
    if (
        plan["baseline"]["identity"]["reference"]
        == plan["candidate"]["identity"]["reference"]
    ):
        raise ValueError("Baseline and candidate references must differ")
    return plan


def _score(payload: Any, metric: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        "schema",
        "status",
        "metric",
        "unit",
        "direction",
        "sample_count",
        "value",
    }:
        raise ValueError("The scorer must return the declared eval_score JSON contract")
    if payload["schema"] != SCORE_SCHEMA or payload["status"] != "pass":
        raise ValueError("The authored scorer did not report a passing observation")
    if any(
        payload[key] != metric[expected]
        for key, expected in (
            ("metric", "name"),
            ("unit", "unit"),
            ("direction", "direction"),
            ("sample_count", "sample_count"),
        )
    ):
        raise ValueError("Scorer cohort, unit, metric or direction is incomparable")
    if type(payload["sample_count"]) is not int:
        raise ValueError("Scorer sample_count must be an integer")
    return {**payload, "value": _number(payload["value"])}


def _comparison(scores: Mapping[str, Any], metric: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(scores, dict) or set(scores) != {"baseline", "candidate"}:
        raise ValueError("Both baseline and candidate observations are required")
    for row in scores.values():
        if not isinstance(row, dict) or row.get("status") not in {
            "available",
            "unavailable",
        }:
            raise ValueError("Unknown evaluation observation state")
        if row["status"] == "available":
            if row.get("returncode") != 0:
                raise ValueError(
                    "An available score requires successful scorer execution"
                )
            _digest(row.get("stdout_sha256"))
        else:
            _text(row.get("reason"), "Unavailable observation reason")
            if "score" in row:
                raise ValueError("Unavailable observations cannot contain a score")
    if any(
        scores[name].get("status") != "available" for name in ("baseline", "candidate")
    ):
        return {"status": "unavailable", "delta": None, "improvement": None}
    baseline = _score(scores["baseline"]["score"], metric)["value"]
    candidate = _score(scores["candidate"]["score"], metric)["value"]
    try:
        delta = _number(candidate - baseline)
        improvement = _number(delta if metric["direction"] == "maximize" else -delta)
    except ValueError:
        return {"status": "unavailable", "delta": None, "improvement": None}
    return {
        "status": "pass" if improvement >= 0 else "fail",
        "delta": delta,
        "improvement": improvement,
    }


def _execute_score(
    source: bytes,
    snapshot: Path,
    inputs: Mapping[str, Any],
    side: Mapping[str, Any],
    metric: Mapping[str, Any],
    timeout: float,
) -> dict[str, Any]:
    # Compile the exact checked bytes supplied in argv, never reread a mutable source path.
    source_name = inputs["scorer"]["path"]
    if len(source) > 64 * 1024:
        raise ValueError("Standalone scorer source cannot exceed 64 KiB")
    bootstrap = (
        "import sys, base64; sys.argv = [" + repr(source_name) + "] + sys.argv[1:]; "
        "globals()['__file__'] = " + repr(source_name) + "; "
        "exec(compile(base64.b64decode("
        + repr(base64.b64encode(source).decode("ascii"))
        + "), "
        + repr(source_name)
        + ", 'exec'))"
    )
    argv = [sys.executable, "-I", "-S", "-c", bootstrap]
    for flag, ref in (
        ("--fixture", inputs["fixture"]),
        ("--config", inputs["config"]),
        ("--artifact", side["artifact"]),
        ("--run-manifest", side["run_manifest"]),
    ):
        argv.extend([flag, str(snapshot / ref["path"])])
    env = {
        "PATH": os.defpath,
        "HOME": str(snapshot / "home"),
        "TMPDIR": str(snapshot / "tmp"),
    }
    if "SYSTEMROOT" in os.environ:
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            result = subprocess.run(
                argv,
                cwd=snapshot,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "unavailable",
                "reason": "scorer_timeout",
                "returncode": None,
            }
        stdout.seek(0)
        raw = stdout.read(MAX_JSON_BYTES + 1)
        observation = {
            "returncode": result.returncode,
            "stdout_sha256": hashlib.sha256(raw).hexdigest(),
        }
        if result.returncode:
            return {**observation, "status": "unavailable", "reason": "scorer_failed"}
        try:
            score = _score(read_evidence_json(raw), metric)
        except (ValueError, TypeError) as exc:
            return {
                **observation,
                "status": "unavailable",
                "reason": "invalid_or_incomparable_score",
                "detail": str(exc),
            }
        return {**observation, "status": "available", "score": score}


def verify_evaluation_run(root: Path, reference: Mapping[str, Any]) -> dict[str, Any]:
    """Reuse the run verifier on private, descriptor-captured regular-file bytes.

    The generic verifier still opens paths, so it receives only our private
    snapshot. It never reopens caller-controlled run or artifact paths.
    """
    raw = check_file_reference(root, reference)
    payload = read_evidence_json(raw)
    manifest = run_manifest.RunManifest.from_dict(payload)
    if len(manifest.artifacts) > 256:
        raise ValueError("Evaluation runs may declare at most 256 artifacts")
    total = 0
    with tempfile.TemporaryDirectory(prefix="agilab-eval-run-") as directory:
        snapshot = Path(directory)
        copied = []
        for index, artifact in enumerate(manifest.artifacts):
            declared = _run_artifact_path(root, manifest, reference, artifact.path)
            row = artifact.as_dict()
            destination = snapshot / f"artifact-{index}"
            try:
                data = read_evidence_file(root, declared)
            except _EvidencePathAbsent:
                if artifact.exists or artifact.sha256:
                    raise
            else:
                total += len(data)
                if total > 64 * 1024 * 1024:
                    raise ValueError("Evaluation run snapshot exceeds 64 MiB")
                if (
                    artifact.sha256
                    and hashlib.sha256(data).hexdigest() != artifact.sha256
                ):
                    raise ValueError(
                        "Run artifact bytes differ from their recorded digest"
                    )
                destination.write_bytes(data)
            row["path"] = str(destination)
            copied.append(row)
        payload["artifacts"] = copied
        manifest_path = snapshot / "run_manifest.json"
        manifest_path.write_text(json.dumps(payload, allow_nan=False))
        report = evidence_contract.verify_manifest(manifest_path)
    # Restore the original identity after verifying exactly the captured inputs.
    report["manifest_path"] = str(confined_path(root, reference["path"]))
    report["manifest_sha256"] = reference["sha256"]
    report["manifest_payload_sha256"] = evidence_contract.sha256_payload(
        read_evidence_json(raw)
    )
    return report


def run_evaluation(
    app_root: Path,
    manifest_path: str | Path,
    *,
    operator_requested: bool = False,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Execute a frozen standalone stdlib scorer only after explicit operator opt-in."""
    if operator_requested is not True:
        raise ValueError("Scorer execution requires an explicit operator request")
    timeout = _number(timeout_seconds)
    if not 0 < timeout <= 300:
        raise ValueError(
            "Scorer timeout must be greater than zero and at most 300 seconds"
        )
    root = app_root.resolve(strict=True)
    manifest_ref = file_reference(root, manifest_path)
    plan = _manifest(root, manifest_path)
    refs = list(plan["inputs"].values())
    for name in ("baseline", "candidate"):
        refs.extend([plan[name]["artifact"], plan[name]["run_manifest"]])
    captured = {row["path"]: check_file_reference(root, row) for row in refs}
    scores = {}
    with tempfile.TemporaryDirectory(prefix="agilab-eval-") as temporary:
        snapshot = Path(temporary)
        for directory in ("home", "tmp"):
            (snapshot / directory).mkdir()
        for path, data in sorted(captured.items()):
            destination = confined_path(snapshot, path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            destination.chmod(0o400)
        source = captured[plan["inputs"]["scorer"]["path"]]
        for name in ("baseline", "candidate"):
            report = verify_evaluation_run(root, plan[name]["run_manifest"])
            if report["status"] != "pass":
                scores[name] = {
                    "status": "unavailable",
                    "reason": "run_verification_failed",
                }
            else:
                scores[name] = _execute_score(
                    source,
                    snapshot,
                    plan["inputs"],
                    plan[name],
                    plan["metric"],
                    timeout,
                )
        # Refuse to pair an observation with input bytes changed during execution.
        try:
            check_file_reference(root, manifest_ref)
            for row in refs:
                check_file_reference(root, row)
            for path, original in captured.items():
                if read_evidence_file(snapshot, path) != original:
                    raise ValueError("Frozen input changed during scorer execution")
        except (OSError, ValueError):
            scores = {
                name: {
                    "status": "unavailable",
                    "reason": "input_changed_during_execution",
                }
                for name in ("baseline", "candidate")
            }
    comparison = _comparison(scores, plan["metric"])
    return seal_evidence(
        {
            "schema": RECEIPT_SCHEMA,
            "producer": __name__,
            "created_at": _now(),
            "eval_manifest": manifest_ref,
            "eval_manifest_sha256": plan["sha256"],
            "baseline": plan["baseline"],
            "candidate": plan["candidate"],
            "metric": plan["metric"],
            "scores": scores,
            "comparison": comparison,
            "evaluation_status": comparison["status"],
            "execution": {
                "operator_requested": True,
                "engine": "isolated-stdlib-python",
                "scorer_sha256": plan["inputs"]["scorer"]["sha256"],
                "producer_sha256": evidence_contract.sha256_file(Path(__file__)),
                "python_version": sys.version,
                "python_executable": sys.executable,
                "python_sha256": evidence_contract.sha256_file(
                    Path(sys.executable).resolve()
                ),
                "timeout_seconds": timeout,
            },
            "claim_scope": CLAIM_SCOPE,
        }
    )


# A caller pin is external trust input, never a value recovered from the receipt
# under verification. This context bridges the existing frozen promotion API.
_TRUSTED_RECEIPT: ContextVar[tuple[Path, str] | None] = ContextVar(
    "agilab_trusted_evaluation_receipt", default=None
)


@contextmanager
def trusted_evaluation_receipt(app_root: Path, receipt_sha256: str):
    """Scope a pin captured by a trusted controller after observing scorer execution.

    A checksum read from an untrusted report supplies no execution authority.
    This is local caller trust, not a signature or independent attestation.
    """
    binding = (app_root.resolve(strict=True), _digest(receipt_sha256))
    token = _TRUSTED_RECEIPT.set(binding)
    try:
        yield
    finally:
        _TRUSTED_RECEIPT.reset(token)


def _execution_pin(root: Path, supplied: str | None) -> str | None:
    if supplied is not None:
        return _digest(supplied)
    binding = _TRUSTED_RECEIPT.get()
    return binding[1] if binding is not None and binding[0] == root else None


def verify_evaluation_receipt(
    app_root: Path,
    receipt_path: str | Path,
    *,
    trusted_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    """Check consistency and an external pin captured by a trusted execution observer.

    Never executes the scorer. A self-sealed receipt alone has no execution authority.
    """
    consistency = "fail"
    try:
        root = app_root.resolve(strict=True)
        receipt_ref = file_reference(root, receipt_path)
        receipt = read_evidence_json(check_file_reference(root, receipt_ref))
        check_evidence_seal(receipt, RECEIPT_SCHEMA)
        check_file_reference(root, receipt["eval_manifest"])
        plan = _manifest(root, receipt["eval_manifest"]["path"])
        if receipt["eval_manifest_sha256"] != plan["sha256"] or any(
            receipt[key] != plan[key] for key in ("baseline", "candidate", "metric")
        ):
            raise ValueError("Evaluation receipt does not match the frozen manifest")
        execution = receipt["execution"]
        if (
            execution["operator_requested"] is not True
            or execution["engine"] != "isolated-stdlib-python"
            or execution["scorer_sha256"] != plan["inputs"]["scorer"]["sha256"]
        ):
            raise ValueError("Evaluation execution binding is invalid")
        expected = _comparison(receipt["scores"], plan["metric"])
        if (
            receipt["comparison"] != expected
            or receipt["evaluation_status"] != expected["status"]
        ):
            raise ValueError("Evaluation comparison does not match the observations")
        consistency = "pass"
        pin = _execution_pin(root, trusted_receipt_sha256)
        if pin is None:
            raise ValueError(
                "Trusted execution requires an external receipt SHA-256 pin from the controller that observed the scorer; self-sealed evidence is only internally consistent"
            )
        if pin != receipt["sha256"]:
            raise ValueError(
                "Evaluation receipt differs from the trusted execution pin"
            )
        check_file_reference(root, receipt_ref)
        return {
            "status": "pass",
            "evaluation_status": receipt["evaluation_status"],
            "receipt": receipt_ref,
            "payload": receipt,
            "internal_consistency_status": consistency,
            "execution_authenticity": "caller_pinned_receipt",
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {
            "status": "fail",
            "evaluation_status": "unavailable",
            "internal_consistency_status": consistency,
            "execution_authenticity": "untrusted",
            "reason": str(exc),
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run or verify a frozen app-owned evaluation."
    )
    parser.add_argument("operation", choices=("run", "verify"))
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument(
        "--manifest", help="Frozen eval manifest path, relative to app root."
    )
    parser.add_argument(
        "--receipt", required=True, help="Receipt path, relative to app root."
    )
    parser.add_argument(
        "--execute-scorer",
        action="store_true",
        help="Explicitly request authored local scorer execution.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=30)
    parser.add_argument(
        "--trusted-receipt-sha256",
        help="External canonical receipt pin captured by a trusted execution observer; never copy this from untrusted evidence.",
    )
    args = parser.parse_args(argv)
    try:
        if args.operation == "run":
            if not args.manifest:
                parser.error("run requires --manifest")
            payload = run_evaluation(
                args.app_root,
                args.manifest,
                operator_requested=args.execute_scorer,
                timeout_seconds=args.timeout_seconds,
            )
            persist_evaluation(args.app_root, args.receipt, payload)
            result = verify_evaluation_receipt(
                args.app_root, args.receipt, trusted_receipt_sha256=payload["sha256"]
            )
            result["observed_execution_receipt_sha256"] = payload["sha256"]
        else:
            result = verify_evaluation_receipt(
                args.app_root,
                args.receipt,
                trusted_receipt_sha256=args.trusted_receipt_sha256,
            )
    except (OSError, ValueError) as exc:
        result = {
            "status": "fail",
            "evaluation_status": "unavailable",
            "reason": str(exc),
        }
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return (
        0 if result["status"] == "pass" and result["evaluation_status"] == "pass" else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
