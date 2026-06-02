"""Evidence helpers for the built-in data quality gate app."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import random
from pathlib import Path
from typing import Any

import pandas as pd


SCHEMA = "agilab.app.data_quality_gate.v1"
CONTRACT_SCHEMA = "agilab.app.data_quality_gate.contract.v1"
THRESHOLDS_SCHEMA = "agilab.app.data_quality_gate.thresholds.v1"

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

DEFAULT_TARGET_COLUMN = "target"
DEFAULT_IDENTIFIER_COLUMNS = ("customer_id",)
DEFAULT_LEAKAGE_NAME_PATTERNS = ("leak", "target_proxy")


def default_contract() -> dict[str, Any]:
    """Return the default data-quality contract used by the synthetic demo."""

    columns: dict[str, dict[str, Any]] = {}
    for name, description in CONTRACT_COLUMNS.items():
        role = "feature"
        kind = "categorical" if description == "categorical" else "numeric"
        if name == DEFAULT_TARGET_COLUMN:
            role = "target"
            kind = "binary"
        elif name in DEFAULT_IDENTIFIER_COLUMNS:
            role = "identifier"
            kind = "integer"
        columns[name] = {
            "description": description,
            "drift": role == "feature",
            "kind": kind,
            "required": True,
            "role": role,
        }
    return {
        "schema": CONTRACT_SCHEMA,
        "allow_unexpected_columns": False,
        "columns": columns,
        "identifier_columns": list(DEFAULT_IDENTIFIER_COLUMNS),
        "leakage_name_patterns": list(DEFAULT_LEAKAGE_NAME_PATTERNS),
        "target_column": DEFAULT_TARGET_COLUMN,
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


def _source_file(path: Path, *, role: str) -> dict[str, Any]:
    resolved = path.expanduser().resolve(strict=False)
    return {
        "path": str(resolved),
        "role": role,
        "bytes": resolved.stat().st_size,
        "sha256": _sha256(resolved),
    }


def _optional_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid {label} JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON in {path} must be an object")
    return payload


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _normalize_column_spec(name: str, raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = {"kind": raw}
    if not isinstance(raw, dict):
        raw = {}
    role = str(raw.get("role") or ("target" if name == DEFAULT_TARGET_COLUMN else "feature")).strip().lower()
    if name in DEFAULT_IDENTIFIER_COLUMNS and "role" not in raw:
        role = "identifier"
    kind = str(raw.get("kind") or ("binary" if role == "target" else "numeric")).strip().lower()
    required = _coerce_bool(raw.get("required"), default=True)
    drift = _coerce_bool(raw.get("drift"), default=role == "feature")
    return {
        "description": str(raw.get("description") or kind),
        "drift": drift,
        "kind": kind,
        "required": required,
        "role": role,
    }


def _normalize_contract(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    base = default_contract()
    if not payload:
        return base

    raw_columns = payload.get("columns") or payload.get("expected_columns")
    if isinstance(raw_columns, list):
        raw_columns = {str(name): {"kind": "numeric"} for name in raw_columns}
    if isinstance(raw_columns, dict):
        base["columns"] = {
            str(name): _normalize_column_spec(str(name), raw)
            for name, raw in sorted(raw_columns.items(), key=lambda item: str(item[0]))
        }
    base["allow_unexpected_columns"] = _coerce_bool(
        payload.get("allow_unexpected_columns"),
        default=bool(base["allow_unexpected_columns"]),
    )
    if isinstance(payload.get("target_column"), str) and payload["target_column"].strip():
        base["target_column"] = payload["target_column"].strip()
    raw_identifiers = payload.get("identifier_columns")
    if isinstance(raw_identifiers, str):
        raw_identifiers = [raw_identifiers]
    if isinstance(raw_identifiers, list):
        base["identifier_columns"] = [str(value).strip() for value in raw_identifiers if str(value).strip()]
    raw_patterns = payload.get("leakage_name_patterns")
    if isinstance(raw_patterns, str):
        raw_patterns = [raw_patterns]
    if isinstance(raw_patterns, list):
        base["leakage_name_patterns"] = [str(value).strip() for value in raw_patterns if str(value).strip()]
    return base


def _normalize_thresholds(payload: dict[str, Any] | None = None) -> dict[str, float]:
    thresholds = {key: float(value) for key, value in THRESHOLDS.items()}
    thresholds.update(_threshold_updates(payload))
    return thresholds


def _threshold_updates(payload: dict[str, Any] | None = None) -> dict[str, float]:
    updates: dict[str, float] = {}
    if not payload:
        return updates
    raw_thresholds = payload.get("thresholds") if isinstance(payload.get("thresholds"), dict) else payload
    for key, value in raw_thresholds.items():
        if key not in THRESHOLDS:
            continue
        try:
            updates[key] = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Threshold {key!r} must be numeric") from exc
    return updates


def _load_gate_configuration(
    *,
    contract_json: str | Path | None,
    thresholds_json: str | Path | None,
) -> tuple[dict[str, Any], dict[str, float], dict[str, dict[str, Any]]]:
    contract_sources: dict[str, dict[str, Any]] = {}
    raw_contract: dict[str, Any] | None = None
    contract_path = _optional_path(contract_json)
    if contract_path is not None:
        raw_contract = _read_json(contract_path, label="contract")
        contract_sources["contract_json"] = _source_file(contract_path, role="contract configuration")

    contract = _normalize_contract(raw_contract)
    thresholds = _normalize_thresholds(raw_contract.get("thresholds") if isinstance(raw_contract, dict) else None)
    thresholds_path = _optional_path(thresholds_json)
    if thresholds_path is not None:
        raw_thresholds = _read_json(thresholds_path, label="thresholds")
        thresholds.update(_threshold_updates(raw_thresholds))
        contract_sources["thresholds_json"] = _source_file(thresholds_path, role="threshold configuration")
    return contract, thresholds, contract_sources


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
    thresholds: dict[str, float],
) -> tuple[str, str]:
    if (
        psi >= thresholds["psi_block"]
        or ks_statistic >= thresholds["ks_block"]
        or mean_shift_std >= thresholds["mean_shift_block"]
        or max_category_delta >= thresholds["category_delta_block"]
    ):
        return "block", "drift exceeds block threshold"
    if (
        psi >= thresholds["psi_warn"]
        or ks_statistic >= thresholds["ks_warn"]
        or mean_shift_std >= thresholds["mean_shift_warn"]
        or max_category_delta >= thresholds["category_delta_warn"]
    ):
        return "warn", "drift exceeds review threshold"
    return "pass", "within drift thresholds"


def _drift_columns(contract: dict[str, Any]) -> list[str]:
    columns = contract.get("columns", {})
    if not isinstance(columns, dict):
        return []
    return [
        str(name)
        for name, spec in columns.items()
        if isinstance(spec, dict) and spec.get("drift") is True and spec.get("role") not in {"identifier", "target"}
    ]


def _drift_rows(
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
    *,
    contract: dict[str, Any],
    thresholds: dict[str, float],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    common_columns = [column for column in _drift_columns(contract) if column in baseline.columns and column in candidate.columns]
    for column in common_columns:
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
            thresholds=thresholds,
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


def _leakage_columns(candidate: pd.DataFrame, *, contract: dict[str, Any]) -> list[str]:
    patterns = contract.get("leakage_name_patterns") or list(DEFAULT_LEAKAGE_NAME_PATTERNS)
    target_column = str(contract.get("target_column") or DEFAULT_TARGET_COLUMN)
    identifier_columns = {str(value) for value in contract.get("identifier_columns", [])}
    suspicious = [
        column
        for column in candidate.columns
        if any(pattern and pattern.lower() in column.lower() for pattern in patterns)
    ]
    if target_column not in candidate.columns:
        return sorted(suspicious)
    target = candidate[target_column]
    for column in candidate.columns:
        if column == target_column or column in identifier_columns or not pd.api.types.is_numeric_dtype(candidate[column]):
            continue
        try:
            correlation = abs(float(candidate[column].corr(target)))
        except (TypeError, ValueError):
            correlation = 0.0
        if correlation >= 0.98:
            suspicious.append(column)
    return sorted(set(suspicious))


def _type_issues(frame: pd.DataFrame, *, frame_name: str, contract: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    columns = contract.get("columns", {})
    if not isinstance(columns, dict):
        return issues
    for column, spec in sorted(columns.items()):
        if column not in frame.columns or not isinstance(spec, dict):
            continue
        kind = str(spec.get("kind", "")).lower()
        if kind in {"numeric", "integer", "float", "binary"} and not pd.api.types.is_numeric_dtype(frame[column]):
            issues.append(f"{frame_name}.{column} expected numeric-compatible data, got {frame[column].dtype}")
    return issues


def _contract_result(
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
    *,
    contract: dict[str, Any],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    columns = contract.get("columns", {})
    columns = columns if isinstance(columns, dict) else {}
    expected = {name for name, spec in columns.items() if isinstance(spec, dict) and spec.get("required") is True}
    defined = set(columns)
    candidate_columns = set(candidate.columns)
    missing = sorted(expected - candidate_columns)
    unexpected = sorted(candidate_columns - defined)
    baseline_columns = set(baseline.columns)
    return {
        "allow_unexpected_columns": bool(contract.get("allow_unexpected_columns")),
        "expected_columns": columns,
        "missing_columns": missing,
        "unexpected_columns": [] if contract.get("allow_unexpected_columns") else unexpected,
        "observed_unexpected_columns": unexpected,
        "baseline_missing_columns": sorted(expected - baseline_columns),
        "type_issues": [
            *_type_issues(baseline, frame_name="baseline", contract=contract),
            *_type_issues(candidate, frame_name="candidate", contract=contract),
        ],
        "thresholds": thresholds,
    }


def _gate_decision(
    *,
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
    contract: dict[str, Any],
    drift_rows: list[dict[str, Any]],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    if contract["missing_columns"]:
        blockers.append("missing required columns: " + ", ".join(contract["missing_columns"]))
    if contract["baseline_missing_columns"]:
        blockers.append("baseline missing required columns: " + ", ".join(contract["baseline_missing_columns"]))
    if contract["unexpected_columns"]:
        blockers.append("unexpected columns: " + ", ".join(contract["unexpected_columns"]))
    if contract["type_issues"]:
        blockers.extend(contract["type_issues"])

    null_rate = float(candidate.isna().mean().max()) if len(candidate.columns) else 0.0
    duplicate_rate = float(candidate.duplicated().mean()) if len(candidate) else 0.0
    row_count_delta = abs(len(candidate) - len(baseline)) / max(1, len(baseline))
    if null_rate > thresholds["max_null_rate"]:
        blockers.append(f"null rate {null_rate:.3f} exceeds threshold")
    if duplicate_rate > thresholds["max_duplicate_rate"]:
        blockers.append(f"duplicate rate {duplicate_rate:.3f} exceeds threshold")
    if row_count_delta > thresholds["max_row_count_delta"]:
        warnings.append(f"row count delta {row_count_delta:.3f} exceeds review threshold")

    leakage_columns = _leakage_columns(candidate, contract=contract)
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


def _recommended_action(decision: str) -> str:
    if decision == "promote":
        return "Promote the candidate data to the next workflow step."
    if decision == "manual-review":
        return "Hold promotion until an owner reviews drift and row-count warnings."
    return "Block promotion until blockers are fixed and the gate is rerun."


def _risk_score(decision: dict[str, Any]) -> int:
    base = len(decision["blockers"]) * 35 + len(decision["warnings"]) * 12
    drift = decision["drift"]
    base += int(float(drift["max_psi"]) * 100)
    base += int(float(drift["max_ks_statistic"]) * 40)
    return max(0, min(100, base))


def _decision_card(decision: dict[str, Any], drift_rows: list[dict[str, Any]], *, input_mode: str) -> dict[str, Any]:
    top_rows = sorted(drift_rows, key=lambda row: (row["severity"] == "pass", -float(row["psi"])))[:5]
    return {
        "schema": SCHEMA,
        "decision": decision["decision"],
        "input_mode": input_mode,
        "recommended_action": _recommended_action(decision["decision"]),
        "risk_score": _risk_score(decision),
        "blocker_count": len(decision["blockers"]),
        "warning_count": len(decision["warnings"]),
        "quality": decision["quality"],
        "drift": decision["drift"],
        "top_drift_signals": top_rows,
    }


def _write_report(
    path: Path,
    *,
    decision: dict[str, Any],
    drift_rows: list[dict[str, Any]],
    input_mode: str,
    contract: dict[str, Any],
) -> None:
    top_rows = sorted(drift_rows, key=lambda row: (row["severity"] != "block", -float(row["psi"])))[:5]
    lines = [
        "# Data Quality Gate Evidence",
        "",
        f"- input mode: `{input_mode}`",
        f"- decision: `{decision['decision']}`",
        f"- recommended action: {decision['recommended_action']}",
        f"- blockers: `{len(decision['blockers'])}`",
        f"- warnings: `{len(decision['warnings'])}`",
        f"- max PSI: `{decision['drift']['max_psi']}`",
        f"- max KS statistic: `{decision['drift']['max_ks_statistic']}`",
        f"- contract columns: `{len(contract.get('expected_columns', {}))}`",
        "",
        "## Blockers",
        "",
        *(f"- {blocker}" for blocker in decision["blockers"]),
        *([] if decision["blockers"] else ["- none"]),
        "",
        "## Warnings",
        "",
        *(f"- {warning}" for warning in decision["warnings"]),
        *([] if decision["warnings"] else ["- none"]),
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


def _write_dashboard(
    path: Path,
    *,
    decision_card: dict[str, Any],
    drift_rows: list[dict[str, Any]],
    contract: dict[str, Any],
) -> None:
    badge_color = {"promote": "#137333", "manual-review": "#b06000", "block": "#b42318"}.get(
        str(decision_card["decision"]),
        "#334155",
    )
    rows_html = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row['feature']))}</td>"
        f"<td>{html.escape(str(row['kind']))}</td>"
        f"<td>{html.escape(str(row['severity']))}</td>"
        f"<td>{float(row['psi']):.4f}</td>"
        f"<td>{float(row['ks_statistic']):.4f}</td>"
        f"<td>{float(row['mean_shift_std']):.4f}</td>"
        f"<td>{float(row['max_category_delta']):.4f}</td>"
        "</tr>"
        for row in sorted(drift_rows, key=lambda item: (item["severity"] == "pass", -float(item["psi"])))
    )
    blocker_items = "\n".join(
        f"<li>{html.escape(str(value))}</li>" for value in decision_card.get("blockers", [])
    ) or "<li>none</li>"
    warning_items = "\n".join(
        f"<li>{html.escape(str(value))}</li>" for value in decision_card.get("warnings", [])
    ) or "<li>none</li>"
    content = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Data Quality Gate</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 2rem; color: #172033; }}
    .hero {{ border: 1px solid #d7dee8; border-radius: 18px; padding: 1.4rem; background: #f8fafc; }}
    .decision {{ display: inline-block; background: {badge_color}; color: white; border-radius: 999px; padding: .25rem .75rem; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .8rem; margin: 1rem 0; }}
    .card {{ border: 1px solid #d7dee8; border-radius: 14px; padding: .9rem; background: white; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
    th, td {{ border-bottom: 1px solid #e5e9f0; padding: .45rem; text-align: left; }}
    th {{ background: #eef3f8; }}
  </style>
</head>
<body>
  <section class="hero">
    <h1>Data Quality Gate</h1>
    <p class="decision">{html.escape(str(decision_card["decision"]))}</p>
    <p>{html.escape(str(decision_card["recommended_action"]))}</p>
  </section>
  <section class="grid">
    <div class="card"><strong>Input mode</strong><br>{html.escape(str(decision_card["input_mode"]))}</div>
    <div class="card"><strong>Risk score</strong><br>{int(decision_card["risk_score"])}/100</div>
    <div class="card"><strong>Max PSI</strong><br>{float(decision_card["drift"]["max_psi"]):.4f}</div>
    <div class="card"><strong>Max KS</strong><br>{float(decision_card["drift"]["max_ks_statistic"]):.4f}</div>
  </section>
  <h2>Blockers</h2>
  <ul>{blocker_items}</ul>
  <h2>Warnings</h2>
  <ul>{warning_items}</ul>
  <h2>Drift signals</h2>
  <table>
    <thead><tr><th>Feature</th><th>Kind</th><th>Severity</th><th>PSI</th><th>KS</th><th>Mean shift</th><th>Category delta</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  <p>Contract columns: {len(contract.get("expected_columns", {}))}. This dashboard is a local evidence artifact, not a production certification.</p>
</body>
</html>
"""
    path.write_text(content, encoding="utf-8")


