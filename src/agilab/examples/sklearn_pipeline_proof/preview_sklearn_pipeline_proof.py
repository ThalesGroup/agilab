from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from joblib import dump
from sklearn.datasets import make_classification
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


SCHEMA = "agilab.example.sklearn_pipeline_proof.v1"
DEFAULT_OUTPUT_DIR = Path.home() / "log" / "execute" / "sklearn_pipeline_proof"


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


def build_preview(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    seed: int = 2026,
    sample_count: int = 240,
    test_size: float = 0.25,
    regularization_c: float = 1.0,
) -> dict[str, Any]:
    output_dir = output_dir.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    X, y = make_classification(
        n_samples=sample_count,
        n_features=8,
        n_informative=5,
        n_redundant=1,
        n_classes=2,
        class_sep=1.35,
        flip_y=0.03,
        random_state=seed,
    )
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=test_size,
        random_state=seed,
        stratify=y,
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
    pipeline.fit(X_train, y_train)
    predictions = pipeline.predict(X_test)
    probabilities = pipeline.predict_proba(X_test)[:, 1]

    metrics = {
        "accuracy": round(float(accuracy_score(y_test, predictions)), 6),
        "f1": round(float(f1_score(y_test, predictions)), 6),
        "test_rows": int(len(y_test)),
        "train_rows": int(len(y_train)),
    }
    matrix = confusion_matrix(y_test, predictions).tolist()
    report = classification_report(y_test, predictions, output_dict=True, zero_division=0)

    predictions_path = output_dir / "predictions.csv"
    with predictions_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["row_id", "target", "prediction", "positive_probability"])
        for row_id, (target, prediction, probability) in enumerate(zip(y_test, predictions, probabilities)):
            writer.writerow([row_id, int(target), int(prediction), f"{float(probability):.8f}"])

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
                "# Scikit-Learn Pipeline Proof",
                "",
                f"- seed: `{seed}`",
                f"- train rows: `{metrics['train_rows']}`",
                f"- test rows: `{metrics['test_rows']}`",
                f"- accuracy: `{metrics['accuracy']}`",
                f"- f1: `{metrics['f1']}`",
                "",
                "This preview keeps the model, predictions, metrics, and manifest together so the run can be audited later.",
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
        "example": "sklearn_pipeline_proof",
        "deterministic": True,
        "runtime": "local preview",
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
    artifacts["manifest"] = _artifact(manifest_path, role="artifact hash manifest", output_dir=output_dir)

    preview_path = output_dir / "sklearn_pipeline_preview.json"
    preview = {
        "schema": SCHEMA,
        "output_dir": str(output_dir),
        "metrics": metrics,
        "artifacts": artifacts,
        "manifest": str(manifest_path),
    }
    preview_path.write_text(json.dumps(preview, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    preview["artifacts"]["preview"] = _artifact(preview_path, role="preview summary", output_dir=output_dir)
    return preview


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a deterministic scikit-learn AGILAB proof preview.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--sample-count", type=int, default=240)
    parser.add_argument("--test-size", type=float, default=0.25)
    parser.add_argument("--regularization-c", type=float, default=1.0)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    if args.sample_count < 40:
        raise SystemExit("--sample-count must be at least 40")
    if not 0.1 <= args.test_size <= 0.5:
        raise SystemExit("--test-size must be between 0.1 and 0.5")
    if args.regularization_c <= 0:
        raise SystemExit("--regularization-c must be positive")
    preview = build_preview(
        output_dir=args.output_dir,
        seed=args.seed,
        sample_count=args.sample_count,
        test_size=args.test_size,
        regularization_c=args.regularization_c,
    )
    print(json.dumps(preview, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
