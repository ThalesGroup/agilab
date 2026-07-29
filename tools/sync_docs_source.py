from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT.parent / "thales_agilab" / "docs" / "source"
DEFAULT_TARGET = REPO_ROOT / "docs" / "source"
DOCS_SOURCE_ENV = "AGILAB_DOCS_SOURCE"
STAMP_FILE_NAME = ".docs_source_mirror_stamp.json"
STAMP_FORMAT_VERSION = 2
STAMP_MANAGED_TARGET = "docs/source"
STAMP_SOURCE_HINT = "../thales_agilab/docs/source"
STAMP_SYNC_TOOL = "tools/sync_docs_source.py"
IGNORED_FILE_NAMES = {".DS_Store"}
IGNORED_DIR_NAMES = {"__pycache__", ".ipynb_checkpoints"}
PUBLIC_OWNED_EXCLUSIONS = frozenset(
    {
        "data/release_proof.toml",
        "data/ui_robot_evidence.json",
        "release-proof.rst",
    }
)
CANONICAL_DRIFT_NOT_CHECKED = (
    "canonical docs source unavailable; target integrity only; "
    "canonical drift NOT CHECKED"
)


@dataclass(frozen=True)
class SyncPlan:
    created: list[str]
    updated: list[str]
    deleted: list[str]

    def has_changes(self) -> bool:
        return bool(self.created or self.updated or self.deleted)


def _should_include(rel_path: Path) -> bool:
    if _normalized_rel_path(rel_path) in PUBLIC_OWNED_EXCLUSIONS:
        return False
    return not any(
        part in IGNORED_DIR_NAMES or part in IGNORED_FILE_NAMES
        for part in rel_path.parts
    )


def _normalized_rel_path(rel_path: Path) -> str:
    return unicodedata.normalize("NFC", rel_path.as_posix())


def build_manifest(root: Path) -> dict[str, Path]:
    manifest: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(root)
        if not _should_include(rel_path):
            continue
        manifest[_normalized_rel_path(rel_path)] = path
    return manifest


def _same_file_content(left: Path, right: Path) -> bool:
    if left.stat().st_size != right.stat().st_size:
        return False
    return left.read_bytes() == right.read_bytes()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_state(root: Path) -> dict[str, int | str]:
    manifest = build_manifest(root)
    digest = hashlib.sha256()
    for rel_path, path in sorted(manifest.items()):
        file_hash = _file_sha256(path)
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return {
        "file_count": len(manifest),
        "digest_sha256": digest.hexdigest(),
    }


def stamp_path_for_target(target: Path) -> Path:
    return target.parent / STAMP_FILE_NAME


def configured_canonical_source() -> Path:
    configured = os.environ.get(DOCS_SOURCE_ENV)
    return Path(configured).expanduser() if configured else DEFAULT_SOURCE


def _stamp_payload(
    target: Path,
    *,
    source_status: str,
    source_digest_sha256: str | None,
) -> dict[str, object]:
    target_state = _manifest_state(target)
    return {
        "format_version": STAMP_FORMAT_VERSION,
        "managed_target": STAMP_MANAGED_TARGET,
        "public_owned_exclusions": sorted(PUBLIC_OWNED_EXCLUSIONS),
        "source_hint": STAMP_SOURCE_HINT,
        "source_status": source_status,
        "source_digest_sha256": source_digest_sha256,
        "target_digest_sha256": target_state["digest_sha256"],
        "file_count": target_state["file_count"],
        "sync_tool": STAMP_SYNC_TOOL,
    }


def build_mirror_stamp(source: Path, target: Path) -> dict[str, object]:
    if not source.is_dir():
        raise ValueError(f"canonical source is not a directory: {source}")
    if not target.is_dir():
        raise ValueError(f"mirror target is not a directory: {target}")
    if source.resolve() == target.resolve():
        raise ValueError(
            "canonical source and mirror target resolve to the same directory; "
            "refusing to manufacture canonical mirror evidence"
        )

    source_state = _manifest_state(source)
    target_state = _manifest_state(target)
    if source_state != target_state:
        raise ValueError(
            "canonical source and managed mirror target differ; apply the complete "
            "sync plan before writing verified mirror evidence"
        )
    return _stamp_payload(
        target,
        source_status="verified",
        source_digest_sha256=str(source_state["digest_sha256"]),
    )


def build_target_only_mirror_stamp(target: Path) -> dict[str, object]:
    if not target.is_dir():
        raise ValueError(f"mirror target is not a directory: {target}")
    return _stamp_payload(
        target,
        source_status="unavailable",
        source_digest_sha256=None,
    )


