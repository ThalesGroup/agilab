#!/usr/bin/env python3
"""Independent acceptance checks for the notebook-to-app live demo.

Copied outside the agent's working directory and executable-bound by Tokki.
This checks a local development result; it is not a sandbox for hostile code.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile


def verify(project: Path) -> dict:
    import numpy as np
    from sklearn.base import clone
    from sklearn.datasets import load_iris
    from sklearn.metrics import accuracy_score
    from sklearn.model_selection import train_test_split
    from streamlit.testing.v1 import AppTest

    project = project.resolve()
    for name in ("models.py", "app.py", "solution.ipynb"):
        path = project / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing regular generated file: {name}")
    sys.path.insert(0, str(project))
    spec = importlib.util.spec_from_file_location("models", project / "models.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["models"] = module
    spec.loader.exec_module(module)
    iris = load_iris()
    scores = []
    for seed in (7, 29, 83):
        X_train, X_test, y_train, y_test = train_test_split(
            iris.data, iris.target, test_size=0.3, stratify=iris.target,
            random_state=seed,
        )
        models = module.build_models(max_depth=3, seed=seed)
        if not isinstance(models, dict) or len(models) < 3:
            raise ValueError("build_models must return at least three sklearn estimators")
        for name, estimator in models.items():
            fitted = clone(estimator).fit(X_train, y_train)
            predictions = fitted.predict(X_test)
            score = float(accuracy_score(y_test, predictions))
            if not np.isfinite(score) or score < 0.8:
                raise ValueError(f"{name} failed held-out accuracy at seed {seed}: {score}")
            scores.append({"model": str(name), "seed": seed, "accuracy": score})

    notebook = json.loads((project / "solution.ipynb").read_text())
    cells = [c for c in notebook.get("cells", []) if c.get("cell_type") == "code"]
    if len(cells) < 2:
        raise ValueError("solution.ipynb must contain at least two runnable workflow cells")
    # Execute in a scratch directory: stale results cannot satisfy this check.
    old_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="agilab-notebook-check-") as scratch:
        try:
            os.chdir(scratch)
            namespace = {"__name__": "__main__", "PROJECT_ROOT": project}
            for index, cell in enumerate(cells):
                source = cell.get("source", "")
                source = "".join(source) if isinstance(source, list) else source
                exec(compile(source, f"solution.ipynb:cell-{index}", "exec"), namespace)
            metrics = json.loads(Path("metrics.json").read_text())
            if not isinstance(metrics, list) or len(metrics) < 3:
                raise ValueError("Notebook must write metrics.json with three model results")
            for row in metrics:
                score = row.get("accuracy")
                if not isinstance(score, (int, float)) or not 0.8 <= score <= 1:
                    raise ValueError("Invalid notebook accuracy result")
        finally:
            os.chdir(old_cwd)

    app = AppTest.from_file(str(project / "app.py"), default_timeout=60).run()
    if app.exception:
        raise ValueError(f"App startup failed: {app.exception[0].message}")
    if not app.slider:
        raise ValueError("App must expose a max-depth slider")
    slider = app.slider[0]
    value = slider.min if slider.value != slider.min else slider.max
    slider.set_value(value).run()
    if app.exception:
        raise ValueError(f"App interaction failed: {app.exception[0].message}")
    if not app.metric or not app.dataframe:
        raise ValueError("App must show a metric and a model comparison table")
    return {
        "status": "passed", "checks": ["held_out_models", "fresh_notebook_execution",
                                         "app_startup", "app_slider_interaction"],
        "scores": scores,
    }


def main() -> int:
    try:
        report = verify(Path.cwd())
    except Exception as exc:
        report = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
