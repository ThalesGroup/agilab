from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import pandas as pd

GENERATED_ACTIONS_KIND = "agilab.generated_dataframe_actions"
GENERATED_ACTIONS_SCHEMA_VERSION = 1

GENERATION_MODE_SAFE_ACTIONS = "safe_actions"
GENERATION_MODE_PYTHON_SNIPPET = "python_snippet"

STAGE_GENERATION_MODE_FIELD = "generation_mode"
STAGE_ACTION_CONTRACT_FIELD = "action_contract"
STAGE_ACTION_CONTRACT_SHA256_FIELD = "action_contract_sha256"
STAGE_DATAFRAME_SCHEMA_SHA256_FIELD = "dataframe_schema_sha256"
STAGE_SAFE_ACTION_PINNED_FIELD = "safe_action_pinned"

GENERATED_ACTIONS_SYSTEM_INSTRUCTIONS = """
Return ONLY a JSON object. Do not return Python code or Markdown.
The JSON object must use this exact contract:
{
  "schema_version": 1,
  "kind": "agilab.generated_dataframe_actions",
  "actions": [
    {"action": "select_columns", "columns": ["col_a", "col_b"]}
  ],
  "notes": "short optional human summary"
}
Use only documented actions. Never include code, imports, shell commands, file paths,
network calls, or arbitrary expressions. If the request cannot be represented with
the documented actions, return an empty actions list and explain why in notes.
""".strip()

_ALLOWED_ACTIONS = {
    "select_columns",
    "drop_columns",
    "rename_columns",
    "filter_rows",
    "derive_column",
    "fill_missing",
    "drop_missing",
    "sort_rows",
    "groupby_aggregate",
    "rolling_mean",
    "clip",
}
_FILTER_OPERATORS = {"eq", "ne", "gt", "ge", "lt", "le", "contains", "isin"}
_DERIVE_TRANSFORMS = {"copy", "add", "subtract", "multiply", "divide", "abs"}
_AGGREGATIONS = {"sum", "mean", "min", "max", "count"}
_ACTION_KEYS = {
    "select_columns": {"action", "columns"},
    "drop_columns": {"action", "columns"},
    "rename_columns": {"action", "mapping"},
    "filter_rows": {"action", "column", "operator", "value"},
    "derive_column": {"action", "input", "output", "transform", "value"},
    "fill_missing": {"action", "columns", "value"},
    "drop_missing": {"action", "columns"},
    "sort_rows": {"action", "columns", "ascending"},
    "groupby_aggregate": {"action", "by", "aggregations"},
    "rolling_mean": {"action", "input", "output", "window"},
    "clip": {"action", "input", "output", "lower", "upper"},
}
SAFE_ACTION_CATALOG = (
    {
        "action": "select_columns",
        "label": "Select columns",
        "prompt": "Select the dataframe columns needed for the next analysis step.",
    },
    {
        "action": "drop_columns",
        "label": "Drop columns",
        "prompt": "Drop unnecessary dataframe columns while preserving the analysis target.",
    },
    {
        "action": "rename_columns",
        "label": "Rename columns",
        "prompt": "Rename dataframe columns to clearer analysis-ready names.",
    },
    {
        "action": "filter_rows",
        "label": "Filter rows",
        "prompt": "Filter rows using a column condition and keep only relevant observations.",
    },
    {
        "action": "derive_column",
        "label": "Derive column",
        "prompt": "Create a derived dataframe column from an existing column.",
    },
    {
        "action": "fill_missing",
        "label": "Fill missing values",
        "prompt": "Fill missing values in selected dataframe columns.",
    },
    {
        "action": "drop_missing",
        "label": "Drop missing rows",
        "prompt": "Drop rows with missing values in the relevant dataframe columns.",
    },
    {
        "action": "sort_rows",
        "label": "Sort rows",
        "prompt": "Sort dataframe rows by the columns that define the analysis order.",
    },
    {
        "action": "groupby_aggregate",
        "label": "Group and aggregate",
        "prompt": "Group rows by one or more columns and compute aggregate metrics.",
    },
    {
        "action": "rolling_mean",
        "label": "Rolling mean",
        "prompt": "Compute a rolling mean feature from an ordered numeric column.",
    },
    {
        "action": "clip",
        "label": "Clip values",
        "prompt": "Clip numeric values to a safe lower and upper range.",
    },
)


