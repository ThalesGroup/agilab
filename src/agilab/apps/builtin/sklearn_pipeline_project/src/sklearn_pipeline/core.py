"""Evidence helpers for the built-in scikit-learn pipeline app."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from joblib import dump
from sklearn.datasets import make_classification
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


SCHEMA = "agilab.app.sklearn_pipeline.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path, *, role: str, output_dir: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(output_dir)),
        "role": role,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def build_sklearn_pipeline_artifacts(
    *,
    output_dir: Path,
    seed: int = 2026,
    sample_count: int = 240,
    test_size: float = 0.25,
    regularization_c: float = 1.0,
) -> dict[str, Any]:
    """Train a deterministic sklearn pipeline and write an audit bundle."""

    output_dir = output_dir.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    features, target = make_classification(
        n_samples=sample_count,
        n_features=8,
        n_informative=5,
        n_redundant=1,
        n_classes=2,
        class_sep=1.35,
        flip_y=0.03,
        random_state=seed,
    )
    features_train, features_test, target_train, target_test = train_test_split(
        features,
        target,
        test_size=test_size,
        random_state=seed,
        stratify=target,
    )
    pipeline = Pipeline(
        steps=[
            ("scale", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    C=regularization_c,
                    max_iter=500,
                    random_state=seed,
                    solver="lbfgs",
                ),
            ),
        ]
    )
    pipeline.fit(features_train, target_train)
    predictions = pipeline.predict(features_test)
    probabilities = pipeline.predict_proba(features_test)[:, 1]

    metrics = {
        "accuracy": round(float(accuracy_score(target_test, predictions)), 6),
        "f1": round(float(f1_score(target_test, predictions)), 6),
        "test_rows": int(len(target_test)),
        "train_rows": int(len(target_train)),
    }
    matrix = confusion_matrix(target_test, predictions).tolist()
    report = classification_report(target_test, predictions, output_dict=True, zero_division=0)

    predictions_path = output_dir / "predictions.csv"
    with predictions_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["row_id", "target", "prediction", "positive_probability"])
        for row_id, (actual, predicted, probability) in enumerate(
            zip(target_test, predictions, probabilities)
        ):
            writer.writerow([row_id, int(actual), int(predicted), f"{float(probability):.8f}"])

    metrics_path = output_dir / "metrics.json"
    metrics_payload = {
        "schema": SCHEMA,
        "seed": seed,
        "model": "sklearn.pipeline.Pipeline(StandardScaler, LogisticRegression)",
        "metrics": metrics,
        "confusion_matrix": matrix,
        "classification_report": report,
    }
    metrics_path.write_text(json.dumps(metrics_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    model_path = output_dir / "model.joblib"
    dump(pipeline, model_path)

    report_path = output_dir / "sklearn_report.md"
    report_path.write_text(
        "\n".join(
            [
                "# Scikit-Learn Pipeline Evidence",
                "",
                f"- seed: `{seed}`",
                f"- train rows: `{metrics['train_rows']}`",
                f"- test rows: `{metrics['test_rows']}`",
                f"- accuracy: `{metrics['accuracy']}`",
                f"- f1: `{metrics['f1']}`",
                "",
                "The model, predictions, metrics, and manifest are persisted together for audit and replay.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    artifacts = {
        "metrics": _artifact(metrics_path, role="model quality evidence", output_dir=output_dir),
        "predictions": _artifact(predictions_path, role="row-level prediction evidence", output_dir=output_dir),
        "model": _artifact(model_path, role="serialized sklearn pipeline", output_dir=output_dir),
        "report": _artifact(report_path, role="human-readable evidence summary", output_dir=output_dir),
    }
    manifest_path = output_dir / "run_manifest.json"
    manifest = {
        "schema": SCHEMA,
        "app": "sklearn_pipeline_project",
        "deterministic": True,
        "runtime": "agi worker",
        "inputs": {
            "dataset": "sklearn.datasets.make_classification",
            "seed": seed,
            "sample_count": sample_count,
            "test_size": test_size,
            "regularization_c": regularization_c,
        },
        "artifacts": artifacts,
        "metrics": metrics,
        "promotion_hint": "candidate" if metrics["accuracy"] >= 0.85 and metrics["f1"] >= 0.85 else "review",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_artifacts = {
        **artifacts,
        "manifest": _artifact(manifest_path, role="artifact hash manifest", output_dir=output_dir),
    }

    summary_path = output_dir / "sklearn_pipeline_summary.json"
    summary = {
        "schema": SCHEMA,
        "output_dir": str(output_dir),
        "metrics": metrics,
        "promotion_hint": manifest["promotion_hint"],
        "artifacts": summary_artifacts,
        "manifest": str(manifest_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary
