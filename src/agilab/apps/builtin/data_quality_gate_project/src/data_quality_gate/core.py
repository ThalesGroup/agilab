"""Evidence helpers for the built-in data quality gate app."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

import pandas as pd


SCHEMA = "agilab.app.data_quality_gate.v1"

CONTRACT_COLUMNS: dict[str, str] = {
    "customer_id": "integer identifier",
    "age": "numeric",
    "income": "numeric",
    "risk_score": "numeric",
    "segment": "categorical",
    "region": "categorical",
    "target": "binary integer label",
}

THRESHOLDS: dict[str, float | int] = {
    "max_null_rate": 0.02,
    "max_duplicate_rate": 0.05,
    "max_row_count_delta": 0.15,
    "psi_warn": 0.08,
    "psi_block": 0.30,
    "ks_warn": 0.18,
    "ks_block": 0.45,
    "mean_shift_warn": 0.25,
    "mean_shift_block": 0.75,
    "category_delta_warn": 0.10,
    "category_delta_block": 0.25,
}


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


def _weighted_choice(rng: random.Random, choices: list[tuple[str, float]]) -> str:
    total = sum(weight for _value, weight in choices)
    marker = rng.random() * total
    running = 0.0
    for value, weight in choices:
        running += weight
        if marker <= running:
            return value
    return choices[-1][0]


def _bounded(value: float, *, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _generate_dataset(
    *,
    rows: int,
    seed: int,
    drift_strength: float,
    include_quality_issues: bool,
) -> pd.DataFrame:
    rng = random.Random(seed)
    records: list[dict[str, Any]] = []
    for row_id in range(rows):
        enterprise_weight = 0.28 + 0.22 * drift_strength
        public_weight = 0.24 - 0.10 * drift_strength
        segment = _weighted_choice(
            rng,
            [
                ("small_business", 0.30),
                ("enterprise", enterprise_weight),
                ("public", max(0.08, public_weight)),
                ("consumer", 0.18),
            ],
        )
        region = _weighted_choice(
            rng,
            [
                ("north", 0.32 - 0.08 * drift_strength),
                ("south", 0.18 + 0.14 * drift_strength),
                ("east", 0.26),
                ("west", 0.24 - 0.06 * drift_strength),
            ],
        )
        age = int(round(_bounded(rng.gauss(42 + 5.0 * drift_strength, 9.0), lower=18, upper=82)))
        income = int(round(_bounded(rng.gauss(72_000 + 14_000 * drift_strength, 18_000), lower=24_000, upper=180_000)))
        risk_score = round(_bounded(rng.gauss(0.48 + 0.13 * drift_strength, 0.16), lower=0.01, upper=0.99), 4)
        decision_score = (
            0.55 * risk_score
            + 0.0018 * (age - 40)
            + 0.0000015 * (income - 70_000)
            + (0.035 if segment == "enterprise" else 0.0)
            + rng.gauss(0, 0.055)
        )
        records.append(
            {
                "customer_id": row_id + 1,
                "age": age,
                "income": income,
                "risk_score": risk_score,
                "segment": segment,
                "region": region,
                "target": int(decision_score >= 0.52),
            }
        )

    frame = pd.DataFrame.from_records(records, columns=list(CONTRACT_COLUMNS))
    if include_quality_issues and not frame.empty:
        frame.loc[frame.index[::37], "risk_score"] = None
        duplicates = frame.head(max(1, rows // 40)).copy()
        frame = pd.concat([frame, duplicates], ignore_index=True)
        frame["target_proxy_leakage"] = frame["target"]
    return frame


def generate_reference_frames(
    *,
    baseline_rows: int,
    candidate_rows: int,
    drift_strength: float,
    seed: int,
    include_quality_issues: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build deterministic baseline and candidate frames for the gate."""

    baseline = _generate_dataset(
        rows=baseline_rows,
        seed=seed,
        drift_strength=0.0,
        include_quality_issues=False,
    )
    candidate = _generate_dataset(
        rows=candidate_rows,
        seed=seed + 17,
        drift_strength=drift_strength,
        include_quality_issues=include_quality_issues,
    )
    return baseline, candidate


