"""Declarative, candidate-row quality checks for the data quality gate app."""

from __future__ import annotations

from collections import Counter
from datetime import date
import math
from numbers import Integral, Real
import operator
import re
from typing import Any

import pandas as pd


RULE_RESULTS_SCHEMA = "agilab.app.data_quality_gate.rule_results.v1"
EVALUATOR_VERSION = 1
FAILURE_POSITION_LIMIT = 10
_OPERATORS = {
    "eq": operator.eq,
    "ne": operator.ne,
    "lt": operator.lt,
    "le": operator.le,
    "gt": operator.gt,
    "ge": operator.ge,
}
_FIELDS = {
    "required": set(),
    "range": {"min", "max"},
    "allowed_values": {"values"},
    "format": {"format"},
    "compare": {"other_column", "operator"},
}


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and (isinstance(value, Integral) or math.isfinite(value))
    )


def normalize_rules(raw: Any, columns: dict[str, Any]) -> list[dict[str, Any]]:
    """Reject ambiguous or unsupported rules before producing gate artifacts."""
    if not isinstance(raw, list):
        raise ValueError("Contract rules must be a list")
    normalized = []
    seen = set()
    for position, item in enumerate(raw):
        label = f"Contract rule at position {position}"
        if not isinstance(item, dict):
            raise ValueError(f"{label} must be an object")
        rule_id = item.get("id")
        if not isinstance(rule_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", rule_id
        ):
            raise ValueError(
                f"{label} requires a unique id of 1-64 letters, digits, dots, underscores or hyphens"
            )
        label = f"Contract rule {rule_id!r}"
        if rule_id in seen:
            raise ValueError(f"Duplicate contract rule id: {rule_id}")
        seen.add(rule_id)
        kind = item.get("kind")
        if not isinstance(kind, str) or kind not in _FIELDS:
            raise ValueError(f"{label} has an unsupported kind")
        extra = (
            set(item) - {"id", "kind", "column", "severity", "on_null"} - _FIELDS[kind]
        )
        if extra:
            raise ValueError(
                f"{label} has unsupported fields: {', '.join(sorted(extra))}"
            )
        column = item.get("column")
        if not isinstance(column, str) or column not in columns:
            raise ValueError(f"{label} must reference a declared column")
        severity = item.get("severity", "block")
        on_null = item.get("on_null", "fail")
        if severity not in ("block", "warn") or on_null not in ("fail", "skip"):
            raise ValueError(
                f"{label} requires severity block/warn and on_null fail/skip"
            )
        if kind == "required" and on_null != "fail":
            raise ValueError(f"{label}: required checks cannot skip nulls")
        rule = {**item, "severity": severity, "on_null": on_null}
        if kind == "range":
            bounds = [item[key] for key in ("min", "max") if key in item]
            if not bounds or not all(_finite_number(value) for value in bounds):
                raise ValueError(
                    f"{label} needs at least one finite numeric min/max bound"
                )
            if "min" in item and "max" in item and item["min"] > item["max"]:
                raise ValueError(f"{label}: min must not exceed max")
        elif kind == "allowed_values":
            values = item.get("values")
            if (
                not isinstance(values, list)
                or not values
                or not all(
                    isinstance(value, (str, bool)) or _finite_number(value)
                    for value in values
                )
            ):
                raise ValueError(
                    f"{label} needs a non-empty list of non-null scalar values"
                )
        elif kind == "format":
            if item.get("format") not in ("iso_date", "email"):
                raise ValueError(f"{label} supports format iso_date or email")
        elif kind == "compare":
            other = item.get("other_column")
            if not isinstance(other, str) or other not in columns:
                raise ValueError(f"{label} must reference a declared other_column")
            if item.get("operator") not in tuple(_OPERATORS):
                raise ValueError(f"{label} requires operator eq/ne/lt/le/gt/ge")
        normalized.append(rule)
    return sorted(normalized, key=lambda rule: rule["id"])


