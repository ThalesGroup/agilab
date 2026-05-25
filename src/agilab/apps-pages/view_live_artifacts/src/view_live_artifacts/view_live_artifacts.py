# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import streamlit as st
from agi_pages.runtime import ensure_repo_on_path as _page_ensure_repo_on_path
from agi_pages.runtime import relative_label, resolve_active_app_path


PAGE_KEY = "view_live_artifacts"
DEFAULT_PATTERNS = (
    "**/live_state.json",
    "**/analysis_manifest.json",
    "**/run_manifest.json",
    "**/manifest_index.json",
    "**/*.json",
    "**/*.jsonl",
    "**/*.ndjson",
    "**/*.csv",
    "**/*.log",
    "**/*.txt",
    "**/*.png",
    "**/*.jpg",
    "**/*.jpeg",
    "**/*.webp",
    "**/*.parquet",
)
MANIFEST_NAMES = {
    "analysis_manifest.json",
    "live_state.json",
    "manifest_index.json",
    "run_manifest.json",
}
TEXT_SUFFIXES = {".csv", ".jsonl", ".log", ".md", ".ndjson", ".txt", ".yaml", ".yml"}
JSON_SUFFIXES = {".json"}
IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
PREVIEW_BYTES = 64 * 1024
MAX_JSON_PREVIEW_BYTES = 512 * 1024
MAX_DISCOVERED_FILES = 500
REFRESH_INTERVAL_SECONDS = (1, 2, 5, 10, 30, 60)


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    path: Path
    relative_path: str
    size: int
    mtime_ns: int
    mtime_iso: str
    kind: str
    is_manifest: bool = False

    def as_row(self) -> dict[str, Any]:
        return {
            "path": self.relative_path,
            "kind": self.kind,
            "size": format_bytes(self.size),
            "updated_utc": self.mtime_iso,
            "manifest": "yes" if self.is_manifest else "",
        }


@dataclass(frozen=True, slots=True)
class ArtifactPreview:
    kind: str
    value: Any
    truncated: bool = False
    error: str = ""


def _ensure_repo_on_path() -> None:
    _page_ensure_repo_on_path(__file__)


_ensure_repo_on_path()

from agi_env import AgiEnv
from agi_gui.pagelib import render_logo


def parse_patterns(raw_value: str | Iterable[str] | None) -> tuple[str, ...]:
    if raw_value is None:
        return DEFAULT_PATTERNS
    if isinstance(raw_value, str):
        raw_items = raw_value.replace(";", ",").replace("\n", ",").split(",")
    else:
        raw_items = [str(item) for item in raw_value]

    patterns: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        pattern = item.strip()
        if not pattern or pattern in seen:
            continue
        seen.add(pattern)
        patterns.append(pattern)
    return tuple(patterns) or DEFAULT_PATTERNS


def format_patterns(patterns: Iterable[str]) -> str:
    return ", ".join(parse_patterns(patterns))


def format_bytes(size: int | float | None) -> str:
    try:
        value = float(size or 0)
    except (TypeError, ValueError):
        value = 0.0
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _kind_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if path.name in MANIFEST_NAMES:
        return "manifest"
    if suffix in JSON_SUFFIXES:
        return "json"
    if suffix in TEXT_SUFFIXES:
        return "text"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix == ".parquet":
        return "parquet"
    return "binary"


def _mtime_iso(mtime_ns: int) -> str:
    return datetime.fromtimestamp(mtime_ns / 1_000_000_000, tz=UTC).replace(microsecond=0).isoformat()


def discover_artifacts(root: Path, patterns: Iterable[str], *, limit: int = MAX_DISCOVERED_FILES) -> tuple[ArtifactRecord, ...]:
    if limit <= 0:
        return ()
    try:
        root_path = Path(root).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return ()
    if not root_path.exists() or not root_path.is_dir():
        return ()

    found: dict[Path, ArtifactRecord] = {}
    for pattern in parse_patterns(patterns):
        try:
            candidates = root_path.glob(pattern)
            for candidate in candidates:
                try:
                    resolved = candidate.resolve(strict=False)
                    if resolved in found or not resolved.is_file():
                        continue
                    stat = resolved.stat()
                except (OSError, RuntimeError, TypeError, ValueError):
                    continue
                found[resolved] = ArtifactRecord(
                    path=resolved,
                    relative_path=relative_label(resolved, root_path),
                    size=int(stat.st_size),
                    mtime_ns=int(stat.st_mtime_ns),
                    mtime_iso=_mtime_iso(int(stat.st_mtime_ns)),
                    kind=_kind_for_path(resolved),
                    is_manifest=resolved.name in MANIFEST_NAMES or resolved.name.endswith("_manifest.json"),
                )
        except (OSError, RuntimeError, TypeError, ValueError):
            continue

    ordered = sorted(found.values(), key=lambda item: (-item.mtime_ns, item.relative_path.casefold()))
    return tuple(ordered[: max(0, int(limit))])


