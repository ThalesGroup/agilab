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
stage_generation_extra_fields = generated_actions.stage_generation_extra_fields
summarize_generated_actions = generated_actions.summarize_generated_actions
validate_generated_action_contract = generated_actions.validate_generated_action_contract


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