def _compatible(left: Any, right: Any) -> bool:
    # Preserve booleans as booleans rather than allowing True == 1.
    return (
        (_finite_number(left) and _finite_number(right))
        or (isinstance(left, str) and isinstance(right, str))
        or (isinstance(left, bool) and isinstance(right, bool))
    )


def _format_matches(value: Any, name: str) -> bool:
    if not isinstance(value, str):
        return False
    if name == "iso_date":
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            return False
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True
    # A bounded syntax check, not an RFC validator or mailbox existence check.
    if (
        len(value) > 254
        or value.count("@") != 1
        or any(char.isspace() for char in value)
    ):
        return False
    local, domain = value.split("@")
    return bool(local and domain and "." in domain and all(domain.split(".")))


def _failure(rule: dict[str, Any], value: Any, other: Any) -> str | None:
    kind = rule["kind"]
    if kind == "range":
        if not _finite_number(value):
            return "invalid_type"
        if ("min" in rule and value < rule["min"]) or (
            "max" in rule and value > rule["max"]
        ):
            return "out_of_range"
    elif kind == "allowed_values":
        if not any(
            _compatible(value, allowed) and value == allowed
            for allowed in rule["values"]
        ):
            return "not_allowed"
    elif kind == "format":
        if not _format_matches(value, rule["format"]):
            return "invalid_format"
    elif kind == "compare":
        if not _compatible(value, other):
            return "invalid_type"
        if not _OPERATORS[rule["operator"]](value, other):
            return "comparison_failed"
    return None


def evaluate_rules(frame: pd.DataFrame, rules: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate normalized rules, retaining counts and bounded row positions only."""
    results = []
    for rule in rules:
        columns = [rule["column"]]
        if rule["kind"] == "compare":
            columns.append(rule["other_column"])
        missing = sorted(set(columns) - set(frame.columns))
        result = {
            "id": rule["id"],
            "kind": rule["kind"],
            "column": rule["column"],
            "severity": rule["severity"],
            "on_null": rule["on_null"],
            "row_count": len(frame),
            "checked_count": 0,
            "passed_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "pass_rate": None,
            "failure_counts": {},
            "failed_row_positions": [],
            "omitted_failure_positions": 0,
            "missing_columns": missing,
        }
        if missing:
            result.update(
                status="missing", reason="missing_columns", skipped_count=len(frame)
            )
        else:
            failures: Counter[str] = Counter()
            positions = []
            checked = skipped = 0
            for position, values in enumerate(
                frame[columns].itertuples(index=False, name=None)
            ):
                value, other = values[0], values[-1]
                if any(bool(pd.isna(cell)) for cell in values):
                    if rule["on_null"] == "skip":
                        skipped += 1
                        continue
                    failure = "missing_value"
                else:
                    failure = _failure(rule, value, other)
                checked += 1
                if failure:
                    failures[failure] += 1
                    if len(positions) < FAILURE_POSITION_LIMIT:
                        positions.append(position)
            failed = sum(failures.values())
            result.update(
                status="fail" if failed else "pass" if checked else "skipped",
                reason="rule_failures"
                if failed
                else "evaluated"
                if checked
                else "no_evaluated_rows",
                checked_count=checked,
                passed_count=checked - failed,
                failed_count=failed,
                skipped_count=skipped,
                pass_rate=(checked - failed) / checked if checked else None,
                failure_counts=dict(sorted(failures.items())),
                failed_row_positions=positions,
                omitted_failure_positions=failed - len(positions),
            )
        results.append(result)
    return {
        "schema": RULE_RESULTS_SCHEMA,
        "producer": "data_quality_gate.domain.quality_rules.evaluate_rules",
        "evaluator_version": EVALUATOR_VERSION,
        "dataset": "candidate",
        "row_position_basis": "zero-based candidate record order, excluding the CSV header",
        "rule_count": len(results),
        "status_counts": {
            status: sum(row["status"] == status for row in results)
            for status in ("pass", "fail", "missing", "skipped")
        },
        "rules": results,
    }
