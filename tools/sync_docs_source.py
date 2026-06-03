from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
import unicodedata


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT.parent / "thales_agilab" / "docs" / "source"
DEFAULT_TARGET = REPO_ROOT / "docs" / "source"
STAMP_FILE_NAME = ".docs_source_mirror_stamp.json"
STAMP_FORMAT_VERSION = 1
IGNORED_FILE_NAMES = {".DS_Store"}
IGNORED_DIR_NAMES = {"__pycache__", ".ipynb_checkpoints"}


@dataclass(frozen=True)
class SyncPlan:
    created: list[str]
    updated: list[str]
    deleted: list[str]

    def has_changes(self) -> bool:
        return bool(self.created or self.updated or self.deleted)


def _should_include(rel_path: Path) -> bool:
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


def build_mirror_stamp(source: Path, target: Path) -> dict[str, int | str]:
    source_state = _manifest_state(source)
    target_state = _manifest_state(target)
    return {
        "format_version": STAMP_FORMAT_VERSION,
        "managed_target": "docs/source",
        "source_hint": "../thales_agilab/docs/source",
        "source_digest_sha256": source_state["digest_sha256"],
        "target_digest_sha256": target_state["digest_sha256"],
        "file_count": target_state["file_count"],
        "sync_tool": "tools/sync_docs_source.py",
    }


def write_mirror_stamp(source: Path, target: Path) -> Path:
    stamp_path = stamp_path_for_target(target)
    stamp_path.write_text(
        json.dumps(build_mirror_stamp(source, target), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return stamp_path


def verify_mirror_stamp(target: Path) -> tuple[bool, str]:
    stamp_path = stamp_path_for_target(target)
    if not stamp_path.exists():
        return False, f"missing mirror stamp: {stamp_path}"

    try:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"invalid mirror stamp {stamp_path}: {exc}"

    if stamp.get("format_version") != STAMP_FORMAT_VERSION:
        return False, (
            f"unsupported mirror stamp format in {stamp_path}: "
            f"{stamp.get('format_version')!r}"
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

    return True, f"mirror stamp ok: {stamp_path}"


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
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check for drift without applying changes. This is the default mode.",
    )
    parser.add_argument(
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
    parser.add_argument(
        "--verify-stamp",
        action="store_true",
        help=(
            "Verify that the managed docs/source mirror stamp matches the current "
            "target tree. This does not require access to the canonical source tree."
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

    if args.verify_stamp:
        if not target.exists():
            parser.error(f"target directory not found: {target}")
        ok, message = verify_mirror_stamp(target)
        if not ok or not args.quiet:
            print(message)
        return 0 if ok else 1

    source = args.source.expanduser().resolve()
    if not source.exists():
        if args.skip_missing_source and not args.apply:
            if not args.quiet:
                print(f"canonical docs source not found; skipped mirror drift check: {source}")
            return 0
        parser.error(f"source directory not found: {source}")
    if not source.is_dir():
        parser.error(f"source path is not a directory: {source}")

    target.mkdir(parents=True, exist_ok=True)
    plan = make_sync_plan(source, target, delete_extra=args.delete)

    if plan.has_changes() or not args.quiet:
        print(render_plan(plan, source=source, target=target))

    if args.apply:
        apply_sync_plan(source, target, plan)
        write_mirror_stamp(source, target)
        return 0

    return 1 if plan.has_changes() else 0


if __name__ == "__main__":
    sys.exit(main())
