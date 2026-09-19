#!/usr/bin/env python3
"""Acceptance checks for a user-notebook adaptation.

Checks generated Python execution and interface behavior, not scientific validity
or equivalence to the original. This is not a sandbox for hostile generated code.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys
import tempfile
import tomllib


def _has_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_has_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_value(item) for item in value)
    return False


def _visible_results(app) -> tuple:
    return tuple((kind, tuple(repr(element.value) for element in getattr(app, kind)))
                 for kind in ("metric", "dataframe", "json", "markdown", "text"))


def _reject_nonfinite(value: str):
    raise ValueError(f"Non-finite result: {value}")


def verify(project: Path) -> dict:
    from streamlit.testing.v1 import AppTest

    project = project.resolve()
    for name in ("app.py", "solution.ipynb", "pyproject.toml"):
        path = project / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing regular generated file: {name}")
    metadata = tomllib.loads((project / "pyproject.toml").read_text())
    if not isinstance(metadata.get("project"), dict) or not metadata["project"].get("name"):
        raise ValueError("pyproject.toml must declare project metadata")
    notebook = json.loads((project / "solution.ipynb").read_text())
    if not isinstance(notebook, dict) or notebook.get("nbformat") != 4 or not isinstance(notebook.get("cells"), list):
        raise ValueError("solution.ipynb must be a version 4 Python notebook")
    language = notebook.get("metadata", {}).get("kernelspec", {}).get("language", "python")
    if language.lower() != "python":
        raise ValueError("Only self-contained Python notebooks are supported")
    cells = [c for c in notebook["cells"] if isinstance(c, dict) and c.get("cell_type") == "code"]
    if not cells:
        raise ValueError("solution.ipynb must contain runnable Python cells")
    old_cwd, old_path = Path.cwd(), sys.path[:]
    try:
        sys.path.insert(0, str(project))
        with tempfile.TemporaryDirectory(prefix="agilab-notebook-check-") as scratch:
            os.chdir(scratch)
            namespace = {"__name__": "__main__", "PROJECT_ROOT": project}
            for index, cell in enumerate(cells):
                source = cell.get("source", "")
                source = "".join(source) if isinstance(source, list) else source
                exec(compile(source, f"solution.ipynb:cell-{index}", "exec"), namespace)
            output = Path("results.json")
            if output.is_symlink() or not output.is_file():
                raise ValueError("Notebook must write fresh results.json in its execution directory")
            results = json.loads(output.read_text(), parse_constant=_reject_nonfinite)
            if not isinstance(results, dict) or not isinstance(results.get("results"), dict) or not _has_value(results["results"]):
                raise ValueError("results.json must contain a results object with at least one nonempty result value")
        os.chdir(project)
        app = AppTest.from_file(str(project / "app.py"), default_timeout=60).run()
        if app.exception:
            raise ValueError(f"App startup failed: {app.exception[0].message}")
        buttons = [button for button in app.button if button.label == "Run analysis"]
        if len(buttons) != 1:
            raise ValueError("App must expose exactly one Run analysis button")
        before = _visible_results(app)
        buttons[0].click().run()
        if app.exception:
            raise ValueError(f"App interaction failed: {app.exception[0].message}")
        after = _visible_results(app)
        if before == after or not any(values for _, values in after):
            raise ValueError("Run analysis must render a new or changed visible result")
    finally:
        os.chdir(old_cwd)
        sys.path[:] = old_path
    return {"status": "passed", "verification_scope": "execution_and_interface",
            "checks": ["fresh_notebook_execution", "fresh_result_artifact",
                       "app_startup", "app_run_analysis_interaction"],
            "result_names": sorted(results["results"]),
            "scientific_correctness_verified": False}


def main() -> int:
    try:
        report = verify(Path.cwd())
    except Exception as exc:
        report = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