def _series_profile(series: pd.Series) -> dict[str, Any]:
    null_count = int(series.isna().sum())
    payload: dict[str, Any] = {
        "dtype": str(series.dtype),
        "null_count": null_count,
        "null_rate": round(null_count / max(1, len(series)), 6),
        "unique_count": int(series.nunique(dropna=True)),
    }
    if pd.api.types.is_numeric_dtype(series):
        clean = series.dropna()
        payload["kind"] = "numeric"
        payload["min"] = None if clean.empty else round(float(clean.min()), 6)
        payload["max"] = None if clean.empty else round(float(clean.max()), 6)
        payload["mean"] = None if clean.empty else round(float(clean.mean()), 6)
        payload["std"] = None if clean.empty else round(float(clean.std(ddof=0)), 6)
    else:
        payload["kind"] = "categorical"
        payload["top_values"] = {
            str(key): int(value)
            for key, value in series.fillna("<NA>").value_counts().head(5).sort_index().items()
        }
    return payload


def _profile_frame(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "duplicate_rate": round(float(frame.duplicated().mean()) if len(frame) else 0.0, 6),
        "columns": {column: _series_profile(frame[column]) for column in sorted(frame.columns)},
    }


def _proportion(count: float, total: float) -> float:
    return (count + 1e-9) / (total + 1e-9)


def _psi(base_parts: list[float], candidate_parts: list[float]) -> float:
    total = 0.0
    for base_part, candidate_part in zip(base_parts, candidate_parts):
        base_value = max(base_part, 1e-9)
        candidate_value = max(candidate_part, 1e-9)
        total += (candidate_value - base_value) * math.log(candidate_value / base_value)
    return round(float(total), 6)


def _numeric_psi(base: pd.Series, candidate: pd.Series) -> float:
    base_clean = base.dropna().astype(float)
    candidate_clean = candidate.dropna().astype(float)
    if base_clean.empty or candidate_clean.empty:
        return 0.0
    quantiles = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    edges = sorted({float(base_clean.quantile(q)) for q in quantiles})
    if len(edges) < 2:
        return 0.0
    edges[0] = -math.inf
    edges[-1] = math.inf
    base_counts = pd.cut(base_clean, edges, include_lowest=True).value_counts(sort=False)
    candidate_counts = pd.cut(candidate_clean, edges, include_lowest=True).value_counts(sort=False)
    base_parts = [_proportion(float(value), float(len(base_clean))) for value in base_counts]
    candidate_parts = [_proportion(float(value), float(len(candidate_clean))) for value in candidate_counts]
    return _psi(base_parts, candidate_parts)


def _categorical_psi(base: pd.Series, candidate: pd.Series) -> tuple[float, float]:
    base_values = base.fillna("<NA>").astype(str)
    candidate_values = candidate.fillna("<NA>").astype(str)
    categories = sorted(set(base_values.unique()) | set(candidate_values.unique()))
    base_counts = base_values.value_counts()
    candidate_counts = candidate_values.value_counts()
    base_parts = [_proportion(float(base_counts.get(category, 0)), float(len(base_values))) for category in categories]
    candidate_parts = [
        _proportion(float(candidate_counts.get(category, 0)), float(len(candidate_values))) for category in categories
    ]
    max_delta = max((abs(a - b) for a, b in zip(base_parts, candidate_parts)), default=0.0)
    return _psi(base_parts, candidate_parts), round(float(max_delta), 6)


