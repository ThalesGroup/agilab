"""Read-only preview for the built-in multi-app DAG project."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence


def _repo_root_from_file() -> Path | None:
    module_file = Path(__file__).resolve()
    if len(module_file.parents) < 6:
        return None
    package_path = module_file.parents[5]
    expected = Path(
        "apps/builtin/multi_app_dag_project/src/multi_app_dag/preview_multi_app_dag.py"
    )
    repo_root = package_path.parent.parent
    if (
        module_file.relative_to(package_path) == expected
        and package_path == repo_root / "src/agilab"
        and (package_path / "apps/builtin").is_dir()
    ):
        return repo_root
    return None


_SOURCE_ROOT = _repo_root_from_file()
if _SOURCE_ROOT is not None:
    source_path = str(_SOURCE_ROOT / "src")
    if source_path not in sys.path:
        sys.path.insert(0, source_path)

from agilab.global_pipeline.global_pipeline_execution_plan import build_execution_plan
from agilab.global_pipeline.global_pipeline_runner_state import dispatch_next_runnable, persist_runner_state


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DAG_PATH = PROJECT_ROOT / "dag_templates" / "flight_to_weather_multi_app_dag.json"
DEFAULT_OUTPUT_PATH = Path.home() / "log" / "execute" / "multi_app_dag" / "runner_state.json"
RUN_ID = "multi-app-dag-preview"


def agilab_package_path() -> Path:
    marker = Path.home() / ".local/share/agilab/.agilab-path"
    if not marker.is_file():
        raise SystemExit(
            "AGILAB is not initialized. Run the AGILAB installer or "
            "`agilab first-proof --json` before this example."
        )
    path = Path(marker.read_text(encoding="utf-8").strip()).expanduser()
    if not path.is_dir():
        raise SystemExit(f"AGILAB package path from {marker} does not exist: {path}")
    return path


def _source_checkout_root_from_package(package_path: Path) -> Path | None:
    package_path = package_path.resolve()
    parents = package_path.parents
    if len(parents) < 2:
        return None
    repo_root = parents[1]
    if (repo_root / "src" / "agilab").resolve() == package_path and (
        package_path / "apps" / "builtin"
    ).is_dir():
        return repo_root
    return None


def _apps_content_hash(apps_path: Path) -> str:
    digest = hashlib.sha256()

    def visit(directory: Path, ancestors: set[Path]) -> None:
        resolved = directory.resolve()
        if resolved in ancestors:
            raise OSError(f"Cyclic app assets under {apps_path}")
        for entry in sorted(directory.iterdir()):
            relative = entry.relative_to(apps_path).as_posix()
            if entry.is_dir():
                record = ("directory", relative)
                visit(entry, ancestors | {resolved})
            else:
                if not entry.is_file():
                    raise OSError(
                        f"Unsupported app asset under {apps_path}: {relative}"
                    )
                with entry.open("rb") as stream:
                    record = (
                        "file",
                        relative,
                        hashlib.file_digest(stream, "sha256").hexdigest(),
                    )
            digest.update(json.dumps(record).encode("utf-8"))

    visit(apps_path, set())
    return digest.hexdigest()


def _path_identity(path: Path) -> tuple[int, int] | None:
    try:
        status = path.lstat()
    except FileNotFoundError:
        return None
    return status.st_dev, status.st_ino


def _ensure_packaged_layout_adapter(package_path: Path) -> Path:
    apps_path = (package_path / "apps").resolve()
    if not (apps_path / "builtin").is_dir():
        raise SystemExit(f"AGILAB built-in apps are not available under {apps_path}")

    cache_root = Path.home() / ".cache" / "agilab" / "multi_app_dag_layout"
    if cache_root.is_symlink() or (cache_root.exists() and not cache_root.is_dir()):
        raise SystemExit(
            f"Could not prepare a planning layout under {cache_root}: unrecognized cache root"
        )

    adapter_package = cache_root / "src" / "agilab"
    adapter_apps = adapter_package / "apps"
    copy_source = adapter_package / ".apps-copy-source"
    parents = (cache_root / "src", adapter_package)
    if not any(
        path.is_symlink() or (path.exists() and not path.is_dir()) for path in parents
    ):
        if not copy_source.exists() and not copy_source.is_symlink():
            if adapter_apps.is_symlink():
                if adapter_apps.resolve() == apps_path:
                    return cache_root
            elif not adapter_apps.exists():
                adapter_package.mkdir(parents=True, exist_ok=True)
                try:
                    adapter_apps.symlink_to(apps_path, target_is_directory=True)
                except OSError:
                    pass
                else:
                    return cache_root

    # Preserve legacy copies and occupied layouts. A returned copy is never redirected.
    content_hash = _apps_content_hash(apps_path)
    provenance = json.dumps(
        {"source": str(apps_path), "sha256": content_hash}, sort_keys=True
    )
    copy_key = hashlib.sha256(provenance.encode("utf-8")).hexdigest()
    index = 0
    while True:
        copies = cache_root / ("copies" if index == 0 else f"copies-{index}")
        if not copies.is_symlink() and not (copies.exists() and not copies.is_dir()):
            copies.mkdir(parents=True, exist_ok=True)
            break
        index += 1

    index = 0
    while True:
        repo_root = copies / (copy_key if index == 0 else f"{copy_key}-{index}")
        index += 1
        if repo_root.exists() or repo_root.is_symlink():
            package = repo_root / "src/agilab"
            cached_apps = package / "apps"
            marker = package / ".apps-copy-source"
            if not any(
                path.is_symlink()
                for path in (repo_root, repo_root / "src", package, cached_apps, marker)
            ):
                try:
                    if (
                        marker.is_file()
                        and marker.read_bytes() == provenance.encode("utf-8")
                        and cached_apps.is_dir()
                        and _apps_content_hash(cached_apps) == content_hash
                    ):
                        return repo_root
                except OSError:
                    pass
            continue

        try:
            repo_root.mkdir()
        except FileExistsError:
            continue
        slot_identity = _path_identity(repo_root)
        staging = None
        staging_identity = None
        try:
            staging = Path(tempfile.mkdtemp(prefix=".apps-copy-", dir=copies))
            staging_identity = _path_identity(staging)
            staged_package = staging / "src/agilab"
            staged_package.mkdir(parents=True)
            shutil.copytree(apps_path, staged_package / "apps")
            if _apps_content_hash(staged_package / "apps") != content_hash:
                raise OSError(
                    "AGILAB app assets changed while copying; retry the preview"
                )
            (staged_package / ".apps-copy-source").write_text(
                provenance, encoding="utf-8"
            )
            (staging / "src").rename(repo_root / "src")
            return repo_root
        finally:
            # These identity checks cover cooperative recovery, not adversarial TOCTOU.
            if staging is not None and _path_identity(staging) == staging_identity:
                shutil.rmtree(staging)
            if _path_identity(repo_root) == slot_identity:
                try:
                    repo_root.rmdir()
                except OSError:
                    pass


def planning_repo_root(explicit_repo_root: Path | None = None) -> Path:
    if explicit_repo_root is not None:
        return explicit_repo_root.expanduser().resolve()
    if _SOURCE_ROOT is not None:
        return _SOURCE_ROOT.resolve()
    package_path = agilab_package_path()
    source_root = _source_checkout_root_from_package(package_path)
    if source_root is not None:
        return source_root.resolve()
    return _ensure_packaged_layout_adapter(package_path).resolve()


def _unit_preview(unit: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": unit["id"],
        "app": unit["app"],
        "dispatch_status": "runnable" if unit.get("ready") is True else "blocked",
        "depends_on": list(unit.get("depends_on", [])),
        "produces": [
            artifact["artifact"]
            for artifact in unit.get("produces", [])
            if isinstance(artifact, dict) and artifact.get("artifact")
        ],
    }


def _artifact_handoffs(units: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    handoffs: list[dict[str, str]] = []
    units_by_id = {str(unit.get("id", "")): unit for unit in units}
    for unit in units:
        for dependency in unit.get("artifact_dependencies", []):
            if not isinstance(dependency, dict):
                continue
            source_id = str(dependency.get("from", ""))
            source_unit = units_by_id.get(source_id, {})
            handoffs.append(
                {
                    "artifact": str(dependency.get("artifact", "")),
                    "from": source_id,
                    "from_app": str(dependency.get("from_app", "")),
                    "source_path": str(dependency.get("source_path", "")),
                    "to": str(unit.get("id", "")),
                    "to_app": str(unit.get("app", "")),
                    "handoff": str(dependency.get("handoff", "")),
                    "producer_status": "runnable" if source_unit.get("ready") is True else "blocked",
                }
            )
    return handoffs


def build_preview(
    *,
    repo_root: Path,
    dag_path: Path = DAG_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    now: str = "2026-04-29T00:00:00Z",
) -> dict[str, Any]:
    plan = build_execution_plan(repo_root=repo_root, dag_path=dag_path)
    proof = persist_runner_state(
        repo_root=repo_root,
        dag_path=dag_path,
        output_path=output_path,
        run_id=RUN_ID,
        now=now,
    )
    dispatch = dispatch_next_runnable(proof.runner_state, now=now)
    units = list(plan.runnable_units)

    return {
        "example": "multi_app_dag_project",
        "goal": "Preview a built-in multi-app DAG that coordinates multiple AGILAB apps through artifact contracts.",
        "dag": {
            "path": plan.dag_path,
            "ok": plan.ok,
            "issues": [issue.as_dict() for issue in plan.issues],
            "execution_order": list(plan.execution_order),
        },
        "units": [_unit_preview(unit) for unit in units],
        "artifact_handoffs": _artifact_handoffs(units),
        "runner_state": {
            "path": proof.path,
            "round_trip_ok": proof.round_trip_ok,
            "run_status": proof.runner_state["run_status"],
            "summary": proof.runner_state["summary"],
        },
        "after_first_dispatch": {
            "ok": dispatch.ok,
            "dispatched_unit_id": dispatch.dispatched_unit_id,
            "run_status": dispatch.state["run_status"],
            "summary": dispatch.state["summary"],
        },
        "real_app_execution": False,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview the built-in AGILAB multi-app DAG without executing app stages."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Optional source checkout root. If omitted, the preview uses the local source layout or AGILAB marker.",
    )
    parser.add_argument(
        "--dag-path",
        type=Path,
        default=DAG_PATH,
        help="Path to an agilab.multi_app_dag.v1 JSON contract.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Where to write the read-only runner-state preview JSON.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> dict[str, Any]:
    args = _parse_args(argv)
    summary = build_preview(
        repo_root=planning_repo_root(args.repo_root),
        dag_path=args.dag_path.expanduser(),
        output_path=args.output.expanduser(),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


if __name__ == "__main__":
    main()