class GeneratedActionError(ValueError):
    """Raised when a generated dataframe-action contract is invalid."""


@dataclass(frozen=True)
class GeneratedActionContract:
    schema_version: int
    kind: str
    actions: tuple[dict[str, Any], ...]
    notes: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "actions": [dict(action) for action in self.actions],
            "notes": self.notes,
        }


def dataframe_schema_for_prompt(df: pd.DataFrame | None, *, max_columns: int = 80) -> list[dict[str, str]]:
    if not isinstance(df, pd.DataFrame):
        return []
    rows: list[dict[str, str]] = []
    for column in list(df.columns)[:max_columns]:
        rows.append({"name": str(column), "dtype": str(df[column].dtype)})
    return rows


def safe_action_catalog_options() -> tuple[dict[str, str], ...]:
    return tuple(dict(item) for item in SAFE_ACTION_CATALOG)


def safe_action_template_code(action_name: str) -> str:
    action = str(action_name or "").strip()
    labels = {str(item["action"]): str(item["label"]) for item in SAFE_ACTION_CATALOG}
    label = labels.get(action)
    if label is None:
        raise GeneratedActionError(f"unsupported safe action template: {action!r}")
    template_body = {
        "select_columns": (
            'columns = ["column_a", "column_b"]\n'
            "missing = [column for column in columns if column not in df.columns]\n"
            "if missing:\n"
            '    raise KeyError(f"Unknown dataframe column(s): {missing}")\n'
            "df = df[columns].copy()\n"
        ),
        "drop_columns": (
            'columns = ["column_to_drop"]\n'
            "missing = [column for column in columns if column not in df.columns]\n"
            "if missing:\n"
            '    raise KeyError(f"Unknown dataframe column(s): {missing}")\n'
            "df = df.drop(columns=columns).copy()\n"
        ),
        "rename_columns": (
            'mapping = {"old_column": "new_column"}\n'
            "missing = [column for column in mapping if column not in df.columns]\n"
            "if missing:\n"
            '    raise KeyError(f"Unknown dataframe column(s): {missing}")\n'
            "df = df.rename(columns=mapping).copy()\n"
        ),
        "filter_rows": (
            'column = "column_name"\n'
            'value = "value"\n'
            "if column not in df.columns:\n"
            '    raise KeyError(f"Unknown dataframe column: {column}")\n'
            "df = df[df[column] == value].copy()\n"
        ),
        "derive_column": (
            'input_column = "source_column"\n'
            'output_column = "derived_column"\n'
            "scale = 1.0\n"
            "if input_column not in df.columns:\n"
            '    raise KeyError(f"Unknown dataframe column: {input_column}")\n'
            "df = df.copy()\n"
            "df[output_column] = df[input_column] * scale\n"
        ),
        "fill_missing": (
            'columns = ["column_name"]\n'
            "fill_value = 0\n"
            "missing = [column for column in columns if column not in df.columns]\n"
            "if missing:\n"
            '    raise KeyError(f"Unknown dataframe column(s): {missing}")\n'
            "df = df.copy()\n"
            "df[columns] = df[columns].fillna(fill_value)\n"
        ),
        "drop_missing": (
            'columns = ["column_name"]\n'
            "missing = [column for column in columns if column not in df.columns]\n"
            "if missing:\n"
            '    raise KeyError(f"Unknown dataframe column(s): {missing}")\n'
            "df = df.dropna(subset=columns).copy()\n"
        ),
        "sort_rows": (
            'columns = ["column_name"]\n'
            "ascending = True\n"
            "missing = [column for column in columns if column not in df.columns]\n"
            "if missing:\n"
            '    raise KeyError(f"Unknown dataframe column(s): {missing}")\n'
            "df = df.sort_values(by=columns, ascending=ascending).reset_index(drop=True)\n"
        ),
        "groupby_aggregate": (
            'group_columns = ["group_column"]\n'
            'aggregations = {"metric_column": "mean"}\n'
            "required = [*group_columns, *aggregations.keys()]\n"
            "missing = [column for column in required if column not in df.columns]\n"
            "if missing:\n"
            '    raise KeyError(f"Unknown dataframe column(s): {missing}")\n'
            "df = df.groupby(group_columns, dropna=False).agg(aggregations).reset_index()\n"
        ),
        "rolling_mean": (
            'input_column = "metric_column"\n'
            'output_column = "metric_rolling_mean"\n'
            "window = 3\n"
            "if input_column not in df.columns:\n"
            '    raise KeyError(f"Unknown dataframe column: {input_column}")\n'
            "df = df.copy()\n"
            "df[output_column] = df[input_column].rolling(window=window, min_periods=1).mean()\n"
        ),
        "clip": (
            'input_column = "metric_column"\n'
            "output_column = input_column\n"
            "lower = 0\n"
            "upper = 1\n"
            "if input_column not in df.columns:\n"
            '    raise KeyError(f"Unknown dataframe column: {input_column}")\n'
            "df = df.copy()\n"
            "df[output_column] = df[input_column].clip(lower=lower, upper=upper)\n"
        ),
    }[action]
    return (
        f"# AGILAB Safe Action template: {label}.\n"
        "# Replace placeholder column/value names or click Gen code to create a validated Safe Action contract.\n"
        "# The final saved Safe Action should come from AGILAB's validated JSON contract.\n"
        f"{template_body}"
    )