def write_mirror_stamp(source: Path, target: Path) -> Path:
    stamp_path = stamp_path_for_target(target)
    stamp_path.write_text(
        json.dumps(build_mirror_stamp(source, target), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return stamp_path


def write_target_only_mirror_stamp(target: Path) -> Path:
    stamp_path = stamp_path_for_target(target)
    stamp_path.write_text(
        json.dumps(build_target_only_mirror_stamp(target), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return stamp_path


def verify_mirror_stamp(
    target: Path,
    source: Path | None = None,
    *,
    skip_missing_source: bool = False,
) -> tuple[bool, str]:
    stamp_path = stamp_path_for_target(target)
    if not stamp_path.exists():
        return False, f"missing mirror stamp: {stamp_path}"

    try:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"invalid mirror stamp {stamp_path}: {exc}"

    if not isinstance(stamp, dict):
        return False, f"invalid mirror stamp {stamp_path}: expected a JSON object"

    if stamp.get("format_version") != STAMP_FORMAT_VERSION:
        return False, (
            f"unsupported mirror stamp format in {stamp_path}: "
            f"{stamp.get('format_version')!r}; regenerate with "
            "`python tools/sync_docs_source.py --apply --delete` when the "
            "canonical source is available, or "
            "`python tools/sync_docs_source.py --write-target-only-stamp` "
            "for explicit target-only evidence"
        )

    expected_identity = {
        "managed_target": STAMP_MANAGED_TARGET,
        "source_hint": STAMP_SOURCE_HINT,
        "sync_tool": STAMP_SYNC_TOOL,
    }
    for field, expected in expected_identity.items():
        if stamp.get(field) != expected:
            return False, (
                f"mirror stamp {field} mismatch in {stamp_path}: expected "
                f"{expected!r}, got {stamp.get(field)!r}"
            )

    expected_exclusions = sorted(PUBLIC_OWNED_EXCLUSIONS)
    if stamp.get("public_owned_exclusions") != expected_exclusions:
        return False, (
            f"mirror stamp exclusions mismatch in {stamp_path}: expected "
            f"{expected_exclusions!r}, got {stamp.get('public_owned_exclusions')!r}"
        )

    source_status = stamp.get("source_status")
    source_digest = stamp.get("source_digest_sha256")
    if source_status not in {"verified", "unavailable"}:
        return False, (
            f"invalid source_status in {stamp_path}: {source_status!r}"
        )
    if source_status == "verified":
        if not isinstance(source_digest, str) or not source_digest:
            return False, f"verified mirror stamp has no source digest: {stamp_path}"
        if source_digest != stamp.get("target_digest_sha256"):
            return False, (
                f"verified mirror stamp records unequal source and target digests: "
                f"{stamp_path}"
            )
    elif source_digest is not None:
        return False, (
            f"unavailable-source mirror stamp must use a null source digest: {stamp_path}"
        )

    state = _manifest_state(target)
    if stamp.get("file_count") != state["file_count"]:
        return False, (
            f"mirror stamp mismatch for {target}: expected file_count "
            f"{stamp.get('file_count')}, got {state['file_count']}"
        )
    if stamp.get("target_digest_sha256") != state["digest_sha256"]:
        return False, (
            f"mirror stamp mismatch for {target}: expected digest "
            f"{stamp.get('target_digest_sha256')}, got {state['digest_sha256']}"
        )

    if source is None:
        if not skip_missing_source:
            return False, (
                "canonical docs source was not supplied; rerun with a canonical "
                "--source or explicitly allow --skip-missing-source"
            )
        return True, f"{CANONICAL_DRIFT_NOT_CHECKED}: source path not supplied"

    if not source.exists():
        if not skip_missing_source:
            return False, (
                f"canonical docs source not found: {source}; rerun with "
                "--skip-missing-source only when target-only integrity is intended"
            )
        return True, f"{CANONICAL_DRIFT_NOT_CHECKED}: {source}"
    if not source.is_dir():
        return False, f"canonical docs source is not a directory: {source}"
    if source.resolve() == target.resolve():
        return False, (
            "canonical source and mirror target resolve to the same directory; "
            "canonical drift cannot be verified"
        )

    source_state = _manifest_state(source)
    if source_status == "unavailable":
        if source_state != state:
            return False, (
                f"canonical source drift for {source}: current managed state "
                "does not match the target-only stamped mirror"
            )
        return True, (
            "mirror target integrity ok; canonical source currently matches the "
            "managed target, but the stored stamp remains source_status=unavailable"
        )

    if source_state["digest_sha256"] != source_digest:
        return False, (
            f"canonical source drift for {source}: stamp expected digest "
            f"{source_digest}, got {source_state['digest_sha256']}"
        )
    if source_state["file_count"] != stamp.get("file_count"):
        return False, (
            f"canonical source drift for {source}: stamp expected file_count "
            f"{stamp.get('file_count')}, got {source_state['file_count']}"
        )

    return True, f"mirror stamp ok: {stamp_path}; canonical source verified: {source}"


def verify_target_mirror_integrity(target: Path) -> tuple[bool, str]:
    """Verify only the checked-in public mirror and its stamped identity."""
    ok, message = verify_mirror_stamp(
        target,
        source=None,
        skip_missing_source=True,
    )
    if ok:
        return True, f"checked-in docs mirror target integrity verified: {target}"
    return False, message


def verify_canonical_mirror_alignment(
    target: Path,
    source: Path,
) -> tuple[str, str]:
    """Return pass, fail, or skipped for live canonical-to-public alignment."""
    if not source.exists():
        return "skipped", f"{CANONICAL_DRIFT_NOT_CHECKED}: {source}"
    ok, message = verify_mirror_stamp(
        target,
        source,
        skip_missing_source=False,
    )
    return ("pass" if ok else "fail"), message


def make_sync_plan(source: Path, target: Path, *, delete_extra: bool) -> SyncPlan:
    source_manifest = build_manifest(source)
    target_manifest = build_manifest(target) if target.exists() else {}

    created = sorted(path for path in source_manifest if path not in target_manifest)
    updated = sorted(
        path
        for path in source_manifest
        if path in target_manifest
        and not _same_file_content(source_manifest[path], target_manifest[path])
    )
    deleted = sorted(
        path for path in target_manifest if path not in source_manifest
    ) if delete_extra else []
    return SyncPlan(created=created, updated=updated, deleted=deleted)


def apply_sync_plan(source: Path, target: Path, plan: SyncPlan) -> None:
    for rel_path in plan.created + plan.updated:
        src = source / rel_path
        dst = target / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    for rel_path in plan.deleted:
        dst = target / rel_path
        dst.unlink(missing_ok=True)
        parent = dst.parent
        while parent != target and parent.exists():
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


def render_plan(plan: SyncPlan, *, source: Path, target: Path) -> str:
    lines = [
        f"source: {source}",
        f"target: {target}",
        f"create: {len(plan.created)}",
        f"update: {len(plan.updated)}",
        f"delete: {len(plan.deleted)}",
    ]
    for label, items in (
        ("create", plan.created),
        ("update", plan.updated),
        ("delete", plan.deleted),
    ):
        for item in items:
            lines.append(f"{label}: {item}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sync the public docs/source mirror in agilab from the canonical "
            "thales_agilab/docs/source tree."
        )
    )
    parser.add_argument("--source", type=Path, default=configured_canonical_source())
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Check for drift without applying changes. This is the default mode.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Copy created/updated files into the target mirror.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete files from the target mirror when they no longer exist in the source tree.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the sync summary output when nothing changes.",
    )
    mode.add_argument(
        "--verify-stamp",
        action="store_true",
        help=(
            "Verify target integrity and canonical-source drift. Use "
            "--skip-missing-source to explicitly accept target-only verification."
        ),
    )
    mode.add_argument(
        "--write-target-only-stamp",
        action="store_true",
        help=(
            "Write target-integrity evidence with source_status=unavailable. "
            "This never claims that the canonical source was checked."
        ),
    )
    parser.add_argument(
        "--skip-missing-source",
        action="store_true",
        help=(
            "When the canonical source checkout is absent, skip source-to-target "
            "drift checks instead of failing. This is intended for local hooks "
            "and public CI jobs that should enforce the comparison only when "
            "the sibling docs checkout is available."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    target = args.target.expanduser().resolve()

    if args.write_target_only_stamp:
        if not target.exists():
            parser.error(f"target directory not found: {target}")
        if not target.is_dir():
            parser.error(f"target path is not a directory: {target}")
        try:
            stamp_path = write_target_only_mirror_stamp(target)
        except ValueError as exc:
            print(f"mirror stamp not written: {exc}", file=sys.stderr)
            return 1
        if not args.quiet:
            print(
                f"target-only mirror stamp written: {stamp_path}; "
                "canonical drift NOT CHECKED"
            )
        return 0

    if args.verify_stamp:
        if not target.exists():
            parser.error(f"target directory not found: {target}")
        source = args.source.expanduser().resolve()
        ok, message = verify_mirror_stamp(
            target,
            source,
            skip_missing_source=args.skip_missing_source,
        )
        if not ok or not args.quiet or "canonical drift NOT CHECKED" in message:
            print(message)
        return 0 if ok else 1

    source = args.source.expanduser().resolve()
    if not source.exists():
        if args.skip_missing_source and not args.apply:
            if not target.exists():
                parser.error(f"target directory not found: {target}")
            ok, message = verify_mirror_stamp(
                target,
                source,
                skip_missing_source=True,
            )
            print(message)
            return 0 if ok else 1
        parser.error(f"source directory not found: {source}")
    if not source.is_dir():
        parser.error(f"source path is not a directory: {source}")

    target.mkdir(parents=True, exist_ok=True)
    plan = make_sync_plan(source, target, delete_extra=args.delete)

    if plan.has_changes() or not args.quiet:
        print(render_plan(plan, source=source, target=target))

    if args.apply:
        apply_sync_plan(source, target, plan)
        try:
            write_mirror_stamp(source, target)
        except ValueError as exc:
            print(f"mirror stamp not written: {exc}", file=sys.stderr)
            return 1
        return 0

    return 1 if plan.has_changes() else 0


if __name__ == "__main__":
    sys.exit(main())
