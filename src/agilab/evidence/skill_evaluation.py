"""Frozen skill-evaluation plans and receipts backed by AGILAB agent runs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any, Mapping, Sequence

from agilab.evidence.evidence_contract import sha256_file, sha256_payload
from agilab.security.secret_uri import redact_text

PLAN_SCHEMA = "agilab.skill_evaluation_plan.v1"
RESULTS_SCHEMA = "agilab.skill_evaluation_results.v1"
RECEIPT_SCHEMA = "agilab.skill_evaluation_receipt.v1"
CHECKS = ("installation", "routing", "task", "persistence")
STATUSES = ("passed", "failed", "not_checked", "insufficient_evidence")
MAX_JSON_BYTES = 4 * 1024 * 1024
CLAIM_SCOPE = (
    "Recorded grader observations for the frozen inputs and linked agent run. "
    "Hashes establish content consistency, not independent attestation, skill routing, "
    "model quality, or successful checks that were not observed. Evaluator configuration "
    "is declared; plan association does not prove that the frozen skill or grader executed."
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("A timezone-aware timestamp is required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("A timezone-aware timestamp is required")
    return result


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
        raise ValueError(
            f"{label} must be a nonempty string of at most 1000 characters"
        )
    return value


def _digest(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Expected a lowercase SHA-256 digest")
    return value


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON value: {value}")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        data = handle.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("JSON evidence exceeds the 4 MiB limit")
    try:
        payload = json.loads(
            data, object_pairs_hook=_pairs, parse_constant=_invalid_constant
        )
    except RecursionError as exc:
        raise ValueError("JSON evidence nesting exceeds the parser limit") from exc
    return _object(payload, "JSON evidence")


def _path(root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Evidence paths must stay within the declared root")
    return resolved


def _relative(value: Any) -> str:
    value = _text(value, "Relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or path.as_posix() != value
    ):
        raise ValueError(
            "Stored evidence paths must be normalized root-relative POSIX paths"
        )
    return value


def _file(root: Path, path: str | Path) -> dict[str, Any]:
    resolved = _path(root, path)
    if not resolved.is_file():
        raise ValueError("A referenced evidence file is missing")
    return {
        "path": resolved.relative_to(root).as_posix(),
        "size_bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def _check_file(root: Path, entry: Any) -> Path:
    entry = _object(entry, "File reference")
    path = _relative(entry.get("path"))
    if _file(root, path) != entry:
        raise ValueError(f"Evidence file changed: {path}")
    return _path(root, path)


def _skill_files(root: Path, skill: str | Path) -> list[dict[str, Any]]:
    directory = _path(root, skill)
    if not (directory / "SKILL.md").is_file():
        raise ValueError("The selected skill directory must contain SKILL.md")
    paths = sorted(directory.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("Skill snapshots cannot contain symlinks")
    files = [_file(root, path) for path in paths if path.is_file()]
    if len(files) > 4096:
        raise ValueError("A skill snapshot cannot exceed 4096 files")
    return files


def _cases(fixtures: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = fixtures.get("cases")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise ValueError("Fixtures must declare between 1 and 1000 cases")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        row = _object(row, "Fixture case")
        case_id = _text(row.get("id"), "Case id")
        checks = row.get("checks")
        if case_id in seen:
            raise ValueError("Fixture case ids must be unique")
        if (
            not isinstance(checks, list)
            or not checks
            or any(check not in CHECKS for check in checks)
        ):
            raise ValueError(
                "Each case must name installation, routing, task, or persistence checks"
            )
        if len(checks) != len(set(checks)):
            raise ValueError("Fixture checks must be unique within each case")
        seen.add(case_id)
        result.append({"id": case_id, "checks": sorted(checks)})
    return sorted(result, key=lambda case: case["id"])


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "sha256": sha256_payload(payload)}


def _check_seal(payload: dict[str, Any], schema: str) -> None:
    if payload.get("schema") != schema:
        raise ValueError("Unsupported evidence schema")
    expected = _digest(payload.get("sha256"))
    if expected != sha256_payload(
        {key: value for key, value in payload.items() if key != "sha256"}
    ):
        raise ValueError("Evidence checksum does not match its content")
    _timestamp(payload.get("created_at"))


def persist_evaluation(
    root: Path, output: str | Path, payload: dict[str, Any]
) -> dict[str, Any]:
    """Publish once, then verify the bytes read back from the destination."""
    root = root.resolve()
    path = _path(root, output)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".skill-evaluation-", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(
            temporary, path
        )  # Atomic publication; an existing result is never replaced.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    if path.read_bytes() != encoded:
        raise ValueError("Persisted evidence did not match the intended bytes")
    return _file(root, path)


def create_evaluation_plan(
    *,
    root: Path,
    skill: str | Path,
    fixtures: str | Path,
    grader: str | Path,
    evaluator: Mapping[str, Any],
) -> dict[str, Any]:
    root = root.resolve()
    mode = evaluator.get("mode")
    if mode not in ("deterministic_fixture", "native_agent"):
        raise ValueError(
            "Evaluation mode must be deterministic_fixture or native_agent"
        )
    runtime = {
        key: _text(evaluator.get(key), key)
        for key in ("runtime", "runtime_version", "model")
    }
    fixture_file = _file(root, fixtures)
    return _seal(
        {
            "schema": PLAN_SCHEMA,
            "created_at": _now(),
            "producer": "python -m agilab.evidence.skill_evaluation plan",
            "skill": {
                "path": _path(root, skill).relative_to(root).as_posix(),
                "files": _skill_files(root, skill),
            },
            "fixtures": fixture_file,
            "grader": _file(root, grader),
            "evaluator": {"mode": mode, **runtime},
            "cases": _cases(_read_json(_path(root, fixtures))),
        }
    )


def _load_plan(root: Path, plan_path: str | Path) -> dict[str, Any]:
    plan = _read_json(_path(root, plan_path))
    _check_seal(plan, PLAN_SCHEMA)
    skill = _object(plan.get("skill"), "Skill snapshot")
    if _skill_files(root, _relative(skill.get("path"))) != skill.get("files"):
        raise ValueError("Skill source changed since the evaluation plan was frozen")
    fixtures = _check_file(root, plan.get("fixtures"))
    _check_file(root, plan.get("grader"))
    if _cases(_read_json(fixtures)) != plan.get("cases"):
        raise ValueError("Plan cases do not match the frozen fixtures")
    evaluator = _object(plan.get("evaluator"), "Evaluator")
    if evaluator.get("mode") not in ("deterministic_fixture", "native_agent"):
        raise ValueError("Unsupported evaluation mode")
    for key in ("runtime", "runtime_version", "model"):
        _text(evaluator.get(key), key)
    return plan


def _outcomes(plan: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    if (
        result.get("schema") != RESULTS_SCHEMA
        or result.get("plan_sha256") != plan["sha256"]
    ):
        raise ValueError(
            "Grader output must name the frozen plan and supported results schema"
        )
    observations = result.get("cases")
    if not isinstance(observations, list):
        raise ValueError("Grader cases must be a list")
    expected = {case["id"]: case["checks"] for case in plan["cases"]}
    found: dict[str, dict[str, Any]] = {}
    for case in observations:
        case = _object(case, "Grader case")
        case_id = _text(case.get("id"), "Grader case id")
        if case_id not in expected or case_id in found:
            raise ValueError("Grader output contains an unexpected or duplicate case")
        checks = _object(case.get("checks"), "Grader checks")
        if any(name not in expected[case_id] for name in checks):
            raise ValueError("Grader output contains an unplanned check")
        found[case_id] = {}
        for name, observation in checks.items():
            observation = _object(observation, "Grader observation")
            status = observation.get("status")
            if status not in STATUSES:
                raise ValueError("Grader observation has an unsupported status")
            evidence = _text(observation.get("evidence"), "Observation evidence")
            found[case_id][name] = {"status": status, "evidence": redact_text(evidence)}
    return [
        {
            "id": case_id,
            "checks": {
                name: found.get(case_id, {}).get(
                    name,
                    {
                        "status": "not_checked",
                        "evidence": "No observation was recorded.",
                    },
                )
                for name in names
            },
        }
        for case_id, names in expected.items()
    ]


def create_evaluation_receipt(
    *,
    root: Path,
    plan_path: str | Path,
    agent_run: str | Path,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Bind observations from hashed agent stdout to a pre-existing evaluation plan."""
    return _build_receipt(
        root=root, plan_path=plan_path, agent_run=agent_run, created_at=created_at
    )


