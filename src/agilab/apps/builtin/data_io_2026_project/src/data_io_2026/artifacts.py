"""Deterministic artifact generation for the public Data IO 2026 demo."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from .fred_support import fred_fixture_feature_rows


@dataclass(frozen=True)
class MissionWeights:
    latency: float = 0.65
    cost: float = 0.12
    reliability: float = 0.16
    risk: float = 0.07

    @classmethod
    def from_args(cls, args: Any) -> "MissionWeights":
        objective = str(getattr(args, "objective", "balanced_mission"))
        if objective == "latency_first":
            return cls(latency=0.78, cost=0.08, reliability=0.10, risk=0.04).normalised()
        if objective == "resilience_first":
            return cls(latency=0.32, cost=0.08, reliability=0.42, risk=0.18).normalised()
        return cls(
            latency=float(getattr(args, "latency_weight", 0.65)),
            cost=float(getattr(args, "cost_weight", 0.12)),
            reliability=float(getattr(args, "reliability_weight", 0.16)),
            risk=float(getattr(args, "risk_weight", 0.07)),
        ).normalised()

    def normalised(self) -> "MissionWeights":
        total = self.latency + self.cost + self.reliability + self.risk
        if total <= 0:
            return MissionWeights()
        return MissionWeights(
            latency=self.latency / total,
            cost=self.cost / total,
            reliability=self.reliability / total,
            risk=self.risk / total,
        )


def _clamp(value: float, *, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _pct_delta(new_value: float, reference: float) -> float | None:
    if reference == 0:
        return None
    return round(((new_value - reference) / reference) * 100.0, 3)


def _event_matches(event: Mapping[str, Any], failure_kind: str) -> bool:
    event_kind = str(event.get("kind", ""))
    if failure_kind == "combined":
        return event_kind in {"bandwidth_drop", "node_failure"}
    return event_kind == failure_kind


def _route_key(route: Mapping[str, Any]) -> str:
    return str(route.get("route_id") or route.get("label") or "route")


def apply_failure_events(
    routes: list[dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    failure_kind: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply selected mission events to route candidates."""

    updated = [deepcopy(route) for route in routes]
    applied: list[dict[str, Any]] = []
    for event in events:
        if not _event_matches(event, failure_kind):
            continue
        target_route = str(event.get("target_route", ""))
        for route in updated:
            if _route_key(route) != target_route:
                continue
            route["latency_ms"] = round(
                _safe_float(route.get("latency_ms")) * _safe_float(event.get("latency_multiplier"), 1.0),
                3,
            )
            route["cost"] = round(
                _safe_float(route.get("cost")) * _safe_float(event.get("cost_multiplier"), 1.0),
                3,
            )
            route["bandwidth_mbps"] = round(
                _safe_float(route.get("bandwidth_mbps")) * _safe_float(event.get("bandwidth_factor"), 1.0),
                3,
            )
            route["reliability"] = round(
                _clamp(_safe_float(route.get("reliability")) + _safe_float(event.get("reliability_delta"))),
                4,
            )
            route["risk"] = round(
                _clamp(_safe_float(route.get("risk")) + _safe_float(event.get("risk_delta"))),
                4,
            )
            route["active_event"] = event.get("kind")
            applied.append(dict(event))
    return updated, applied


def score_routes(
    routes: list[dict[str, Any]],
    *,
    weights: MissionWeights,
    phase: str,
) -> list[dict[str, Any]]:
    """Score route candidates. Lower score is better."""

    max_latency = max((_safe_float(route.get("latency_ms")) for route in routes), default=1.0) or 1.0
    max_cost = max((_safe_float(route.get("cost")) for route in routes), default=1.0) or 1.0
    max_risk = max((_safe_float(route.get("risk")) for route in routes), default=1.0) or 1.0

    scored: list[dict[str, Any]] = []
    for route in routes:
        latency = _safe_float(route.get("latency_ms"))
        cost = _safe_float(route.get("cost"))
        reliability = _clamp(_safe_float(route.get("reliability")))
        risk = _clamp(_safe_float(route.get("risk")))
        score = (
            weights.latency * (latency / max_latency)
            + weights.cost * (cost / max_cost)
            + weights.reliability * (1.0 - reliability)
            + weights.risk * (risk / max_risk)
        )
        row = {
            "phase": phase,
            "route_id": _route_key(route),
            "label": str(route.get("label", _route_key(route))),
            "latency_ms": round(latency, 3),
            "cost": round(cost, 3),
            "reliability": round(reliability, 4),
            "risk": round(risk, 4),
            "bandwidth_mbps": round(_safe_float(route.get("bandwidth_mbps")), 3),
            "score": round(score, 6),
            "active_event": route.get("active_event", ""),
        }
        scored.append(row)
    return sorted(scored, key=lambda item: (item["score"], item["latency_ms"], item["route_id"]))


