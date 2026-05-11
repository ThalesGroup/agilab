from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
import pandas as pd


def _load_module():
    module_path = Path("src/agilab/generated_actions.py")
    spec = importlib.util.spec_from_file_location("agilab.generated_actions", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agilab.generated_actions"] = module
    spec.loader.exec_module(module)
    return module


generated_actions = _load_module()
GENERATED_ACTIONS_KIND = generated_actions.GENERATED_ACTIONS_KIND
GENERATED_ACTIONS_SCHEMA_VERSION = generated_actions.GENERATED_ACTIONS_SCHEMA_VERSION
GENERATION_MODE_SAFE_ACTIONS = generated_actions.GENERATION_MODE_SAFE_ACTIONS
STAGE_ACTION_CONTRACT_FIELD = generated_actions.STAGE_ACTION_CONTRACT_FIELD
STAGE_GENERATION_MODE_FIELD = generated_actions.STAGE_GENERATION_MODE_FIELD
GeneratedActionError = generated_actions.GeneratedActionError
build_generated_actions_prompt = generated_actions.build_generated_actions_prompt
generated_action_contract_to_python = generated_actions.generated_action_contract_to_python
parse_generated_action_contract = generated_actions.parse_generated_action_contract
dataframe_schema_for_prompt = generated_actions.dataframe_schema_for_prompt
stage_generation_extra_fields = generated_actions.stage_generation_extra_fields
summarize_generated_actions = generated_actions.summarize_generated_actions
validate_generated_action_contract = generated_actions.validate_generated_action_contract
_action_to_python_lines = generated_actions._action_to_python_lines
_loads_json_contract = generated_actions._loads_json_contract
_normalize_action = generated_actions._normalize_action


def test_generated_action_contract_validates_and_generates_deterministic_code() -> None:
    df = pd.DataFrame(
        {
            "speed_ms": [10.0, 20.0],
            "category": ["fast", "slow"],
            "unused": [1, 2],
        }
    )
    payload = {
        "schema_version": GENERATED_ACTIONS_SCHEMA_VERSION,
        "kind": GENERATED_ACTIONS_KIND,
        "actions": [
            {"action": "drop_columns", "columns": ["unused"]},
            {
                "action": "derive_column",
                "input": "speed_ms",
                "output": "speed_kmh",
                "transform": "multiply",
                "value": 3.6,
            },
            {"action": "filter_rows", "column": "category", "operator": "contains", "value": "fa"},
        ],
        "notes": "convert speed and keep fast rows",
    }

    contract = validate_generated_action_contract(payload, df=df)
    code = generated_action_contract_to_python(contract)

    namespace = {"df": df, "pd": pd}
    exec(code, namespace)
    result = namespace["df"]

    assert list(result.columns) == ["speed_ms", "category", "speed_kmh"]
    assert result["speed_kmh"].tolist() == [36.0]
    assert "not raw model Python" in code
    assert summarize_generated_actions(contract) == (
        "Safe action contract: drop columns, derive column, filter rows."
    )


def test_generated_action_contract_rejects_raw_python_and_unknown_columns() -> None:
    df = pd.DataFrame({"x": [1]})

    with pytest.raises(GeneratedActionError, match="invalid generated action JSON"):
        parse_generated_action_contract("```python\nimport os\nos.system('whoami')\n```")

    with pytest.raises(GeneratedActionError, match="unknown dataframe column"):
        validate_generated_action_contract(
            {
                "schema_version": GENERATED_ACTIONS_SCHEMA_VERSION,
                "kind": GENERATED_ACTIONS_KIND,
                "actions": [{"action": "select_columns", "columns": ["missing"]}],
            },
            df=df,
        )


def test_generated_action_contract_rejects_unsupported_actions_and_keys() -> None:
    base = {
        "schema_version": GENERATED_ACTIONS_SCHEMA_VERSION,
        "kind": GENERATED_ACTIONS_KIND,
    }

    with pytest.raises(GeneratedActionError, match="unsupported action"):
        validate_generated_action_contract({**base, "actions": [{"action": "eval", "expr": "x + 1"}]})

    with pytest.raises(GeneratedActionError, match="unsupported key"):
        validate_generated_action_contract(
            {**base, "actions": [{"action": "drop_missing", "columns": ["x"], "expr": "x"}]}
        )


def test_generated_action_prompt_and_stage_metadata_are_explicit() -> None:
    df = pd.DataFrame({"station": ["Paris"], "temperature": [21.5]})

    prompt = build_generated_actions_prompt("keep Paris rows", df)
    assert "Return ONLY a JSON object" in prompt
    assert "Do not return Python code" in prompt
    assert '"station"' in prompt
    assert "filter_rows" in prompt

    contract = validate_generated_action_contract(
        {
            "schema_version": GENERATED_ACTIONS_SCHEMA_VERSION,
            "kind": GENERATED_ACTIONS_KIND,
            "actions": [{"action": "filter_rows", "column": "station", "operator": "eq", "value": "Paris"}],
        },
        df=df,
    )
    fields = stage_generation_extra_fields(contract, mode=GENERATION_MODE_SAFE_ACTIONS)

    assert fields[STAGE_GENERATION_MODE_FIELD] == GENERATION_MODE_SAFE_ACTIONS
    assert fields[STAGE_ACTION_CONTRACT_FIELD]["schema_version"] == GENERATED_ACTIONS_SCHEMA_VERSION
    assert fields[STAGE_ACTION_CONTRACT_FIELD]["actions"][0]["action"] == "filter_rows"


def test_dataframe_schema_for_prompt_returns_empty_for_invalid_payload() -> None:
    assert dataframe_schema_for_prompt(None) == []
    df = pd.DataFrame({"a": [1], "b": ["x"]})
    assert dataframe_schema_for_prompt(df, max_columns=1) == [{"name": "a", "dtype": "int64"}]


def test_parse_generated_action_contract_can_extract_json_codeblock() -> None:
    contract = parse_generated_action_contract(
        "\n```json\n"
        "{\n"
        f'  "schema_version": {GENERATED_ACTIONS_SCHEMA_VERSION},\n'
        f'  "kind": "{GENERATED_ACTIONS_KIND}",\n'
        '  "actions": [\n'
        '    {"action": "select_columns", "columns": ["x"]}\n'
        "  ]\n"
        "}\n"
        "```"
    )

    assert contract.actions == ({"action": "select_columns", "columns": ["x"]},)


def test_parse_generated_action_contract_extracts_embedded_json_from_text() -> None:
    contract = parse_generated_action_contract(
        "Noisy preamble\n"
        "some notes\n"
        "{\n"
        f'  "schema_version": {GENERATED_ACTIONS_SCHEMA_VERSION},\n'
        f'  "kind": "{GENERATED_ACTIONS_KIND}",\n'
        '  "actions": []\n'
        "}\n"
        " trailing text"
    )
    assert contract.actions == ()
    assert contract.notes == ""


def test_parse_generated_action_contract_rejects_invalid_json_payload() -> None:
    with pytest.raises(GeneratedActionError, match="invalid generated action JSON"):
        parse_generated_action_contract("not valid json")


def test_loads_json_contract_raises_on_invalid_root() -> None:
    with pytest.raises(GeneratedActionError, match="root is not an object"):
        _loads_json_contract('[1,2,3]')


def test_generated_action_contract_rejects_invalid_schema_and_kind() -> None:
    invalid_schema = {
        "schema_version": 999,
        "kind": GENERATED_ACTIONS_KIND,
        "actions": [],
    }
    with pytest.raises(GeneratedActionError, match="unsupported generated action schema_version"):
        validate_generated_action_contract(invalid_schema)

    invalid_kind = {
        "schema_version": GENERATED_ACTIONS_SCHEMA_VERSION,
        "kind": "invalid.kind",
        "actions": [],
    }
    with pytest.raises(GeneratedActionError, match="unsupported generated action kind"):
        validate_generated_action_contract(invalid_kind)


def test_generated_action_contract_to_python_covers_no_action() -> None:
    code = generated_action_contract_to_python({"schema_version": GENERATED_ACTIONS_SCHEMA_VERSION, "kind": GENERATED_ACTIONS_KIND, "actions": []})
    assert "df = df.copy()" in code
    assert "# No supported dataframe action was generated; df is unchanged." in code


def test_generated_action_contract_rejects_bad_filters_and_scalars() -> None:
    with pytest.raises(GeneratedActionError, match="unsupported filter operator"):
        validate_generated_action_contract(
            {
                "schema_version": GENERATED_ACTIONS_SCHEMA_VERSION,
                "kind": GENERATED_ACTIONS_KIND,
                "actions": [{"action": "filter_rows", "column": "x", "operator": "bad", "value": 1}],
            },
            df=pd.DataFrame({"x": [1]}),
        )

    with pytest.raises(GeneratedActionError, match="value must be a scalar"):
        validate_generated_action_contract(
            {
                "schema_version": GENERATED_ACTIONS_SCHEMA_VERSION,
                "kind": GENERATED_ACTIONS_KIND,
                "actions": [{"action": "filter_rows", "column": "x", "operator": "eq", "value": {"not": "scalar"}}],
            },
            df=pd.DataFrame({"x": [1]}),
        )


def test_generated_action_contract_rejects_bad_transform_and_aggregation() -> None:
    with pytest.raises(GeneratedActionError, match="unsupported transform"):
        validate_generated_action_contract(
            {
                "schema_version": GENERATED_ACTIONS_SCHEMA_VERSION,
                "kind": GENERATED_ACTIONS_KIND,
                "actions": [
                    {
                        "action": "derive_column",
                        "input": "x",
                        "output": "y",
                        "transform": "invalid",
                        "value": 1,
                    }
                ],
            },
            df=pd.DataFrame({"x": [1]}),
        )

    with pytest.raises(GeneratedActionError, match="unsupported function"):
        validate_generated_action_contract(
            {
                "schema_version": GENERATED_ACTIONS_SCHEMA_VERSION,
                "kind": GENERATED_ACTIONS_KIND,
                "actions": [{"action": "groupby_aggregate", "by": ["x"], "aggregations": {"x": "invalid"}}],
            },
            df=pd.DataFrame({"x": [1]}),
        )


def test_action_to_python_lines_has_full_action_coverage_markers() -> None:
    df = pd.DataFrame({"x": [1], "y": [2], "label": ["alpha"]})
    contract = validate_generated_action_contract(
        {
            "schema_version": GENERATED_ACTIONS_SCHEMA_VERSION,
            "kind": GENERATED_ACTIONS_KIND,
            "actions": [
                {"action": "select_columns", "columns": ["x", "y", "label"]},
                {"action": "sort_rows", "columns": ["x"], "ascending": False},
                {"action": "fill_missing", "columns": ["x"], "value": 0},
                {"action": "drop_missing"},
                {"action": "filter_rows", "column": "label", "operator": "contains", "value": "a"},
                {"action": "derive_column", "input": "x", "output": "z1", "transform": "copy"},
                {"action": "derive_column", "input": "x", "output": "z2", "transform": "abs"},
                {"action": "derive_column", "input": "x", "output": "z3", "transform": "add", "value": 1},
                {"action": "derive_column", "input": "x", "output": "z4", "transform": "subtract", "value": 2},
                {"action": "derive_column", "input": "x", "output": "z5", "transform": "multiply", "value": 3},
                {"action": "derive_column", "input": "x", "output": "z6", "transform": "divide", "value": 4},
                {"action": "groupby_aggregate", "by": ["x"], "aggregations": {"y": "sum"}},
                {"action": "rolling_mean", "input": "x", "output": "avg_x", "window": 2},
                {"action": "clip", "input": "x", "output": "x2", "lower": 0, "upper": 10},
                {"action": "clip", "input": "x", "lower": None, "upper": 10},
                {"action": "filter_rows", "column": "y", "operator": "ge", "value": 0},
                {"action": "filter_rows", "column": "y", "operator": "lt", "value": 10},
                {"action": "filter_rows", "column": "y", "operator": "le", "value": 10},
                {"action": "filter_rows", "column": "y", "operator": "gt", "value": 0},
                {"action": "filter_rows", "column": "y", "operator": "ne", "value": 99},
                {"action": "filter_rows", "column": "y", "operator": "isin", "value": [1, 2, 3]},
                {"action": "rename_columns", "mapping": {"x": "z"}},
                {"action": "drop_columns", "columns": ["y"]},
            ],
            },
        df=df,
    )
    code = generated_action_contract_to_python(contract)
    namespace = {"df": df.copy(), "pd": pd}
    exec(code, namespace)

    result = namespace["df"]
    assert not result.empty
    assert "z" in result.columns
    assert "avg_x" in result.columns

    for action in contract.actions:
        action_lines = _action_to_python_lines(99, action)
        assert action_lines


def test_normalize_action_rejects_invalid_columns_when_dataframe_absent() -> None:
    assert _normalize_action(
        "select_columns",
        {"action": "select_columns", "columns": ["x"]},
        idx=1,
        column_names=None,
    ) == {"action": "select_columns", "columns": ["x"]}


def test_derived_action_drop_missing_defaults() -> None:
    contract = validate_generated_action_contract(
        {
            "schema_version": GENERATED_ACTIONS_SCHEMA_VERSION,
            "kind": GENERATED_ACTIONS_KIND,
            "actions": [
                {"action": "drop_missing"},
                {"action": "fill_missing", "columns": ["x"], "value": 2},
                {"action": "clip", "input": "x", "upper": 10},
            ],
        },
        df=pd.DataFrame({"x": [1, None, 3]}),
    )
    code = generated_action_contract_to_python(contract)
    namespace = {"df": pd.DataFrame({"x": [1, None, 3]}), "pd": pd}
    exec(code, namespace)
    assert set(namespace["df"].columns) == {"x"}