def _build_receipt(
    *,
    root: Path,
    plan_path: str | Path,
    agent_run: str | Path,
    created_at: str | None = None,
    stored_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    plan = _load_plan(root, plan_path)
    manifest_path = _path(root, agent_run)
    run = _read_json(manifest_path)
    if (
        run.get("kind") != "agilab.agent_run.v1"
        or type(run.get("schema_version")) is not int
        or run["schema_version"] != 1
    ):
        raise ValueError("Expected an AGILAB agent-run v1 manifest")
    status, returncode = run.get("status"), run.get("returncode")
    if (
        status not in ("pass", "fail", "timeout", "denied")
        or type(returncode) is not int
    ):
        raise ValueError(
            "The agent run must have a terminal status and integer return code"
        )
    if (status == "pass") != (returncode == 0):
        raise ValueError("Agent run status contradicts its return code")
    context = _object(run.get("context"), "Agent context")
    metadata = _object(context.get("metadata"), "Agent metadata")
    if metadata.get("skill_evaluation_plan_sha256") != plan["sha256"]:
        raise ValueError("Agent run metadata is not bound to this frozen plan")
    timing = _object(run.get("timing"), "Agent timing")
    started = _timestamp(timing.get("started_at"))
    finished = _timestamp(timing.get("finished_at"))
    if started < _timestamp(plan["created_at"]) or finished < started:
        raise ValueError("The agent run must start after the plan was frozen")
    command = _object(run.get("command"), "Agent command")
    argv_sha256 = _digest(command.get("argv_sha256"))
    artifact_map = _object(run.get("artifacts"), "Agent artifacts")
    if stored_artifacts is not None and set(stored_artifacts) != {"stdout", "stderr"}:
        raise ValueError("Receipt artifacts must contain exactly stdout and stderr")
    artifacts = {}
    for name in ("stdout", "stderr"):
        descriptor = _object(artifact_map.get(name), f"Agent {name}")
        path = (
            _check_file(root, stored_artifacts[name])
            if stored_artifacts is not None
            else _text(descriptor.get("path"), "Artifact path")
        )
        actual = _file(root, path)
        if actual["sha256"] != descriptor.get("sha256") or actual[
            "size_bytes"
        ] != descriptor.get("size_bytes"):
            raise ValueError(f"Agent {name} bytes no longer match the run manifest")
        artifacts[name] = actual
    observation_error = ""
    try:
        cases = _outcomes(plan, _read_json(_path(root, artifacts["stdout"]["path"])))
    except (ValueError, UnicodeError) as exc:
        observation_error = redact_text(str(exc))[:1000]
        cases = [
            {
                "id": case["id"],
                "checks": {
                    name: {
                        "status": "insufficient_evidence",
                        "evidence": "The grader output failed validation.",
                    }
                    for name in case["checks"]
                },
            }
            for case in plan["cases"]
        ]
    counts = dict.fromkeys(STATUSES, 0)
    for case in cases:
        for observation in case["checks"].values():
            counts[observation["status"]] += 1
    outcome = "passed"
    if status != "pass" or observation_error or counts["failed"]:
        outcome = "failed"
    elif counts["insufficient_evidence"]:
        outcome = "insufficient_evidence"
    elif counts["not_checked"]:
        outcome = "not_checked"
    return _seal(
        {
            "schema": RECEIPT_SCHEMA,
            "created_at": created_at or _now(),
            "producer": "python -m agilab.evidence.skill_evaluation record",
            "plan": _file(root, plan_path),
            "plan_sha256": plan["sha256"],
            "evaluator": plan["evaluator"],
            "agent_run": _file(root, manifest_path),
            "run": {
                "run_id": _text(run.get("run_id"), "Run id"),
                "status": status,
                "returncode": returncode,
                "argv_sha256": argv_sha256,
            },
            "artifacts": artifacts,
            "cases": cases,
            "summary": {
                "status": outcome,
                "case_count": len(cases),
                "check_count": sum(counts.values()),
                "checks": counts,
            },
            "observation_error": observation_error,
            "claim_scope": CLAIM_SCOPE,
        }
    )


def verify_evaluation_receipt(
    *, root: Path, receipt_path: str | Path
) -> dict[str, Any]:
    root = root.resolve()
    receipt = _read_json(_path(root, receipt_path))
    _check_seal(receipt, RECEIPT_SCHEMA)
    plan_path = _check_file(root, receipt.get("plan"))
    agent_run = _check_file(root, receipt.get("agent_run"))
    expected = _build_receipt(
        root=root,
        plan_path=plan_path,
        agent_run=agent_run,
        created_at=receipt["created_at"],
        stored_artifacts=_object(receipt.get("artifacts"), "Receipt artifacts"),
    )
    if receipt != expected:
        raise ValueError(
            "Receipt does not match the frozen plan and recorded agent output"
        )
    return {
        "verification": "passed",
        "evaluation_status": receipt["summary"]["status"],
        "receipt": _file(root, receipt_path),
        "summary": receipt["summary"],
        "claim_scope": CLAIM_SCOPE,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Declared root for all input and output paths",
    )
    commands = parser.add_subparsers(dest="action", required=True)
    plan_parser = commands.add_parser(
        "plan", help="Freeze inputs before running an evaluator"
    )
    for name in (
        "skill",
        "fixtures",
        "grader",
        "runtime",
        "runtime-version",
        "model",
        "output",
    ):
        plan_parser.add_argument(f"--{name}", required=True)
    plan_parser.add_argument(
        "--mode", choices=("deterministic_fixture", "native_agent"), required=True
    )
    record_parser = commands.add_parser(
        "record", help="Persist observations from an existing agent run"
    )
    for name in ("plan", "agent-run", "output"):
        record_parser.add_argument(f"--{name}", required=True)
    verify_parser = commands.add_parser(
        "verify", help="Recheck persisted observations and frozen inputs"
    )
    verify_parser.add_argument("receipt")
    args = parser.parse_args(argv)
    try:
        if args.action == "plan":
            payload = create_evaluation_plan(
                root=args.root,
                skill=args.skill,
                fixtures=args.fixtures,
                grader=args.grader,
                evaluator={
                    "mode": args.mode,
                    "runtime": args.runtime,
                    "runtime_version": args.runtime_version,
                    "model": args.model,
                },
            )
            reference = persist_evaluation(args.root, args.output, payload)
            print(
                json.dumps(
                    {"plan_sha256": payload["sha256"], "plan": reference},
                    sort_keys=True,
                )
            )
            return 0
        if args.action == "record":
            payload = create_evaluation_receipt(
                root=args.root, plan_path=args.plan, agent_run=args.agent_run
            )
            reference = persist_evaluation(args.root, args.output, payload)
            verified = verify_evaluation_receipt(
                root=args.root, receipt_path=args.output
            )
            print(json.dumps({**verified, "receipt": reference}, sort_keys=True))
            return 0 if payload["summary"]["status"] == "passed" else 1
        print(
            json.dumps(
                verify_evaluation_receipt(root=args.root, receipt_path=args.receipt),
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(
            json.dumps(
                {"verification": "failed", "error": redact_text(str(exc))[:1000]},
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