def build_generated_actions_prompt(question: str, df: pd.DataFrame | None = None) -> str:
    schema = dataframe_schema_for_prompt(df)
    schema_text = json.dumps(schema, ensure_ascii=False, indent=2)
    return (
        f"{GENERATED_ACTIONS_SYSTEM_INSTRUCTIONS}\n\n"
        "Supported actions:\n"
        "- select_columns: columns\n"
        "- drop_columns: columns\n"
        "- rename_columns: mapping\n"
        "- filter_rows: column, operator eq|ne|gt|ge|lt|le|contains|isin, value\n"
        "- derive_column: input, output, transform copy|add|subtract|multiply|divide|abs, optional value\n"
        "- fill_missing: columns, value\n"
        "- drop_missing: optional columns\n"
        "- sort_rows: columns, ascending\n"
        "- groupby_aggregate: by, aggregations mapping column to sum|mean|min|max|count\n"
        "- rolling_mean: input, output, window\n"
        "- clip: input, optional output, optional lower, optional upper\n\n"
        f"Available dataframe columns and dtypes:\n{schema_text or '[]'}\n\n"
        f"User request:\n{str(question).strip()}"
    )


def parse_generated_action_contract(raw_text: str) -> GeneratedActionContract:
    payload = _loads_json_contract(raw_text)
    return validate_generated_action_contract(payload)