def _load_or_generate_frames(
    *,
    baseline_csv: str | Path | None,
    candidate_csv: str | Path | None,
    baseline_rows: int,
    candidate_rows: int,
    drift_strength: float,
    seed: int,
    include_quality_issues: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, str, dict[str, dict[str, Any]]]:
    baseline_path = _optional_path(baseline_csv)
    candidate_path = _optional_path(candidate_csv)
    if bool(baseline_path) != bool(candidate_path):
        raise ValueError("baseline_csv and candidate_csv must be provided together")
    if baseline_path and candidate_path:
        if not baseline_path.is_file():
            raise FileNotFoundError(f"baseline_csv not found: {baseline_path}")
        if not candidate_path.is_file():
            raise FileNotFoundError(f"candidate_csv not found: {candidate_path}")
        sources = {
            "baseline_csv": _source_file(baseline_path, role="baseline input CSV"),
            "candidate_csv": _source_file(candidate_path, role="candidate input CSV"),
        }
        return pd.read_csv(baseline_path), pd.read_csv(candidate_path), "csv", sources

    baseline, candidate = generate_reference_frames(
        baseline_rows=baseline_rows,
        candidate_rows=candidate_rows,
        drift_strength=drift_strength,
        seed=seed,
        include_quality_issues=include_quality_issues,
    )
    return baseline, candidate, "synthetic", {}