def _ks_statistic(base: pd.Series, candidate: pd.Series) -> float:
    base_values = sorted(float(value) for value in base.dropna())
    candidate_values = sorted(float(value) for value in candidate.dropna())
    if not base_values or not candidate_values:
        return 0.0
    values = sorted(set(base_values) | set(candidate_values))
    base_index = 0
    candidate_index = 0
    max_delta = 0.0
    for value in values:
        while base_index < len(base_values) and base_values[base_index] <= value:
            base_index += 1
        while candidate_index < len(candidate_values) and candidate_values[candidate_index] <= value:
            candidate_index += 1
        delta = abs(base_index / len(base_values) - candidate_index / len(candidate_values))
        max_delta = max(max_delta, delta)
    return round(float(max_delta), 6)


def _severity(
    *,
    psi: float,
    ks_statistic: float,
    mean_shift_std: float,
    max_category_delta: float,
) -> tuple[str, str]:
    if (
        psi >= float(THRESHOLDS["psi_block"])
        or ks_statistic >= float(THRESHOLDS["ks_block"])
        or mean_shift_std >= float(THRESHOLDS["mean_shift_block"])
        or max_category_delta >= float(THRESHOLDS["category_delta_block"])
    ):
        return "block", "drift exceeds block threshold"
    if (
        psi >= float(THRESHOLDS["psi_warn"])
        or ks_statistic >= float(THRESHOLDS["ks_warn"])
        or mean_shift_std >= float(THRESHOLDS["mean_shift_warn"])
        or max_category_delta >= float(THRESHOLDS["category_delta_warn"])
    ):
        return "warn", "drift exceeds review threshold"
    return "pass", "within drift thresholds"