def validate_generated_action_contract(
    payload: Mapping[str, Any],
    *,
    df: pd.DataFrame | None = None,
) -> GeneratedActionContract:
    if not isinstance(payload, Mapping):
        raise GeneratedActionError("generated action contract must be a JSON object")
    version = payload.get("schema_version")
    if version != GENERATED_ACTIONS_SCHEMA_VERSION:
        raise GeneratedActionError(f"unsupported generated action schema_version: {version!r}")
    kind = payload.get("kind")
    if kind != GENERATED_ACTIONS_KIND:
        raise GeneratedActionError(f"unsupported generated action kind: {kind!r}")
    raw_actions = payload.get("actions")
    if not isinstance(raw_actions, list):
        raise GeneratedActionError("generated action contract requires an actions list")

    column_names = set(str(column) for column in df.columns) if isinstance(df, pd.DataFrame) else None
    actions: list[dict[str, Any]] = []
    for idx, raw_action in enumerate(raw_actions, start=1):
        if not isinstance(raw_action, Mapping):
            raise GeneratedActionError(f"action {idx} must be an object")
        action = str(raw_action.get("action") or "").strip()
        if action not in _ALLOWED_ACTIONS:
            raise GeneratedActionError(f"action {idx} uses unsupported action {action!r}")
        extra_keys = set(raw_action) - _ACTION_KEYS[action]
        if extra_keys:
            names = ", ".join(sorted(str(key) for key in extra_keys))
            raise GeneratedActionError(f"action {idx} contains unsupported key(s): {names}")
        normalized = _normalize_action(action, raw_action, idx=idx, column_names=column_names)
        actions.append(normalized)

    notes = str(payload.get("notes") or "").strip()
    return GeneratedActionContract(
        schema_version=GENERATED_ACTIONS_SCHEMA_VERSION,
        kind=GENERATED_ACTIONS_KIND,
        actions=tuple(actions),
        notes=notes,
    )


def generated_action_contract_to_python(contract: GeneratedActionContract | Mapping[str, Any]) -> str:
    if isinstance(contract, Mapping):
        contract = validate_generated_action_contract(contract)

    lines = [
        "# AGILAB generated safe actions: validated JSON contract converted to pandas operations.",
        "# This stage is not raw model Python.",
        "df = df.copy()",
    ]
    if not contract.actions:
        lines.append("# No supported dataframe action was generated; df is unchanged.")
    for idx, action in enumerate(contract.actions, start=1):
        lines.extend(_action_to_python_lines(idx, action))
    return "\n".join(lines).strip() + "\n"


def safe_action_contract_stage_code(contract: GeneratedActionContract | Mapping[str, Any]) -> str:
    return generated_action_contract_to_python(contract)