def choose_route(scored_routes: list[dict[str, Any]]) -> dict[str, Any]:
    if not scored_routes:
        raise ValueError("No route candidates available")
    return dict(scored_routes[0])


def _selected_route(rows: list[dict[str, Any]], route_id: str) -> dict[str, Any]:
    for row in rows:
        if row.get("route_id") == route_id:
            return dict(row)
    raise ValueError(f"Route {route_id!r} not found")


def build_generated_pipeline(
    scenario: Mapping[str, Any],
    *,
    failure_kind: str,
    adaptation_mode: str,
) -> dict[str, Any]:
    """Build a scenario-driven conceptual pipeline contract."""

    source_count = len(scenario.get("sources", []) or [])
    route_count = len(scenario.get("routes", []) or [])
    event_count = len(
        [
            event
            for event in scenario.get("events", []) or []
            if isinstance(event, dict) and _event_matches(event, failure_kind)
        ]
    )
    stages = [
        {
            "stage_id": "ingest",
            "label": "Live data ingestion",
            "reason": f"{source_count} source streams declared",
        },
        {
            "stage_id": "clean",
            "label": "Cleaning and normalization",
            "reason": "quality fields are present on mission sources",
        },
        {
            "stage_id": "features",
            "label": "Feature extraction",
            "reason": "route latency, bandwidth, cost, reliability, and risk are available",
        },
        {
            "stage_id": "score",
            "label": "Model selection and route scoring",
            "reason": f"{route_count} candidate routes declared",
        },
    ]
    if event_count:
        stages.append(
            {
                "stage_id": "detect_event",
                "label": "Mission event detection",
                "reason": f"{event_count} selected failure event(s) are active",
            }
        )
    if adaptation_mode == "auto_replan":
        stages.append(
            {
                "stage_id": "replan",
                "label": "Optimization re-plan",
                "reason": "automatic adaptation mode is enabled",
            }
        )
    stages.append(
        {
            "stage_id": "decision",
            "label": "Decision evidence export",
            "reason": "ANALYSIS requires auditable metrics and timeline artifacts",
        }
    )
    return {
        "schema": "agilab.data_io_2026.pipeline.v1",
        "scenario": scenario.get("scenario", "mission"),
        "dynamic": True,
        "failure_kind": failure_kind,
        "adaptation_mode": adaptation_mode,
        "stages": stages,
    }


