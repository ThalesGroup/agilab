"""Build a shareable one-run story from an AGILAB run manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
from typing import Any, Mapping, Sequence

from agilab import run_manifest


SCHEMA = "agilab.run_storyboard.v1"
RUN_STORY_JSON = "run_story.json"
RUN_STORY_MARKDOWN = "run_story.md"
DEFAULT_MANIFEST_PATH = Path("~/log/execute/flight_telemetry/run_manifest.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_artifact_path(path: str, manifest_path: Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    return (manifest_path.parent / candidate).resolve(strict=False)


def _command_text(argv: Sequence[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in argv)


def _validation_rows(manifest: run_manifest.RunManifest) -> list[dict[str, Any]]:
    return [
        {
            "label": validation.label,
            "status": validation.status,
            "summary": validation.summary,
        }
        for validation in manifest.validations
    ]


def _artifact_rows(
    manifest: run_manifest.RunManifest,
    manifest_path: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for artifact in manifest.artifacts:
        path = _resolve_artifact_path(artifact.path, manifest_path)
        exists = path.exists()
        row: dict[str, Any] = {
            "name": artifact.name,
            "kind": artifact.kind,
            "path": str(path),
            "exists": exists,
            "size_bytes": path.stat().st_size if exists and path.is_file() else artifact.size_bytes,
        }
        if exists and path.is_file():
            row["sha256"] = _sha256(path)
        rows.append(row)
    return rows


def _headline(manifest: run_manifest.RunManifest) -> str:
    if run_manifest.manifest_passed(manifest):
        return f"{manifest.label} passed for {manifest.environment.app_name}."
    if manifest.status == "fail":
        return f"{manifest.label} failed for {manifest.environment.app_name}."
    return f"{manifest.label} finished with unknown status for {manifest.environment.app_name}."


def _next_actions(
    manifest: run_manifest.RunManifest,
    artifact_rows: Sequence[Mapping[str, Any]],
) -> list[str]:
    missing_artifacts = [row["name"] for row in artifact_rows if not row.get("exists")]
    failing_validations = [
        validation.label
        for validation in manifest.validations
        if validation.status not in {"pass", "ok"}
    ]
    if missing_artifacts:
        return [
            "Regenerate missing artifacts before sharing the run.",
            "Missing artifacts: " + ", ".join(sorted(str(item) for item in missing_artifacts)),
        ]
    if failing_validations:
        return [
            "Fix or rerun the failing validation step before promoting the evidence.",
            "Failing validations: " + ", ".join(sorted(failing_validations)),
        ]
    if run_manifest.manifest_passed(manifest):
        return [
            "Share run_story.md with reviewers as the human-readable run summary.",
            "Attach run_story.json when a downstream tool needs structured evidence.",
            "Run `agilab prove <run_manifest.json>` when a portable proof pack is required.",
        ]
    return ["Rerun the manifest-producing command until the status is pass or fail."]


def build_run_story(manifest_path: Path) -> dict[str, Any]:
    """Return a deterministic story payload for ``manifest_path``."""

    resolved_manifest_path = manifest_path.expanduser().resolve(strict=False)
    manifest = run_manifest.load_run_manifest(resolved_manifest_path)
    artifacts = _artifact_rows(manifest, resolved_manifest_path)
    validations = _validation_rows(manifest)
    summary = run_manifest.manifest_summary(manifest)
    argv = list(manifest.command.argv)
    return {
        "schema": SCHEMA,
        "status": manifest.status,
        "manifest_path": str(resolved_manifest_path),
        "story": {
            "headline": _headline(manifest),
            "run_id": manifest.run_id,
            "path_id": manifest.path_id,
            "label": manifest.label,
            "app_name": manifest.environment.app_name,
            "duration_seconds": manifest.timing.duration_seconds,
            "target_seconds": manifest.timing.target_seconds,
            "artifact_count": summary["artifact_count"],
            "validation_count": len(validations),
        },
        "command": {
            "label": manifest.command.label,
            "argv": argv,
            "text": _command_text(argv),
            "cwd": manifest.command.cwd,
            "env_override_keys": sorted(manifest.command.env_overrides),
        },
        "environment": {
            "python_version": manifest.environment.python_version,
            "platform": manifest.environment.platform,
            "repo_root": manifest.environment.repo_root,
            "active_app": manifest.environment.active_app,
        },
        "validations": validations,
        "artifacts": artifacts,
        "next_actions": _next_actions(manifest, artifacts),
        "provenance": {
            "source": "run_manifest",
            "source_schema": run_manifest.MANIFEST_KIND,
            "source_schema_version": run_manifest.SCHEMA_VERSION,
            "executes_commands": False,
            "executes_network_probe": False,
            "safe_for_public_evidence": True,
        },
    }


def render_markdown(story: Mapping[str, Any]) -> str:
    """Render ``story`` as a compact Markdown run storyboard."""

    story_summary = dict(story.get("story", {}))
    command = dict(story.get("command", {}))
    environment = dict(story.get("environment", {}))
    validations = [row for row in story.get("validations", []) if isinstance(row, Mapping)]
    artifacts = [row for row in story.get("artifacts", []) if isinstance(row, Mapping)]
    next_actions = [str(action) for action in story.get("next_actions", [])]

    lines = [
        f"# {story_summary.get('headline', 'AGILAB run story')}",
        "",
        "## Run",
        "",
        f"- Status: `{story.get('status', 'unknown')}`",
        f"- Run ID: `{story_summary.get('run_id', '')}`",
        f"- Path: `{story_summary.get('path_id', '')}`",
        f"- App: `{story_summary.get('app_name', '')}`",
        f"- Duration: `{story_summary.get('duration_seconds', 0.0)}` seconds",
        "",
        "## Command",
        "",
        f"- Label: `{command.get('label', '')}`",
        f"- CWD: `{command.get('cwd', '')}`",
        "",
        "```bash",
        str(command.get("text", "")),
        "```",
        "",
        "## Environment",
        "",
        f"- Python: `{environment.get('python_version', '')}`",
        f"- Platform: `{environment.get('platform', '')}`",
        f"- Active app: `{environment.get('active_app', '')}`",
        "",
        "## Validations",
        "",
    ]
    if validations:
        lines.extend(
            f"- `{row.get('status', 'unknown')}` {row.get('label', '')}: {row.get('summary', '')}"
            for row in validations
        )
    else:
        lines.append("- No validation rows were recorded.")

    lines.extend(["", "## Artifacts", ""])
    if artifacts:
        lines.extend(
            (
                f"- `{row.get('name', '')}`: "
                f"{'present' if row.get('exists') else 'missing'} "
                f"at `{row.get('path', '')}`"
            )
            for row in artifacts
        )
    else:
        lines.append("- No artifacts were recorded.")

    lines.extend(["", "## Next Actions", ""])
    if next_actions:
        lines.extend(f"- {action}" for action in next_actions)
    else:
        lines.append("- No next action was generated.")

    return "\n".join(lines).rstrip() + "\n"


def write_run_storyboard(
    manifest_path: Path,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Write JSON and Markdown story files and return their paths."""

    resolved_manifest_path = manifest_path.expanduser().resolve(strict=False)
    story = build_run_story(resolved_manifest_path)
    target_dir = output_dir.expanduser() if output_dir else resolved_manifest_path.parent / "run_story"
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / RUN_STORY_JSON
    markdown_path = target_dir / RUN_STORY_MARKDOWN
    json_path.write_text(json.dumps(story, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(story), encoding="utf-8")
    return {
        "schema": "agilab.run_storyboard.paths.v1",
        "status": story["status"],
        "manifest_path": str(resolved_manifest_path),
        "output_dir": str(target_dir),
        "paths": {
            "json": str(json_path),
            "markdown": str(markdown_path),
        },
        "story": story["story"],
        "next_actions": story["next_actions"],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a shareable AGILAB run storyboard from run_manifest.json."
    )
    parser.add_argument(
        "manifest",
        nargs="?",
        help="Path to run_manifest.json. Defaults to the first-proof manifest location.",
    )
    parser.add_argument("--output-dir", help="Directory for run_story.json and run_story.md.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when the run did not pass.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    manifest_path = Path(args.manifest).expanduser() if args.manifest else DEFAULT_MANIFEST_PATH.expanduser()
    payload = write_run_storyboard(
        manifest_path,
        Path(args.output_dir).expanduser() if args.output_dir else None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"run story: {payload['status']}")
        print(f"markdown: {payload['paths']['markdown']}")
        print(f"json: {payload['paths']['json']}")
    return 1 if args.strict and payload["status"] != "pass" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
