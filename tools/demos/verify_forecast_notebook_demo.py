"""Run independent, real-model acceptance checks for the public forecast demo.

Use the prepared environment and local model snapshot; this script never installs
packages or downloads model weights. A passed receipt records these specific
checks and synthetic measurements, not a general forecasting-quality guarantee.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from importlib import metadata, util
import json
import os
from pathlib import Path
import platform
import sys
import tempfile

from export_forecast_notebook_demo import CORE_FILES, PUBLIC_FILES, checked_file

MODEL_ID = "autogluon/chronos-2-small"
MODEL_REVISION = "ddec01313e50b6bc58ebaa92ede81bc24a3d9f9a"
SEEDS = (7, 42, 2026)
HORIZON = 28


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def public_hashes(project: Path) -> dict[str, str]:
    hashes = {}
    for name in sorted(PUBLIC_FILES):
        path = project
        for part in Path(name).parts:
            path = path / part
            require(not path.is_symlink(), f"Symlinked public forecast asset: {name}")
        if path.exists():
            expected = digest(path)
            checked_file(project, name, expected)
            hashes[name] = expected
    require(CORE_FILES.union({"LICENSE"}).issubset(hashes),
            "Required public forecast artifacts are missing")
    return hashes


def weight_evidence() -> dict:
    """Verify the exact checkpoint independently, without downloading it."""
    expected = {
        "config.json": "f2780468adc8b16322aa0b6e28b26476c9401ecf64ab53292b6d2b0d3f423722",
        "model.safetensors": "492290ae82bb89f9769e3479ce90b3179de1f33e600c34daa0352531538b23cd",
    }
    override = os.environ.get("CHRONOS_MODEL_PATH")
    hashes = {}
    for name, wanted in expected.items():
        if override:
            root = Path(override).expanduser()
            require(not (root / "adapter_config.json").exists(), "Expected the pinned base model, not an adapter")
            path = root / name
        else:
            from huggingface_hub import try_to_load_from_cache
            found = try_to_load_from_cache(MODEL_ID, name, revision=MODEL_REVISION)
            require(isinstance(found, str), f"Pinned model artifact is not cached: {name}")
            path = Path(found)
        require(path.is_file(), f"Pinned model artifact is missing: {name}")
        hashes[name] = digest(path)
        require(hashes[name] == wanted, f"Pinned model artifact changed: {name}")
    return {
        "weight_source": "local_model_path" if override else "pinned_hugging_face_cache",
        "weight_files_sha256": hashes,
    }


def verify(run: Path) -> dict:
    import numpy as np
    from chronos import Chronos2Pipeline

    require(not run.is_symlink(), "Run directory must not be a symlink")
    run = run.resolve()
    report_path = run / "result.json"
    require(not report_path.is_symlink(), "Run receipt must not be a symlink")
    initial_report_hash = digest(report_path)
    report = json.loads(report_path.read_text())
    require(report.get("status") == "passed", "Autonomous run has not passed")
    require(report.get("verification", {}).get("status") == "passed",
            "Autonomous execution/interface verification has not passed")
    project = run / "notebook_app_project"
    require(not project.is_symlink(), "Generated project must not be a symlink")
    files = public_hashes(project)
    for name in sorted(CORE_FILES):
        require(report.get("files", {}).get(name) == files[name],
                f"Autonomous-run artifact changed: {name}")
    source = report["source"]
    original = project / "source" / "original.ipynb"
    checked_file(project, "source/original.ipynb", source["sha256"])
    require(files.get("source/original.ipynb") == source["sha256"],
            "Original notebook does not match recorded source provenance")
    require(source.get("repository") == "amazon-science/chronos-forecasting",
            "Unexpected source repository")
    require(all(isinstance(source.get(key), str) and source[key]
                for key in ("repository", "commit", "url", "sha256")),
            "Source provenance is incomplete")
    checks = ["autonomous_run_passed", "autonomous_artifacts_unchanged", "original_source_hash"]

    spec = util.spec_from_file_location("checked_forecast_core", project / "forecast_core.py")
    require(spec is not None and spec.loader is not None, "Cannot load the generated forecast module")
    core = util.module_from_spec(spec)
    sys.modules[spec.name] = core
    original_predict = Chronos2Pipeline.predict_quantiles
    observed = []
    cases = []

    def tracked_predict(self, *args, **kwargs):
        result = original_predict(self, *args, **kwargs)
        quantiles, point = result
        q = quantiles[0].detach().cpu().numpy().copy()
        p = point[0].detach().cpu().numpy().copy()
        observed.append((q, p, list(kwargs.get("quantile_levels", []))))
        return result

    def array(value, length, name):
        result = np.asarray(value)
        require(result.shape == (length,), f"{name} has shape {result.shape}, expected {(length,)}")
        require(np.isfinite(result).all(), f"{name} contains non-finite values")
        return result

    def validate_fixture(data):
        require(isinstance(data, dict), "make_fixture must return a mapping")
        context = np.asarray(data["context"])
        require(context.ndim == 1 and len(context) >= 7, "Context must contain at least seven observations")
        for name in ("context", "past_promotion", "past_weekday"):
            array(data[name], len(context), name)
        for name in ("actual", "future_promotion", "future_weekday"):
            array(data[name], HORIZON, name)

    def validate_prediction(prediction, observation):
        require(isinstance(prediction, dict), "predict must return a mapping")
        values = {name: array(prediction[name], HORIZON, name)
                  for name in ("forecast", "lower", "upper")}
        require(np.all(values["lower"] <= values["forecast"])
                and np.all(values["forecast"] <= values["upper"]),
                "Forecast and uncertainty bounds are not ordered")
        q, point, levels = observation
        require(q.shape == (1, HORIZON, 3) and point.shape == (1, HORIZON),
                "Unexpected real Chronos output shapes")
        require(levels == [0.1, 0.5, 0.9], "Unexpected Chronos quantile levels")
        require(np.isfinite(q).all() and np.isfinite(point).all(),
                "Real Chronos inference returned non-finite values")
        require(np.all(np.diff(q, axis=-1) >= 0), "Real Chronos quantiles cross")
        for name, expected in (("forecast", point[0]), ("lower", q[0, :, 0]), ("upper", q[0, :, 2])):
            require(np.array_equal(values[name], expected),
                    f"Published {name} differs from the actual Chronos output")
        return values

    def run_prediction(data):
        before = len(observed)
        unchanged = deepcopy(data)
        prediction = core.predict(data, use_covariates=True)
        require(len(observed) == before + 1, "Each forecast must execute one real Chronos predict_quantiles call")
        for name, value in unchanged.items():
            require(np.array_equal(data[name], value), f"Prediction mutated fixture input: {name}")
        return validate_prediction(prediction, observed[-1])

    def metrics(data, prediction):
        actual = np.asarray(data["actual"], dtype=np.float64)
        baseline = np.resize(np.asarray(data["context"])[-7:], HORIZON)
        return baseline, {
            "mae": float(np.mean(np.abs(actual - prediction["forecast"]))),
            "baseline_mae": float(np.mean(np.abs(actual - baseline))),
            "coverage": float(np.mean((actual >= prediction["lower"]) & (actual <= prediction["upper"]))),
        }

    try:
        spec.loader.exec_module(core)
        require(core.MODEL_ID == MODEL_ID and core.MODEL_REVISION == MODEL_REVISION,
                "Generated code changed the pinned model identity or revision")
        # Patch the actual provider method, retaining and invoking its original.
        Chronos2Pipeline.predict_quantiles = tracked_predict
        for seed in SEEDS:
            data = core.make_fixture(seed=seed, horizon=HORIZON, promotion_start=7, promotion_days=7)
            validate_fixture(data)
            prediction = run_prediction(data)
            changed_actual = deepcopy(data)
            changed_actual["actual"] = np.asarray(changed_actual["actual"]) + 1_000_000
            leak_probe = run_prediction(changed_actual)
            require(all(np.array_equal(prediction[key], leak_probe[key]) for key in prediction),
                    f"Held-out actual values influence predictions for seed {seed}")
            zero_promotion = deepcopy(data)
            zero_promotion["future_promotion"] = np.zeros_like(data["future_promotion"])
            changed_schedule = run_prediction(zero_promotion)
            difference = float(np.max(np.abs(prediction["forecast"] - changed_schedule["forecast"])))
            require(difference > 1e-5, f"Future promotion schedule has no measurable effect for seed {seed}")
            baseline, scores = metrics(data, prediction)
            cases.append({
                "seed": seed, "context_length": len(data["context"]), "horizon": HORIZON,
                "promotion_start": 7, "promotion_days": 7, **scores,
                "nominal_interval_coverage": 0.8,
                "seasonal_baseline_period": 7,
                "future_actual_perturbation": 1_000_000,
                "actual_perturbation_predictions_identical": True,
                "promotion_zeroed_max_absolute_forecast_change": difference,
            })
        checks.extend(["three_seed_real_model_inference", "finite_forecast_shapes",
                       "ordered_quantiles", "forecast_matches_instrumented_model_output",
                       "held_out_actual_invariance", "future_promotion_changes_forecast",
                       "independent_mae_seasonal_baseline_and_interval_coverage"])

        before = len(observed)
        analysis = core.run_analysis(seed=42, horizon=HORIZON, promotion_start=7, promotion_days=7)
        require(len(observed) == before + 1, "run_analysis must execute real Chronos inference")
        json.dumps(analysis, allow_nan=False)
        validate_fixture(analysis["fixture"])
        prediction = validate_prediction(analysis["predictions"], observed[-1])
        baseline, scores = metrics(analysis["fixture"], prediction)
        require(np.array_equal(np.asarray(analysis["baseline"]), baseline),
                "run_analysis baseline does not repeat the last seven historical values")
        for key, value in scores.items():
            require(np.isclose(float(analysis["metrics"][key]), value, rtol=1e-6, atol=1e-6),
                    f"run_analysis reports an incorrect {key}")
        checks.append("json_analysis_matches_independent_metrics")
    finally:
        Chronos2Pipeline.predict_quantiles = original_predict
        sys.modules.pop(spec.name, None)

    require(digest(report_path) == initial_report_hash, "Autonomous run receipt changed during verification")
    require(public_hashes(project) == files, "Public forecast artifacts changed during verification")
    require(digest(original) == source["sha256"], "Original source changed during verification")
    checks.append("artifacts_unchanged_after_inference")
    dependencies = {name: metadata.version(name) for name in (
        "chronos-forecasting", "torch", "transformers", "numpy", "pandas", "accelerate",
    )}
    measurements = {
        "cases": cases,
        "real_model_calls": len(observed),
        "model_revision": MODEL_REVISION,
        "dependency_versions": dependencies,
        "python_version": platform.python_version(),
        "platform": platform.system(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "interpretation": (
            "Three deterministic synthetic cases and one analysis-contract check. "
            "MAE and interval coverage are reported without requiring superiority to the baseline. "
            "Changing a promotion input demonstrates model sensitivity, not a causal business effect."
        ),
        **weight_evidence(),
    }
    return {
        "status": "passed", "run_id": run.name, "checks": checks,
        "measurements": measurements, "files": files,
        "source": {**{key: source[key] for key in ("repository", "commit", "url", "sha256")},
                   "license": "Apache-2.0", "author": "Amazon Science"},
        "model": {"id": MODEL_ID, "revision": MODEL_REVISION, "license": "Apache-2.0"},
        "demo": {
            "title": "Chronos-2 demand forecasting lab",
            "description": (
                "Explore synthetic demand with a recent pretrained forecasting model. "
                "Change the horizon and promotion schedule, compare a seasonal baseline, "
                "and reveal held-out observations."
            ),
            "request": "Turn Amazon Science's Chronos-2 notebook into an interactive demand forecasting app.",
        },
        "verification_scope": (
            "execution and interface plus real Chronos inference on three synthetic cases; "
            "held-out target invariance, covariate response, quantile ordering and independent metrics"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run = args.run.expanduser()
    output = args.output.expanduser()
    if output.resolve().is_relative_to((run / "notebook_app_project").resolve()) or output.resolve() == (run / "result.json").resolve():
        parser.error("--output must not overwrite a run receipt or generated project artifact")
    if output.is_symlink():
        parser.error("--output must not be a symlink")
    try:
        result = verify(run)
    except Exception as exc:
        result = {
            "status": "failed", "run_id": run.name,
            "error_type": type(exc).__name__, "error": str(exc),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=output.parent, prefix=f".{output.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write("\n")
    temporary.replace(output)
    print(json.dumps({"status": result["status"], "run_id": result["run_id"],
                      "checks": len(result.get("checks", [])), "error": result.get("error")}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
