"""Stable spawn targets for workflow evidence multiprocessing tests.

Pytest can collect the repository tests under different package names depending
on the checkout path.  Spawned processes must import their target by module
name, so keep the targets in this non-collected module and put the test
directory on ``sys.path`` before processes start.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path
import sys


def _import_workflow_run_manifest():
    repo_root = Path(__file__).resolve().parents[1]
    source_root = repo_root / "src"
    package_root = source_root / "agilab"
    source_root_text = str(source_root)
    if source_root_text not in sys.path:
        sys.path.insert(0, source_root_text)

    package_spec = importlib.util.spec_from_file_location(
        "agilab",
        package_root / "__init__.py",
        submodule_search_locations=[str(package_root)],
    )
    package = sys.modules.get("agilab")
    if package is None or not hasattr(package, "__path__"):
        assert package_spec is not None and package_spec.loader is not None
        package = importlib.util.module_from_spec(package_spec)
        sys.modules["agilab"] = package
        package_spec.loader.exec_module(package)
    else:
        package_paths = list(package.__path__)
        package_root_text = str(package_root)
        if package_root_text not in package_paths:
            package.__path__ = [package_root_text, *package_paths]
        package.__spec__ = package_spec
        package.__file__ = str(package_root / "__init__.py")
        package.__package__ = "agilab"

    importlib.invalidate_caches()
    return importlib.import_module("agilab.workflow_run_manifest")


workflow_run_manifest = _import_workflow_run_manifest()


def workflow_evidence_writer(
    lab_dir: str,
    state_path: str,
    state: dict,
    start,
    results,
) -> None:
    start.wait(timeout=10)
    try:
        workflow_run_manifest.write_workflow_run_evidence(
            state=state,
            state_path=Path(state_path),
            repo_root=Path(lab_dir).parent,
            lab_dir=Path(lab_dir),
            trigger={"surface": "multiprocess", "action": "write"},
        )
    except BaseException as exc:
        results.put(("error", type(exc).__name__, str(exc)))
    else:
        results.put(("ok", "", ""))


def workflow_evidence_trigger_writer(
    lab_dir: str,
    state_path: str,
    state: dict,
    trigger: dict,
    start,
    results,
) -> None:
    start.wait(timeout=10)
    try:
        bundle = workflow_run_manifest.write_workflow_run_evidence(
            state=state,
            state_path=Path(state_path),
            repo_root=Path(lab_dir).parent,
            lab_dir=Path(lab_dir),
            trigger=trigger,
        )
    except BaseException as exc:
        results.put(("error", type(exc).__name__, str(exc)))
    else:
        results.put(("ok", bundle.manifest["manifest_id"], trigger["action"]))


def workflow_evidence_crash_writer(lab_dir: str, state_path: str, state: dict) -> None:
    real_write = workflow_run_manifest._write_json_fsync
    calls = 0

    def crash_after_partial_stage(path, payload):
        nonlocal calls
        calls += 1
        real_write(path, payload)
        if calls == 2:
            os._exit(23)

    workflow_run_manifest._write_json_fsync = crash_after_partial_stage
    workflow_run_manifest.write_workflow_run_evidence(
        state=state,
        state_path=Path(state_path),
        repo_root=Path(lab_dir).parent,
        lab_dir=Path(lab_dir),
        trigger={"surface": "crash", "action": "write"},
    )
