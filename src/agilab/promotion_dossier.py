"""Generate a deterministic AGILAB promotion handoff dossier."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
from typing import Any, Mapping, Sequence

from agilab import bridge_cli, evidence_contract, run_manifest, run_storyboard


SCHEMA = "agilab.promotion_dossier.v1"
DECISION_SCHEMA = "agilab.promotion_decision.v1"
EVIDENCE_MANIFEST_SCHEMA = "agilab.promotion_evidence_manifest.v1"
PROMOTION_DECISION_JSON = "promotion_decision.json"
PROMOTION_DOSSIER_MARKDOWN = "promotion_dossier.md"
EVIDENCE_MANIFEST_JSON = "evidence_manifest.json"
POLICY_RESULTS_JSON = "policy_results.json"
LINEAGE_JSON = "lineage.json"
MLFLOW_EXPORT_JSON = "mlflow_export.json"
REPLAY_SCRIPT = "replay.sh"


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_text(path: Path, text: str, *, executable: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | 0o111)
    return path


def _file_row(path: Path, *, id_: str, kind: str) -> dict[str, Any]:
    exists = path.exists()
    row: dict[str, Any] = {
        "id": id_,
        "kind": kind,
        "path": str(path),
        "exists": exists,
    }
    if exists and path.is_file():
        row["size_bytes"] = path.stat().st_size
        row["sha256"] = evidence_contract.sha256_file(path)
    return row


def _failed_items(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    return [
        str(row.get("id", row.get("label", "")))
        for row in rows
        if str(row.get("status", "unknown")) not in {"pass", "ok"}
    ]


def _decision(
    manifest: run_manifest.RunManifest,
    policy_results: Mapping[str, Any],
    verification: Mapping[str, Any],
) -> dict[str, Any]:
    failed_policy_rules = _failed_items(
        [row for row in policy_results.get("rules", []) if isinstance(row, Mapping)]
    )
    failed_verification_checks = _failed_items(
        [row for row in verification.get("checks", []) if isinstance(row, Mapping)]
    )
    blockers = sorted(set(failed_policy_rules or failed_verification_checks))
    if manifest.status == "pass" and policy_results.get("status") == "pass":
        decision = "promote"
        reason = "policy_passed"
    elif manifest.status == "fail" or blockers:
        decision = "block"
        reason = "policy_failed" if blockers else "manifest_failed"
    else:
        decision = "manual-review"
        reason = "insufficient_evidence"
    return {
        "schema": DECISION_SCHEMA,
        "decision": decision,
        "reason": reason,
        "status": "pass" if decision == "promote" else "fail",
        "run_id": manifest.run_id,
        "path_id": manifest.path_id,
        "label": manifest.label,
        "app_name": manifest.environment.app_name,
        "manifest_status": manifest.status,
        "policy_status": str(policy_results.get("status", "unknown")),
        "verification_status": str(verification.get("status", "unknown")),
        "blockers": blockers,
        "next_action": _next_action(decision, blockers),
        "created_at": run_manifest.utc_now(),
    }


def _next_action(decision: str, blockers: Sequence[str]) -> str:
    if decision == "promote":
        return "Hand off the dossier with the candidate artifact to the target MLOps or review stack."
    if blockers:
        return "Fix the blocking evidence checks, rerun the AGILAB proof, then regenerate the dossier."
    return "Ask an operator to review the dossier because the policy did not produce a clear pass/fail result."


def _replay_script(manifest: run_manifest.RunManifest) -> str:
    command = " ".join(shlex.quote(str(part)) for part in manifest.command.argv)
    cwd = shlex.quote(manifest.command.cwd or ".")
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f"cd {cwd}",
            command,
            "",
        ]
    )


def _render_markdown(
    *,
    decision: Mapping[str, Any],
    story: Mapping[str, Any],
    policy_results: Mapping[str, Any],
    files: Sequence[Mapping[str, Any]],
) -> str:
    story_summary = dict(story.get("story", {}))
    lines = [
        f"# Promotion dossier: {decision.get('label', 'AGILAB run')}",
        "",
        "## Decision",
        "",
        f"- Decision: `{decision.get('decision', 'manual-review')}`",
        f"- Reason: `{decision.get('reason', '')}`",
        f"- Next action: {decision.get('next_action', '')}",
        "",
        "## Run Summary",
        "",
        f"- App: `{decision.get('app_name', '')}`",
        f"- Run ID: `{decision.get('run_id', '')}`",
        f"- Path ID: `{decision.get('path_id', '')}`",
        f"- Duration: `{story_summary.get('duration_seconds', 0.0)}` seconds",
        f"- Artifact count: `{story_summary.get('artifact_count', 0)}`",
        "",
        "## Policy Results",
        "",
    ]
    rules = [row for row in policy_results.get("rules", []) if isinstance(row, Mapping)]
    if rules:
        lines.extend(
            f"- `{row.get('status', 'unknown')}` {row.get('id', '')}: {row.get('summary', '')}"
            for row in rules
        )
    else:
        lines.append("- No policy rules were recorded.")

    lines.extend(["", "## Dossier Files", ""])
    lines.extend(
        f"- `{row.get('id', '')}`: `{row.get('path', '')}`"
        for row in files
        if row.get("exists")
    )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This dossier is a deterministic handoff artifact. It does not deploy, serve, or certify a model by itself.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def build_promotion_dossier(
    manifest_path: Path,
    output_dir: Path | None = None,
    *,
    policy_path: Path | None = None,
) -> dict[str, Any]:
    """Build and write a promotion dossier for one AGILAB run manifest."""

    resolved_manifest_path = manifest_path.expanduser().resolve(strict=False)
    manifest = run_manifest.load_run_manifest(resolved_manifest_path)
    target_dir = output_dir.expanduser() if output_dir else resolved_manifest_path.parent / "promotion_dossier"
    target_dir.mkdir(parents=True, exist_ok=True)

    verification = evidence_contract.verify_manifest(resolved_manifest_path)
    policy_results = evidence_contract.evaluate_policy(
        manifest,
        resolved_manifest_path,
        policy_path=policy_path,
    )
    story = run_storyboard.build_run_story(resolved_manifest_path)
    decision = _decision(manifest, policy_results, verification)
    lineage = evidence_contract.build_openlineage_event(manifest, resolved_manifest_path)

    paths = {
        "promotion_decision": target_dir / PROMOTION_DECISION_JSON,
        "policy_results": target_dir / POLICY_RESULTS_JSON,
        "lineage": target_dir / LINEAGE_JSON,
        "mlflow_export": target_dir / MLFLOW_EXPORT_JSON,
        "run_story_json": target_dir / run_storyboard.RUN_STORY_JSON,
        "run_story_markdown": target_dir / run_storyboard.RUN_STORY_MARKDOWN,
        "replay": target_dir / REPLAY_SCRIPT,
        "promotion_dossier": target_dir / PROMOTION_DOSSIER_MARKDOWN,
        "evidence_manifest": target_dir / EVIDENCE_MANIFEST_JSON,
    }

    _write_json(paths["promotion_decision"], decision)
    _write_json(paths["policy_results"], policy_results)
    _write_json(paths["lineage"], lineage)
    bridge_cli.export_mlflow_handoff(resolved_manifest_path, paths["mlflow_export"])
    _write_json(paths["run_story_json"], story)
    _write_text(paths["run_story_markdown"], run_storyboard.render_markdown(story))
    _write_text(paths["replay"], _replay_script(manifest), executable=True)

    dossier_file_rows = [
        _file_row(paths["promotion_decision"], id_="promotion_decision", kind="decision"),
        _file_row(paths["policy_results"], id_="policy_results", kind="policy"),
        _file_row(paths["lineage"], id_="lineage", kind="openlineage"),
        _file_row(paths["mlflow_export"], id_="mlflow_export", kind="mlflow"),
        _file_row(paths["run_story_json"], id_="run_story_json", kind="story-json"),
        _file_row(paths["run_story_markdown"], id_="run_story_markdown", kind="story-markdown"),
        _file_row(paths["replay"], id_="replay", kind="script"),
    ]
    _write_text(
        paths["promotion_dossier"],
        _render_markdown(
            decision=decision,
            story=story,
            policy_results=policy_results,
            files=dossier_file_rows,
        ),
    )
    dossier_file_rows.append(
        _file_row(paths["promotion_dossier"], id_="promotion_dossier", kind="markdown")
    )
    evidence_manifest = {
        "schema": EVIDENCE_MANIFEST_SCHEMA,
        "status": decision["status"],
        "decision": decision["decision"],
        "manifest_path": str(resolved_manifest_path),
        "manifest_sha256": evidence_contract.sha256_file(resolved_manifest_path),
        "policy_path": str(policy_path.expanduser()) if policy_path else "",
        "source_artifacts": story["artifacts"],
        "dossier_files": dossier_file_rows,
    }
    _write_json(paths["evidence_manifest"], evidence_manifest)
    dossier_file_rows.append(
        _file_row(paths["evidence_manifest"], id_="evidence_manifest", kind="manifest")
    )

    return {
        "schema": SCHEMA,
        "status": decision["status"],
        "decision": decision["decision"],
        "reason": decision["reason"],
        "manifest_path": str(resolved_manifest_path),
        "output_dir": str(target_dir),
        "paths": {key: str(path) for key, path in sorted(paths.items())},
        "blockers": decision["blockers"],
        "next_action": decision["next_action"],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a production-handoff promotion dossier from run_manifest.json."
    )
    parser.add_argument(
        "manifest",
        nargs="?",
        help="Path to run_manifest.json. Defaults to the first-proof manifest location.",
    )
    parser.add_argument("--output-dir", help="Directory for the dossier files.")
    parser.add_argument("--policy", help="Optional JSON/TOML policy file.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero unless the decision is promote.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    manifest_path = Path(args.manifest).expanduser() if args.manifest else run_storyboard.DEFAULT_MANIFEST_PATH.expanduser()
    payload = build_promotion_dossier(
        manifest_path,
        Path(args.output_dir).expanduser() if args.output_dir else None,
        policy_path=Path(args.policy).expanduser() if args.policy else None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"promotion dossier: {payload['decision']} ({payload['reason']})")
        print(f"output_dir: {payload['output_dir']}")
    return 1 if args.strict and payload["decision"] != "promote" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
