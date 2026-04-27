from __future__ import annotations

import pytest

from agi_node import (
    ReduceArtifact,
    ReduceContract,
    ReducePartial,
    numeric_sum_merge,
    require_payload_keys,
)


def test_reduce_contract_builds_standard_artifact() -> None:
    contract = ReduceContract(
        name="flight-total",
        artifact_name="flight_reduce_summary",
        merge=numeric_sum_merge("delivered_bandwidth", "requested_bandwidth"),
        validate_partial=require_payload_keys("delivered_bandwidth", "requested_bandwidth"),
        metadata={"metric_family": "bandwidth"},
    )

    artifact = contract.build_artifact(
        [
            ReducePartial("worker-1", {"delivered_bandwidth": 7.5, "requested_bandwidth": 10}),
            ReducePartial("worker-2", {"delivered_bandwidth": 2.5, "requested_bandwidth": 5}),
        ]
    )

    assert artifact == ReduceArtifact(
        name="flight_reduce_summary",
        reducer="flight-total",
        payload={"delivered_bandwidth": 10.0, "requested_bandwidth": 15},
        partial_count=2,
        partial_ids=("worker-1", "worker-2"),
        metadata={"metric_family": "bandwidth"},
    )


def test_reduce_artifact_round_trips_to_stable_schema() -> None:
    artifact = ReduceArtifact(
        name="summary",
        reducer="demo",
        payload={"rows": 12},
        partial_count=1,
        partial_ids=("partition-a",),
    )

    encoded = artifact.to_dict()

    assert encoded == {
        "schema_version": 1,
        "name": "summary",
        "reducer": "demo",
        "partial_count": 1,
        "partial_ids": ["partition-a"],
        "payload": {"rows": 12},
        "metadata": {},
    }
    assert ReduceArtifact.from_dict(encoded) == artifact


def test_reduce_contract_rejects_empty_partial_set() -> None:
    contract = ReduceContract(name="demo", merge=numeric_sum_merge("rows"))

    with pytest.raises(ValueError, match="at least one partial"):
        contract.build_artifact([])


@pytest.mark.parametrize(
    ("kwargs", "expected_error", "match"),
    [
        ({"partial_id": "", "payload": {"rows": 1}}, ValueError, "partial_id"),
        ({"partial_id": "partition-a", "payload": [("rows", 1)]}, TypeError, "payload"),
        (
            {"partial_id": "partition-a", "payload": {"rows": 1}, "metadata": [("run", "a")]},
            TypeError,
            "metadata",
        ),
    ],
)
def test_reduce_partial_rejects_invalid_inputs(kwargs, expected_error, match) -> None:
    with pytest.raises(expected_error, match=match):
        ReducePartial(**kwargs)


@pytest.mark.parametrize(
    ("kwargs", "expected_error", "match"),
    [
        (
            {"name": "", "reducer": "demo", "payload": {}, "partial_count": 1},
            ValueError,
            "name",
        ),
        (
            {"name": "summary", "reducer": "", "payload": {}, "partial_count": 1},
            ValueError,
            "reducer",
        ),
        (
            {"name": "summary", "reducer": "demo", "payload": {}, "partial_count": -1},
            ValueError,
            "partial_count",
        ),
        (
            {"name": "summary", "reducer": "demo", "payload": [], "partial_count": 1},
            TypeError,
            "payload",
        ),
        (
            {
                "name": "summary",
                "reducer": "demo",
                "payload": {},
                "partial_count": 1,
                "metadata": [],
            },
            TypeError,
            "metadata",
        ),
    ],
)
def test_reduce_artifact_rejects_invalid_inputs(kwargs, expected_error, match) -> None:
    with pytest.raises(expected_error, match=match):
        ReduceArtifact(**kwargs)


def test_reduce_artifact_rejects_unsupported_schema() -> None:
    with pytest.raises(ValueError, match="Unsupported reduce artifact schema"):
        ReduceArtifact.from_dict(
            {
                "schema_version": 2,
                "name": "summary",
                "reducer": "demo",
                "payload": {},
                "partial_count": 1,
            }
        )


@pytest.mark.parametrize(
    ("kwargs", "expected_error", "match"),
    [
        ({"name": "", "merge": numeric_sum_merge("rows")}, ValueError, "name"),
        (
            {"name": "demo", "artifact_name": "", "merge": numeric_sum_merge("rows")},
            ValueError,
            "artifact_name",
        ),
        ({"name": "demo", "merge": "not-callable"}, TypeError, "merge"),
        (
            {"name": "demo", "merge": numeric_sum_merge("rows"), "metadata": []},
            TypeError,
            "metadata",
        ),
    ],
)
def test_reduce_contract_rejects_invalid_inputs(kwargs, expected_error, match) -> None:
    with pytest.raises(expected_error, match=match):
        ReduceContract(**kwargs)


def test_reduce_contract_rejects_non_mapping_merge_payload() -> None:
    contract = ReduceContract(name="demo", merge=lambda partials: ["not", "a", "mapping"])

    with pytest.raises(TypeError, match="mapping payload"):
        contract.build_artifact([ReducePartial("partition-a", {"rows": 1})])


def test_reduce_contract_runs_artifact_validator() -> None:
    def validate_artifact(artifact: ReduceArtifact) -> None:
        assert artifact.partial_ids == ("partition-a",)
        raise ValueError("artifact rejected")

    contract = ReduceContract(
        name="demo",
        merge=numeric_sum_merge("rows"),
        validate_artifact=validate_artifact,
    )

    with pytest.raises(ValueError, match="artifact rejected"):
        contract.build_artifact([ReducePartial("partition-a", {"rows": 1})])


def test_reducer_factories_require_keys() -> None:
    with pytest.raises(ValueError, match="required key"):
        require_payload_keys()

    with pytest.raises(ValueError, match="numeric key"):
        numeric_sum_merge()


def test_required_payload_validator_reports_missing_keys() -> None:
    contract = ReduceContract(
        name="demo",
        merge=numeric_sum_merge("rows"),
        validate_partial=require_payload_keys("rows"),
    )

    with pytest.raises(ValueError, match="missing: rows"):
        contract.build_artifact([ReducePartial("partition-a", {"other": 1})])


def test_numeric_sum_merge_rejects_non_numeric_payloads() -> None:
    contract = ReduceContract(name="demo", merge=numeric_sum_merge("rows"))

    with pytest.raises(TypeError, match="not numeric"):
        contract.build_artifact([ReducePartial("partition-a", {"rows": "12"})])