def build_artifact_signature(records: Iterable[ArtifactRecord]) -> str:
    payload = [
        {
            "path": record.relative_path,
            "size": record.size,
            "mtime_ns": record.mtime_ns,
        }
        for record in records
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def summarize_artifacts(records: Iterable[ArtifactRecord]) -> dict[str, Any]:
    record_tuple = tuple(records)
    total_size = sum(record.size for record in record_tuple)
    latest = record_tuple[0] if record_tuple else None
    manifests = [record for record in record_tuple if record.is_manifest]
    return {
        "count": len(record_tuple),
        "total_size": total_size,
        "total_size_label": format_bytes(total_size),
        "latest_path": latest.relative_path if latest else "",
        "latest_updated_utc": latest.mtime_iso if latest else "",
        "manifest_count": len(manifests),
        "signature": build_artifact_signature(record_tuple),
    }


def read_artifact_preview(path: Path, *, max_bytes: int = PREVIEW_BYTES) -> ArtifactPreview:
    try:
        resolved = Path(path).expanduser().resolve(strict=False)
        stat = resolved.stat()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return ArtifactPreview(kind="error", value="", error=str(exc))

    suffix = resolved.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return ArtifactPreview(kind="image", value=resolved)
    if suffix == ".json" and stat.st_size <= MAX_JSON_PREVIEW_BYTES:
        try:
            return ArtifactPreview(kind="json", value=json.loads(resolved.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            return ArtifactPreview(kind="error", value="", error=str(exc))
    if suffix in TEXT_SUFFIXES or suffix == ".json":
        try:
            return ArtifactPreview(kind="text", value=_read_tail_text(resolved, max_bytes=max_bytes), truncated=stat.st_size > max_bytes)
        except (OSError, UnicodeDecodeError) as exc:
            return ArtifactPreview(kind="error", value="", error=str(exc))
    return ArtifactPreview(
        kind="metadata",
        value={"path": resolved.as_posix(), "size": format_bytes(stat.st_size), "updated_utc": _mtime_iso(stat.st_mtime_ns)},
    )


def _read_tail_text(path: Path, *, max_bytes: int = PREVIEW_BYTES) -> str:
    max_length = max(1, int(max_bytes))
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_length:
            handle.seek(size - max_length)
            prefix = "... "
        else:
            prefix = ""
        payload = handle.read(max_length)
    return prefix + payload.decode("utf-8", errors="replace")


def refresh_run_every(enabled: bool, interval_seconds: int | float | str) -> str | None:
    if not enabled:
        return None
    try:
        seconds = max(1, int(float(interval_seconds)))
    except (TypeError, ValueError):
        seconds = 5
    return f"{seconds}s"


def _resolve_active_app() -> Path:
    return resolve_active_app_path(error_fn=st.error, stop_fn=st.stop)


def _active_env(active_app_path: Path) -> AgiEnv:
    current = st.session_state.get("env")
    current_apps_path = getattr(current, "apps_path", None)
    try:
        current_apps_root = Path(current_apps_path).resolve(strict=False) if current_apps_path else None
    except (OSError, RuntimeError, TypeError, ValueError):
        current_apps_root = None
    if (
        current is not None
        and getattr(current, "app", None) == active_app_path.name
        and current_apps_root == active_app_path.parent.resolve(strict=False)
    ):
        return current
    env = AgiEnv(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)
    env.init_done = True
    st.session_state["env"] = env
    return env


def _default_export_root(env: AgiEnv) -> Path:
    export_root = Path(getattr(env, "AGILAB_EXPORT_ABS", Path.home() / "export"))
    target = str(getattr(env, "target", "") or getattr(env, "app", "") or "")
    return export_root / target if target else export_root


def root_candidates(env: AgiEnv, active_app_path: Path) -> dict[str, Path]:
    candidates = {
        "Export artifacts": _default_export_root(env),
        "Run environment": Path(getattr(env, "runenv", "") or active_app_path / ".venv"),
        "App project": active_app_path,
    }
    return {label: path for label, path in candidates.items() if str(path)}


def _state_key(app_name: str, suffix: str) -> str:
    return f"{PAGE_KEY}__{app_name}__{suffix}"


def _render_controls(env: AgiEnv, active_app_path: Path) -> tuple[Path, tuple[str, ...], int, bool, int]:
    app_name = active_app_path.name
    candidates = root_candidates(env, active_app_path)
    labels = [*candidates, "Custom path"]
    root_key = _state_key(app_name, "root_choice")
    if st.session_state.get(root_key) not in labels:
        st.session_state[root_key] = labels[0]
    root_choice = st.sidebar.selectbox("Artifact root", labels, key=root_key)

    custom_key = _state_key(app_name, "custom_root")
    st.session_state.setdefault(custom_key, str(candidates[labels[0]]))
    custom_value = st.sidebar.text_input("Custom path", key=custom_key)
    selected_root = Path(custom_value).expanduser() if root_choice == "Custom path" else candidates[root_choice]

    pattern_key = _state_key(app_name, "patterns")
    st.session_state.setdefault(pattern_key, format_patterns(DEFAULT_PATTERNS))
    pattern_value = st.sidebar.text_area("Artifact globs", key=pattern_key, height=92)

    limit_key = _state_key(app_name, "limit")
    st.session_state.setdefault(limit_key, 100)
    max_files = int(st.sidebar.number_input("Max files", min_value=1, max_value=MAX_DISCOVERED_FILES, step=10, key=limit_key))

    live_key = _state_key(app_name, "live_refresh")
    st.session_state.setdefault(live_key, True)
    live_refresh = bool(st.sidebar.toggle("Live refresh", key=live_key))

    interval_key = _state_key(app_name, "interval")
    if st.session_state.get(interval_key) not in REFRESH_INTERVAL_SECONDS:
        st.session_state[interval_key] = 5
    interval_seconds = int(st.sidebar.selectbox("Refresh interval", REFRESH_INTERVAL_SECONDS, key=interval_key))

    if st.sidebar.button("Refresh now", type="secondary", width="stretch"):
        st.rerun()

    return selected_root, parse_patterns(pattern_value), max_files, live_refresh, interval_seconds


def _render_preview(records: tuple[ArtifactRecord, ...]) -> None:
    options = [record.relative_path for record in records]
    if not options:
        return
    selected_label = st.selectbox("Preview artifact", options=options, key=f"{PAGE_KEY}_preview_artifact")
    selected = next((record for record in records if record.relative_path == selected_label), records[0])
    preview = read_artifact_preview(selected.path)
    st.caption(f"{selected.relative_path} · {format_bytes(selected.size)} · {selected.mtime_iso}")
    if preview.error:
        st.error("Preview unavailable.")
        st.code(preview.error, language="text")
    elif preview.kind == "json":
        st.json(preview.value, expanded=False)
    elif preview.kind == "image":
        st.image(str(preview.value), caption=selected.relative_path)
    elif preview.kind == "text":
        st.code(str(preview.value), language="text")
        if preview.truncated:
            st.caption("Showing the latest portion of this file.")
    else:
        st.json(preview.value, expanded=False)


def _render_artifacts_panel(root: Path, patterns: tuple[str, ...], max_files: int) -> None:
    records = discover_artifacts(root, patterns, limit=max_files)
    summary = summarize_artifacts(records)
    scanned_at = datetime.now(tz=UTC).replace(microsecond=0).isoformat()

    cols = st.columns(4)
    cols[0].metric("Artifacts", str(summary["count"]))
    cols[1].metric("Manifests", str(summary["manifest_count"]))
    cols[2].metric("Size", summary["total_size_label"])
    cols[3].metric("Scanned", scanned_at.split("T", 1)[1].replace("+00:00", " UTC"))

    if not root.exists():
        st.warning(f"Artifact root does not exist yet: {root}")
        return
    if not records:
        st.info("No matching artifacts found.")
        return

    latest = summary["latest_path"]
    if latest:
        st.caption(f"Latest update: {latest} at {summary['latest_updated_utc']}")
    st.caption(f"Signature: {summary['signature'][:16]}")

    manifest_rows = [record.as_row() for record in records if record.is_manifest]
    if manifest_rows:
        st.subheader("Manifest candidates")
        st.dataframe(manifest_rows, width="stretch", hide_index=True)

    st.subheader("Artifacts")
    st.dataframe([record.as_row() for record in records], width="stretch", hide_index=True)
    _render_preview(records)


def _render_live_or_static_panel(root: Path, patterns: tuple[str, ...], max_files: int, live_refresh: bool, interval_seconds: int) -> None:
    run_every = refresh_run_every(live_refresh, interval_seconds)
    if run_every is None:
        _render_artifacts_panel(root, patterns, max_files)
        return

    @st.fragment(run_every=run_every)
    def _live_fragment() -> None:
        _render_artifacts_panel(root, patterns, max_files)

    _live_fragment()


def main() -> None:
    st.set_page_config(layout="wide")
    active_app_path = _resolve_active_app()
    env = _active_env(active_app_path)

    render_logo("Live Artifacts")
    st.title("Live artifacts")
    st.caption("Monitor exported evidence, manifests, logs, and lightweight artifacts for the active app.")

    root, patterns, max_files, live_refresh, interval_seconds = _render_controls(env, active_app_path)
    st.caption(f"Root: {root}")
    _render_live_or_static_panel(root, patterns, max_files, live_refresh, interval_seconds)


if __name__ == "__main__":  # pragma: no cover - Streamlit script entrypoint
    main()