def _drift_rows(baseline: pd.DataFrame, candidate: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    common_columns = [column for column in CONTRACT_COLUMNS if column in baseline.columns and column in candidate.columns]
    for column in common_columns:
        if column in {"customer_id", "target"}:
            continue
        base = baseline[column]
        current = candidate[column]
        kind = "numeric" if pd.api.types.is_numeric_dtype(base) and pd.api.types.is_numeric_dtype(current) else "categorical"
        psi = 0.0
        ks_statistic = 0.0
        mean_delta = 0.0
        mean_shift_std = 0.0
        max_category_delta = 0.0
        if kind == "numeric":
            psi = _numeric_psi(base, current)
            ks_statistic = _ks_statistic(base, current)
            base_mean = float(base.dropna().mean()) if not base.dropna().empty else 0.0
            current_mean = float(current.dropna().mean()) if not current.dropna().empty else 0.0
            base_std = float(base.dropna().std(ddof=0)) if not base.dropna().empty else 0.0
            mean_delta = round(current_mean - base_mean, 6)
            mean_shift_std = round(abs(mean_delta) / base_std, 6) if base_std else 0.0
        else:
            psi, max_category_delta = _categorical_psi(base, current)
        severity, reason = _severity(
            psi=psi,
            ks_statistic=ks_statistic,
            mean_shift_std=mean_shift_std,
            max_category_delta=max_category_delta,
        )
        rows.append(
            {
                "feature": column,
                "kind": kind,
                "psi": psi,
                "ks_statistic": ks_statistic,
                "mean_delta": mean_delta,
                "mean_shift_std": mean_shift_std,
                "max_category_delta": max_category_delta,
                "severity": severity,
                "reason": reason,
            }
        )
    return rows


def _leakage_columns(candidate: pd.DataFrame) -> list[str]:
    suspicious = [column for column in candidate.columns if "leak" in column.lower() or "target_proxy" in column.lower()]
    if "target" not in candidate.columns:
        return sorted(suspicious)
    target = candidate["target"]
    for column in candidate.columns:
        if column in {"target", "customer_id"} or not pd.api.types.is_numeric_dtype(candidate[column]):
            continue
        try:
            correlation = abs(float(candidate[column].corr(target)))
        except (TypeError, ValueError):
            correlation = 0.0
        if correlation >= 0.98:
            suspicious.append(column)
    return sorted(set(suspicious))


def _contract_result(baseline: pd.DataFrame, candidate: pd.DataFrame) -> dict[str, Any]:
    expected = set(CONTRACT_COLUMNS)
    candidate_columns = set(candidate.columns)
    missing = sorted(expected - candidate_columns)
    unexpected = sorted(candidate_columns - expected)
    baseline_columns = set(baseline.columns)
    return {
        "expected_columns": CONTRACT_COLUMNS,
        "missing_columns": missing,
        "unexpected_columns": unexpected,
        "baseline_missing_columns": sorted(expected - baseline_columns),
        "thresholds": THRESHOLDS,
    }


def _gate_decision(
    *,
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
    contract: dict[str, Any],
    drift_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    if contract["missing_columns"]:
        blockers.append("missing required columns: " + ", ".join(contract["missing_columns"]))
    if contract["unexpected_columns"]:
        blockers.append("unexpected columns: " + ", ".join(contract["unexpected_columns"]))

    null_rate = float(candidate.isna().mean().max()) if len(candidate.columns) else 0.0
    duplicate_rate = float(candidate.duplicated().mean()) if len(candidate) else 0.0
    row_count_delta = abs(len(candidate) - len(baseline)) / max(1, len(baseline))
    if null_rate > float(THRESHOLDS["max_null_rate"]):
        blockers.append(f"null rate {null_rate:.3f} exceeds threshold")
    if duplicate_rate > float(THRESHOLDS["max_duplicate_rate"]):
        blockers.append(f"duplicate rate {duplicate_rate:.3f} exceeds threshold")
    if row_count_delta > float(THRESHOLDS["max_row_count_delta"]):
        warnings.append(f"row count delta {row_count_delta:.3f} exceeds review threshold")

    leakage_columns = _leakage_columns(candidate)
    if leakage_columns:
        blockers.append("potential leakage columns: " + ", ".join(leakage_columns))

    for row in drift_rows:
        if row["severity"] == "block":
            blockers.append(f"{row['feature']} drift blocks promotion")
        elif row["severity"] == "warn":
            warnings.append(f"{row['feature']} drift needs review")

    decision = "block" if blockers else "manual-review" if warnings else "promote"
    return {
        "schema": SCHEMA,
        "decision": decision,
        "blockers": blockers,
        "warnings": warnings,
        "quality": {
            "candidate_null_rate_max": round(null_rate, 6),
            "candidate_duplicate_rate": round(duplicate_rate, 6),
            "row_count_delta": round(row_count_delta, 6),
            "leakage_columns": leakage_columns,
        },
        "drift": {
            "warn_feature_count": sum(1 for row in drift_rows if row["severity"] == "warn"),
            "block_feature_count": sum(1 for row in drift_rows if row["severity"] == "block"),
            "max_psi": max((float(row["psi"]) for row in drift_rows), default=0.0),
            "max_ks_statistic": max((float(row["ks_statistic"]) for row in drift_rows), default=0.0),
        },
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "feature",
        "kind",
        "psi",
        "ks_statistic",
        "mean_delta",
        "mean_shift_std",
        "max_category_delta",
        "severity",
        "reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_report(path: Path, *, decision: dict[str, Any], drift_rows: list[dict[str, Any]]) -> None:
    top_rows = sorted(drift_rows, key=lambda row: (row["severity"] != "block", -float(row["psi"])))[:5]
    lines = [
        "# Data Quality Gate Evidence",
        "",
        f"- decision: `{decision['decision']}`",
        f"- blockers: `{len(decision['blockers'])}`",
        f"- warnings: `{len(decision['warnings'])}`",
        f"- max PSI: `{decision['drift']['max_psi']}`",
        f"- max KS statistic: `{decision['drift']['max_ks_statistic']}`",
        "",
        "## Top drift signals",
        "",
    ]
    for row in top_rows:
        lines.append(
            f"- `{row['feature']}`: `{row['severity']}` "
            f"(PSI `{row['psi']}`, KS `{row['ks_statistic']}`, reason: {row['reason']})"
        )
    lines.extend(
        [
            "",
            "The gate is deterministic and local. It does not call external services or certify production use.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def build_data_quality_gate_artifacts(
    *,
    output_dir: Path,
    baseline_rows: int = 240,
    candidate_rows: int = 220,
    drift_strength: float = 0.35,
    seed: int = 2026,
    include_quality_issues: bool = False,
) -> dict[str, Any]:
    """Build deterministic data-quality evidence and write an audit bundle."""

    output_dir = output_dir.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline, candidate = generate_reference_frames(
        baseline_rows=baseline_rows,
        candidate_rows=candidate_rows,
        drift_strength=drift_strength,
        seed=seed,
        include_quality_issues=include_quality_issues,
    )

    baseline_path = output_dir / "baseline.csv"
    candidate_path = output_dir / "candidate.csv"
    baseline.to_csv(baseline_path, index=False)
    candidate.to_csv(candidate_path, index=False)

    baseline_profile_path = output_dir / "baseline_profile.json"
    candidate_profile_path = output_dir / "candidate_profile.json"
    baseline_profile = _profile_frame(baseline)
    candidate_profile = _profile_frame(candidate)
    baseline_profile_path.write_text(json.dumps(baseline_profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    candidate_profile_path.write_text(
        json.dumps(candidate_profile, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    contract_path = output_dir / "data_contract.json"
    contract = _contract_result(baseline, candidate)
    contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    drift_rows = _drift_rows(baseline, candidate)
    drift_path = output_dir / "drift_metrics.csv"
    _write_csv(drift_path, drift_rows)

    decision = _gate_decision(
        baseline=baseline,
        candidate=candidate,
        contract=contract,
        drift_rows=drift_rows,
    )
    decision_path = output_dir / "gate_decision.json"
    decision_path.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report_path = output_dir / "data_quality_report.md"
    _write_report(report_path, decision=decision, drift_rows=drift_rows)

    artifacts = {
        "baseline": _artifact(baseline_path, role="baseline dataset", output_dir=output_dir),
        "candidate": _artifact(candidate_path, role="candidate dataset", output_dir=output_dir),
        "baseline_profile": _artifact(baseline_profile_path, role="baseline profile", output_dir=output_dir),
        "candidate_profile": _artifact(candidate_profile_path, role="candidate profile", output_dir=output_dir),
        "contract": _artifact(contract_path, role="data contract", output_dir=output_dir),
        "drift_metrics": _artifact(drift_path, role="drift metrics", output_dir=output_dir),
        "gate_decision": _artifact(decision_path, role="gate decision", output_dir=output_dir),
        "report": _artifact(report_path, role="human-readable evidence summary", output_dir=output_dir),
    }
    manifest_path = output_dir / "run_manifest.json"
    manifest = {
        "schema": SCHEMA,
        "app": "data_quality_gate_project",
        "deterministic": True,
        "runtime": "agi worker",
        "inputs": {
            "baseline_rows": baseline_rows,
            "candidate_rows": candidate_rows,
            "drift_strength": drift_strength,
            "seed": seed,
            "include_quality_issues": include_quality_issues,
        },
        "artifacts": artifacts,
        "decision": decision,
        "promotion_hint": decision["decision"],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary_artifacts = {
        **artifacts,
        "manifest": _artifact(manifest_path, role="artifact hash manifest", output_dir=output_dir),
    }
    summary_path = output_dir / "data_quality_gate_summary.json"
    summary = {
        "schema": SCHEMA,
        "output_dir": str(output_dir),
        "decision": decision["decision"],
        "quality": decision["quality"],
        "drift": decision["drift"],
        "artifacts": summary_artifacts,
        "manifest": str(manifest_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


__all__ = [
    "CONTRACT_COLUMNS",
    "SCHEMA",
    "THRESHOLDS",
    "build_data_quality_gate_artifacts",
    "generate_reference_frames",
]