def build_decision_artifacts(scenario: Mapping[str, Any], args: Any) -> dict[str, Any]:
    """Return all public demo artifacts for one mission scenario."""

    scenario_name = str(scenario.get("scenario") or "mission_decision_demo")
    failure_kind = str(getattr(args, "failure_kind", "bandwidth_drop"))
    adaptation_mode = str(getattr(args, "adaptation_mode", "auto_replan"))
    weights = MissionWeights.from_args(args)
    routes = [dict(route) for route in scenario.get("routes", []) or []]
    events = [dict(event) for event in scenario.get("events", []) or []]
    if not routes:
        raise ValueError(f"Scenario {scenario_name!r} declares no candidate routes")

    baseline_scored = score_routes(routes, weights=weights, phase="baseline")
    initial_choice = choose_route(baseline_scored)
    failed_routes, applied_events = apply_failure_events(
        routes,
        events,
        failure_kind=failure_kind,
    )
    post_failure_scored = score_routes(failed_routes, weights=weights, phase="post_failure")
    degraded_initial = _selected_route(post_failure_scored, str(initial_choice["route_id"]))
    adapted_choice = (
        choose_route(post_failure_scored)
        if adaptation_mode == "auto_replan"
        else degraded_initial
    )
    pipeline = build_generated_pipeline(
        scenario,
        failure_kind=failure_kind,
        adaptation_mode=adaptation_mode,
    )

    latency_delta_pct = _pct_delta(
        _safe_float(adapted_choice["latency_ms"]),
        _safe_float(degraded_initial["latency_ms"]),
    )
    cost_delta_pct = _pct_delta(
        _safe_float(adapted_choice["cost"]),
        _safe_float(degraded_initial["cost"]),
    )
    reliability_delta_pct = _pct_delta(
        _safe_float(adapted_choice["reliability"]),
        _safe_float(degraded_initial["reliability"]),
    )

    artifact_stem = scenario_name.replace(" ", "_")
    summary = {
        "schema": "agilab.data_io_2026.summary.v1",
        "scenario": scenario_name,
        "artifact_stem": artifact_stem,
        "status": "pass",
        "objective": getattr(args, "objective", "balanced_mission"),
        "adaptation_mode": adaptation_mode,
        "failure_kind": failure_kind,
        "selected_strategy": adapted_choice["route_id"],
        "initial_strategy": initial_choice["route_id"],
        "degraded_initial_strategy": degraded_initial["route_id"],
        "latency_ms_initial": initial_choice["latency_ms"],
        "latency_ms_without_replan": degraded_initial["latency_ms"],
        "latency_ms_selected": adapted_choice["latency_ms"],
        "latency_delta_pct_vs_no_replan": latency_delta_pct,
        "cost_without_replan": degraded_initial["cost"],
        "cost_selected": adapted_choice["cost"],
        "cost_delta_pct_vs_no_replan": cost_delta_pct,
        "reliability_without_replan": degraded_initial["reliability"],
        "reliability_selected": adapted_choice["reliability"],
        "reliability_delta_pct_vs_no_replan": reliability_delta_pct,
        "risk_selected": adapted_choice["risk"],
        "pipeline_stage_count": len(pipeline["stages"]),
        "generated_pipeline": True,
        "applied_event_count": len(applied_events),
    }

    sources = [dict(source) for source in scenario.get("sources", []) or []]
    sensor_stream = []
    for index, source in enumerate(sources):
        sensor_stream.append(
            {
                "time_s": index * 4,
                "source_id": source.get("source_id", f"source_{index}"),
                "kind": source.get("kind", "stream"),
                "rate_hz": source.get("rate_hz", 1.0),
                "quality": source.get("quality", 1.0),
                "event": "",
            }
        )
    for event in applied_events:
        sensor_stream.append(
            {
                "time_s": event.get("time_s", 0.0),
                "source_id": event.get("target_route", ""),
                "kind": event.get("kind", ""),
                "rate_hz": 0.0,
                "quality": 0.0,
                "event": event.get("description", ""),
            }
        )
    sensor_stream = sorted(sensor_stream, key=lambda item: _safe_float(item.get("time_s")))

    constraints = dict(scenario.get("constraints", {}) or {})
    feature_table = [
        {
            "feature": "source_count",
            "value": len(sources),
            "unit": "streams",
            "source": "scenario",
        },
        {
            "feature": "route_count",
            "value": len(routes),
            "unit": "routes",
            "source": "scenario",
        },
        {
            "feature": "latency_budget_ms",
            "value": constraints.get("latency_budget_ms"),
            "unit": "ms",
            "source": "constraints",
        },
        {
            "feature": "risk_ceiling",
            "value": constraints.get("risk_ceiling"),
            "unit": "ratio",
            "source": "constraints",
        },
        {
            "feature": "min_reliability",
            "value": constraints.get("min_reliability"),
            "unit": "ratio",
            "source": "constraints",
        },
    ]
    feature_table.extend(fred_fixture_feature_rows())

    decision_timeline = [
        {
            "step": 1,
            "phase": "ingest",
            "decision": f"Loaded {len(sources)} streams and {len(routes)} route candidates",
            "selected_strategy": "",
        },
        {
            "step": 2,
            "phase": "pipeline",
            "decision": f"Generated {len(pipeline['stages'])} pipeline stages",
            "selected_strategy": "",
        },
        {
            "step": 3,
            "phase": "baseline_decision",
            "decision": f"Initial best route: {initial_choice['route_id']}",
            "selected_strategy": initial_choice["route_id"],
        },
        {
            "step": 4,
            "phase": "failure",
            "decision": f"Applied {len(applied_events)} selected failure event(s)",
            "selected_strategy": degraded_initial["route_id"],
        },
        {
            "step": 5,
            "phase": "replan",
            "decision": f"Adapted best route: {adapted_choice['route_id']}",
            "selected_strategy": adapted_choice["route_id"],
        },
        {
            "step": 6,
            "phase": "evidence",
            "decision": "Exported decision metrics and analysis artifacts",
            "selected_strategy": adapted_choice["route_id"],
        },
    ]

    mission_decision = {
        "scenario": scenario_name,
        "objective": scenario.get("objective", ""),
        "selected_strategy": adapted_choice,
        "initial_strategy": initial_choice,
        "degraded_initial_strategy": degraded_initial,
        "applied_events": applied_events,
        "constraints": constraints,
    }

    return {
        "artifact_stem": artifact_stem,
        "summary": summary,
        "mission_decision": mission_decision,
        "generated_pipeline": pipeline,
        "sensor_stream": sensor_stream,
        "feature_table": feature_table,
        "candidate_routes": baseline_scored + post_failure_scored,
        "decision_timeline": decision_timeline,
    }


__all__ = [
    "MissionWeights",
    "apply_failure_events",
    "build_decision_artifacts",
    "build_generated_pipeline",
    "choose_route",
    "score_routes",
]