def safe_action_contract_sha256(contract: GeneratedActionContract | Mapping[str, Any]) -> str:
    if isinstance(contract, GeneratedActionContract):
        payload = contract.to_payload()
    else:
        payload = validate_generated_action_contract(contract).to_payload()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def dataframe_schema_sha256(df: pd.DataFrame | None) -> str:
    canonical = json.dumps(
        dataframe_schema_for_prompt(df),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def summarize_generated_actions(contract: GeneratedActionContract | Mapping[str, Any]) -> str:
    if isinstance(contract, Mapping):
        contract = validate_generated_action_contract(contract)
    if not contract.actions:
        return contract.notes or "No supported safe action was generated; dataframe is unchanged."
    labels = []
    for action in contract.actions:
        labels.append(str(action.get("action", "")).replace("_", " "))
    summary = ", ".join(labels[:4])
    if len(labels) > 4:
        summary += f", +{len(labels) - 4} more"
    return f"Safe action contract: {summary}."


def stage_generation_extra_fields(
    contract: GeneratedActionContract | Mapping[str, Any] | None,
    *,
    mode: str,
    df: pd.DataFrame | None = None,
    pinned: bool = False,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        STAGE_GENERATION_MODE_FIELD: mode,
        STAGE_ACTION_CONTRACT_SHA256_FIELD: "",
        STAGE_DATAFRAME_SCHEMA_SHA256_FIELD: dataframe_schema_sha256(df),
        STAGE_SAFE_ACTION_PINNED_FIELD: False,
    }
    if contract is None:
        fields[STAGE_ACTION_CONTRACT_FIELD] = None
        return fields
    if isinstance(contract, GeneratedActionContract):
        payload = contract.to_payload()
    else:
        payload = validate_generated_action_contract(contract).to_payload()
    fields[STAGE_ACTION_CONTRACT_FIELD] = payload
    fields[STAGE_ACTION_CONTRACT_SHA256_FIELD] = safe_action_contract_sha256(payload)
    fields[STAGE_SAFE_ACTION_PINNED_FIELD] = bool(
        pinned and mode == GENERATION_MODE_SAFE_ACTIONS
    )
    return fields


def pin_safe_action_extra_fields(
    contract: GeneratedActionContract | Mapping[str, Any],
    *,
    df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    return stage_generation_extra_fields(
        contract,
        mode=GENERATION_MODE_SAFE_ACTIONS,
        df=df,
        pinned=True,
    )


def _loads_json_contract(raw_text: str) -> Mapping[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        raise GeneratedActionError("model returned an empty generated action contract")

    candidates = [text]
    if "```" in text:
        parts = text.split("```")
        for part in parts[1::2]:
            stripped = part.strip()
            if stripped.lower().startswith("json"):
                stripped = stripped[4:].strip()
            if stripped:
                candidates.insert(0, stripped)

    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(text[first : last + 1])

    errors: list[str] = []
    for candidate in candidates:
        try:
            loaded = json.loads(candidate)
        except json.JSONDecodeError as exc:
            errors.append(str(exc))
            continue
        if isinstance(loaded, Mapping):
            return loaded
        errors.append("JSON root is not an object")
    reason = errors[-1] if errors else "invalid JSON"
    raise GeneratedActionError(f"model returned invalid generated action JSON: {reason}")


def _normalize_action(
    action: str,
    raw_action: Mapping[str, Any],
    *,
    idx: int,
    column_names: set[str] | None,
) -> dict[str, Any]:
    if action in {"select_columns", "drop_columns", "sort_rows"}:
        columns = _string_list(raw_action.get("columns"), f"action {idx} columns")
        _require_columns(columns, column_names, idx)
        normalized = {"action": action, "columns": columns}
        if action == "sort_rows":
            normalized["ascending"] = _bool_value(raw_action.get("ascending", True), f"action {idx} ascending")
        return normalized

    if action == "rename_columns":
        mapping = _string_mapping(raw_action.get("mapping"), f"action {idx} mapping")
        _require_columns(mapping.keys(), column_names, idx)
        return {"action": action, "mapping": mapping}

    if action == "filter_rows":
        column = _string_value(raw_action.get("column"), f"action {idx} column")
        _require_columns([column], column_names, idx)
        operator = _string_value(raw_action.get("operator"), f"action {idx} operator")
        if operator not in _FILTER_OPERATORS:
            raise GeneratedActionError(f"action {idx} uses unsupported filter operator {operator!r}")
        value = raw_action.get("value")
        if operator == "isin":
            value = _scalar_list(value, f"action {idx} value")
        elif not _is_scalar(value):
            raise GeneratedActionError(f"action {idx} value must be a scalar")
        return {"action": action, "column": column, "operator": operator, "value": value}

    if action == "derive_column":
        input_column = _string_value(raw_action.get("input"), f"action {idx} input")
        output = _string_value(raw_action.get("output"), f"action {idx} output")
        _require_columns([input_column], column_names, idx)
        transform = _string_value(raw_action.get("transform"), f"action {idx} transform")
        if transform not in _DERIVE_TRANSFORMS:
            raise GeneratedActionError(f"action {idx} uses unsupported transform {transform!r}")
        normalized = {"action": action, "input": input_column, "output": output, "transform": transform}
        if transform in {"add", "subtract", "multiply", "divide"}:
            normalized["value"] = _number_value(raw_action.get("value"), f"action {idx} value")
        return normalized

    if action == "fill_missing":
        columns = _string_list(raw_action.get("columns"), f"action {idx} columns")
        _require_columns(columns, column_names, idx)
        value = raw_action.get("value")
        if not _is_scalar(value):
            raise GeneratedActionError(f"action {idx} value must be a scalar")
        return {"action": action, "columns": columns, "value": value}

    if action == "drop_missing":
        raw_columns = raw_action.get("columns")
        columns = _string_list(raw_columns, f"action {idx} columns") if raw_columns is not None else []
        _require_columns(columns, column_names, idx)
        return {"action": action, "columns": columns}

    if action == "groupby_aggregate":
        by = _string_list(raw_action.get("by"), f"action {idx} by")
        aggregations = _string_mapping(raw_action.get("aggregations"), f"action {idx} aggregations")
        _require_columns([*by, *aggregations.keys()], column_names, idx)
        for column, function in aggregations.items():
            if function not in _AGGREGATIONS:
                raise GeneratedActionError(
                    f"action {idx} aggregation for {column!r} uses unsupported function {function!r}"
                )
        return {"action": action, "by": by, "aggregations": aggregations}

    if action == "rolling_mean":
        input_column = _string_value(raw_action.get("input"), f"action {idx} input")
        output = _string_value(raw_action.get("output"), f"action {idx} output")
        _require_columns([input_column], column_names, idx)
        window = _positive_int(raw_action.get("window"), f"action {idx} window")
        return {"action": action, "input": input_column, "output": output, "window": window}

    if action == "clip":
        input_column = _string_value(raw_action.get("input"), f"action {idx} input")
        output = raw_action.get("output")
        output_column = _string_value(output, f"action {idx} output") if output is not None else input_column
        _require_columns([input_column], column_names, idx)
        lower = raw_action.get("lower")
        upper = raw_action.get("upper")
        if lower is None and upper is None:
            raise GeneratedActionError(f"action {idx} clip requires lower or upper")
        if lower is not None:
            lower = _number_value(lower, f"action {idx} lower")
        if upper is not None:
            upper = _number_value(upper, f"action {idx} upper")
        return {"action": action, "input": input_column, "output": output_column, "lower": lower, "upper": upper}

    raise GeneratedActionError(f"unsupported action {action!r}")


def _action_to_python_lines(idx: int, action: Mapping[str, Any]) -> list[str]:
    name = str(action["action"])
    lines = [f"# Safe action {idx}: {name.replace('_', ' ')}"]
    if name == "select_columns":
        lines.append(f"df = df[{_repr_list(action['columns'])}].copy()")
    elif name == "drop_columns":
        lines.append(f"df = df.drop(columns={_repr_list(action['columns'])})")
    elif name == "rename_columns":
        lines.append(f"df = df.rename(columns={_repr_mapping(action['mapping'])})")
    elif name == "filter_rows":
        column = _repr_scalar(action["column"])
        value = action["value"]
        operator = str(action["operator"])
        if operator == "eq":
            lines.append(f"df = df.loc[df[{column}] == {_repr_scalar(value)}].copy()")
        elif operator == "ne":
            lines.append(f"df = df.loc[df[{column}] != {_repr_scalar(value)}].copy()")
        elif operator == "gt":
            lines.append(f"df = df.loc[df[{column}] > {_repr_scalar(value)}].copy()")
        elif operator == "ge":
            lines.append(f"df = df.loc[df[{column}] >= {_repr_scalar(value)}].copy()")
        elif operator == "lt":
            lines.append(f"df = df.loc[df[{column}] < {_repr_scalar(value)}].copy()")
        elif operator == "le":
            lines.append(f"df = df.loc[df[{column}] <= {_repr_scalar(value)}].copy()")
        elif operator == "contains":
            lines.append(
                f"df = df.loc[df[{column}].astype('string').str.contains({_repr_scalar(str(value))}, "
                "case=False, na=False, regex=False)].copy()"
            )
        elif operator == "isin":
            lines.append(f"df = df.loc[df[{column}].isin({_repr_list(value)})].copy()")
    elif name == "derive_column":
        source = _repr_scalar(action["input"])
        target = _repr_scalar(action["output"])
        transform = str(action["transform"])
        if transform == "copy":
            lines.append(f"df[{target}] = df[{source}]")
        elif transform == "abs":
            lines.append(f"df[{target}] = df[{source}].abs()")
        elif transform == "add":
            lines.append(f"df[{target}] = df[{source}] + {_repr_scalar(action['value'])}")
        elif transform == "subtract":
            lines.append(f"df[{target}] = df[{source}] - {_repr_scalar(action['value'])}")
        elif transform == "multiply":
            lines.append(f"df[{target}] = df[{source}] * {_repr_scalar(action['value'])}")
        elif transform == "divide":
            lines.append(f"df[{target}] = df[{source}] / {_repr_scalar(action['value'])}")
    elif name == "fill_missing":
        columns = _repr_list(action["columns"])
        lines.append(f"df[{columns}] = df[{columns}].fillna({_repr_scalar(action['value'])})")
    elif name == "drop_missing":
        columns = action.get("columns") or []
        if columns:
            lines.append(f"df = df.dropna(subset={_repr_list(columns)}).copy()")
        else:
            lines.append("df = df.dropna().copy()")
    elif name == "sort_rows":
        lines.append(
            f"df = df.sort_values(by={_repr_list(action['columns'])}, "
            f"ascending={bool(action.get('ascending', True))}).reset_index(drop=True)"
        )
    elif name == "groupby_aggregate":
        lines.append(
            f"df = df.groupby({_repr_list(action['by'])}, dropna=False)"
            f".agg({_repr_mapping(action['aggregations'])}).reset_index()"
        )
    elif name == "rolling_mean":
        lines.append(
            f"df[{_repr_scalar(action['output'])}] = "
            f"df[{_repr_scalar(action['input'])}].rolling(window={int(action['window'])}, min_periods=1).mean()"
        )
    elif name == "clip":
        lower = "None" if action.get("lower") is None else _repr_scalar(action["lower"])
        upper = "None" if action.get("upper") is None else _repr_scalar(action["upper"])
        lines.append(
            f"df[{_repr_scalar(action['output'])}] = "
            f"df[{_repr_scalar(action['input'])}].clip(lower={lower}, upper={upper})"
        )
    return lines


def _string_value(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GeneratedActionError(f"{label} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise GeneratedActionError(f"{label} must be a non-empty list of strings")
    result = [_string_value(item, label) for item in value]
    if not result:
        raise GeneratedActionError(f"{label} must not be empty")
    return result


def _scalar_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise GeneratedActionError(f"{label} must be a non-empty scalar list")
    result = list(value)
    if not result or not all(_is_scalar(item) for item in result):
        raise GeneratedActionError(f"{label} must be a non-empty scalar list")
    return result


def _string_mapping(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise GeneratedActionError(f"{label} must be a non-empty object")
    return {_string_value(key, label): _string_value(item, label) for key, item in value.items()}


def _bool_value(value: Any, label: str) -> bool:
    if isinstance(value, bool):
        return value
    raise GeneratedActionError(f"{label} must be a boolean")


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise GeneratedActionError(f"{label} must be a positive integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise GeneratedActionError(f"{label} must be a positive integer") from exc
    if number <= 0:
        raise GeneratedActionError(f"{label} must be a positive integer")
    return number


def _number_value(value: Any, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GeneratedActionError(f"{label} must be a number")
    return value


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _require_columns(columns: Sequence[str], column_names: set[str] | None, idx: int) -> None:
    if column_names is None:
        return
    missing = [column for column in columns if column not in column_names]
    if missing:
        names = ", ".join(repr(column) for column in missing)
        raise GeneratedActionError(f"action {idx} references unknown dataframe column(s): {names}")


def _repr_scalar(value: Any) -> str:
    return repr(value)


def _repr_list(values: Sequence[Any]) -> str:
    return repr(list(values))


def _repr_mapping(values: Mapping[str, str]) -> str:
    return repr(dict(values))