def build_data_quality_gate_artifacts(
    *,
    output_dir: Path,
    baseline_csv: str | Path | None = None,
    candidate_csv: str | Path | None = None,
    contract_json: str | Path | None = None,
    thresholds_json: str | Path | None = None,
    baseline_rows: int = 240,
    candidate_rows: int = 220,
    drift_strength: float = 0.35,
    seed: int = 2026,
    include_quality_issues: bool = False,
) -> dict[str, Any]:
    """Build deterministic data-quality evidence and write an audit bundle."""

    output_dir = output_dir.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline, candidate, input_mode, input_sources = _load_or_generate_frames(
        baseline_csv=baseline_csv,
        candidate_csv=candidate_csv,
        baseline_rows=baseline_rows,
        candidate_rows=candidate_rows,
        drift_strength=drift_strength,
        seed=seed,
        include_quality_issues=include_quality_issues,
    )
    contract, thresholds, config_sources = _load_gate_configuration(
        contract_json=contract_json,
        thresholds_json=thresholds_json,
    )
    input_sources.update(config_sources)

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
    contract_result = _contract_result(
        baseline,
        candidate,
        contract=contract,
        thresholds=thresholds,
    )
    contract_path.write_text(json.dumps(contract_result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    drift_rows = _drift_rows(baseline, candidate, contract=contract, thresholds=thresholds)
    drift_path = output_dir / "drift_metrics.csv"
    _write_csv(drift_path, drift_rows)

    decision = _gate_decision(
        baseline=baseline,
        candidate=candidate,
        contract=contract_result,
        drift_rows=drift_rows,
        thresholds=thresholds,
    )
    decision["recommended_action"] = _recommended_action(decision["decision"])
    decision["risk_score"] = _risk_score(decision)
    decision_path = output_dir / "gate_decision.json"
    decision_path.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    decision_card = _decision_card(decision, drift_rows, input_mode=input_mode)
    decision_card["blockers"] = decision["blockers"]
    decision_card["warnings"] = decision["warnings"]
    decision_card_path = output_dir / "decision_card.json"
    decision_card_path.write_text(json.dumps(decision_card, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report_path = output_dir / "data_quality_report.md"
    _write_report(
        report_path,
        decision=decision,
        drift_rows=drift_rows,
        input_mode=input_mode,
        contract=contract_result,
    )

    dashboard_path = output_dir / "data_quality_dashboard.html"
    _write_dashboard(dashboard_path, decision_card=decision_card, drift_rows=drift_rows, contract=contract_result)

    input_sources_path = output_dir / "input_sources.json"
    input_sources_path.write_text(json.dumps(input_sources, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    artifacts = {
        "baseline": _artifact(baseline_path, role="baseline dataset", output_dir=output_dir),
        "candidate": _artifact(candidate_path, role="candidate dataset", output_dir=output_dir),
        "baseline_profile": _artifact(baseline_profile_path, role="baseline profile", output_dir=output_dir),
        "candidate_profile": _artifact(candidate_profile_path, role="candidate profile", output_dir=output_dir),
        "contract": _artifact(contract_path, role="data contract", output_dir=output_dir),
        "drift_metrics": _artifact(drift_path, role="drift metrics", output_dir=output_dir),
        "gate_decision": _artifact(decision_path, role="gate decision", output_dir=output_dir),
        "decision_card": _artifact(decision_card_path, role="operator decision card", output_dir=output_dir),
        "report": _artifact(report_path, role="human-readable evidence summary", output_dir=output_dir),
        "dashboard": _artifact(dashboard_path, role="self-contained HTML dashboard", output_dir=output_dir),
        "input_sources": _artifact(input_sources_path, role="input and configuration source hashes", output_dir=output_dir),
    }
    manifest_path = output_dir / "run_manifest.json"
    manifest = {
        "schema": SCHEMA,
        "app": "data_quality_gate_project",
        "deterministic": True,
        "runtime": "agi worker",
        "inputs": {
            "baseline_csv": str(baseline_csv or ""),
            "baseline_rows": baseline_rows,
            "candidate_csv": str(candidate_csv or ""),
            "candidate_rows": candidate_rows,
            "contract_json": str(contract_json or ""),
            "drift_strength": drift_strength,
            "seed": seed,
            "include_quality_issues": include_quality_issues,
            "input_mode": input_mode,
            "thresholds_json": str(thresholds_json or ""),
        },
        "input_sources": input_sources,
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
        "input_mode": input_mode,
        "recommended_action": decision["recommended_action"],
        "risk_score": decision["risk_score"],
        "quality": decision["quality"],
        "drift": decision["drift"],
        "artifacts": summary_artifacts,
        "decision_card": str(decision_card_path),
        "manifest": str(manifest_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


__all__ = [
    "CONTRACT_COLUMNS",
    "CONTRACT_SCHEMA",
    "SCHEMA",
    "THRESHOLDS",
    "THRESHOLDS_SCHEMA",
    "build_data_quality_gate_artifacts",
    "default_contract",
    "generate_reference_frames",
]
