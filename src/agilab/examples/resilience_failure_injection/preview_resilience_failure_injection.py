from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Sequence


SCENARIO_PATH = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "builtin"
    / "uav_queue_project"
    / "scenario_templates"
    / "resilience_failure_injection_scenario.json"
)
DEFAULT_OUTPUT_PATH = (
    Path.home()
    / "log"
    / "execute"
    / "resilience_failure_injection"
    / "resilience_preview.json"
)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_scenario(path: Path = SCENARIO_PATH) -> dict[str, Any]:
    with path.expanduser().open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise SystemExit(f"Scenario must be a JSON object: {path}")
    return payload


def _affected_by_failure(route: dict[str, Any], failure_event: dict[str, Any]) -> bool:
    affected_relays = {str(item) for item in failure_event.get("affected_relays", [])}
    route_relays = {str(item) for item in route.get("relays", [])}
    return bool(affected_relays & route_relays)


def apply_failure(route: dict[str, Any], failure_event: dict[str, Any]) -> dict[str, Any]:
    degraded = deepcopy(route)
    affected = _affected_by_failure(degraded, failure_event)
    if affected:
        degraded["delivery_ratio"] = max(
            0.0,
            _float(degraded.get("delivery_ratio")) - _float(failure_event.get("delivery_penalty")),
        )
        degraded["latency_ms"] = _float(degraded.get("latency_ms")) + _float(
            failure_event.get("latency_penalty_ms")
        )
        degraded["risk"] = min(
            1.0,
            _float(degraded.get("risk")) + _float(failure_event.get("risk_penalty")),
        )
    degraded["failure_affected"] = affected
    return degraded


def apply_policy_adjustment(
    route: dict[str, Any],
    policy_adjustment: dict[str, Any] | None,
) -> dict[str, Any]:
    adjusted = deepcopy(route)
    if not policy_adjustment:
        return adjusted
    adjusted["delivery_ratio"] = min(
        1.0,
        _float(adjusted.get("delivery_ratio")) + _float(policy_adjustment.get("delivery_bonus")),
    )
    adjusted["latency_ms"] = max(
        0.0,
        _float(adjusted.get("latency_ms")) - _float(policy_adjustment.get("latency_bonus_ms")),
    )
    adjusted["risk"] = max(
        0.0,
        _float(adjusted.get("risk")) - _float(policy_adjustment.get("risk_bonus")),
    )
    adjusted["policy_adjusted"] = True
    return adjusted


def score_route(route: dict[str, Any], weights: dict[str, Any]) -> float:
    score = (
        _float(route.get("delivery_ratio")) * _float(weights.get("delivery"))
        + _float(route.get("latency_ms")) * _float(weights.get("latency_ms"))
        + _float(route.get("risk")) * _float(weights.get("risk"))
        + _float(route.get("energy_cost")) * _float(weights.get("energy_cost"))
        + _float(route.get("control_cost")) * _float(weights.get("control_cost"))
    )
    return round(score, 3)


def _route_by_id(routes: list[dict[str, Any]], route_id: str) -> dict[str, Any]:
    for route in routes:
        if str(route.get("id")) == route_id:
            return route
    raise SystemExit(f"Unknown route_id in resilience scenario: {route_id}")


def _rank_routes(routes: list[dict[str, Any]], weights: dict[str, Any]) -> list[dict[str, Any]]:
    ranked = [
        {
            "route_id": str(route.get("id")),
            "label": str(route.get("label") or route.get("id")),
            "score": score_route(route, weights),
            "latency_ms": round(_float(route.get("latency_ms")), 3),
            "delivery_ratio": round(_float(route.get("delivery_ratio")), 3),
            "risk": round(_float(route.get("risk")), 3),
            "failure_affected": bool(route.get("failure_affected", False)),
        }
        for route in routes
    ]
    return sorted(ranked, key=lambda item: (-_float(item["score"]), item["route_id"]))


def _select_strategy_route(
    strategy: dict[str, Any],
    degraded_routes: list[dict[str, Any]],
    weights: dict[str, Any],
) -> dict[str, Any]:
    selection = str(strategy.get("selection") or "fixed")
    candidates = degraded_routes
    if "risk_guard" in strategy:
        risk_guard = _float(strategy.get("risk_guard"), default=1.0)
        candidates = [route for route in candidates if _float(route.get("risk")) <= risk_guard]
    if "control_guard" in strategy:
        control_guard = _float(strategy.get("control_guard"), default=1.0e9)
        candidates = [
            route for route in candidates if _float(route.get("control_cost")) <= control_guard
        ]
    if not candidates:
        candidates = degraded_routes

    if selection in {"fixed", "route"}:
        route = _route_by_id(degraded_routes, str(strategy.get("route_id")))
    elif selection == "best_after_failure":
        route = max(candidates, key=lambda candidate: score_route(candidate, weights))
    else:
        raise SystemExit(f"Unknown strategy selection: {selection}")

    return apply_policy_adjustment(route, strategy.get("policy_adjustment"))


def compare_strategies(scenario: dict[str, Any]) -> dict[str, Any]:
    routes = [dict(route) for route in scenario.get("routes", []) if isinstance(route, dict)]
    strategies = [
        dict(strategy) for strategy in scenario.get("strategies", []) if isinstance(strategy, dict)
    ]
    if not routes or not strategies:
        raise SystemExit("Scenario must define non-empty routes and strategies.")

    weights = dict(scenario.get("score_weights", {}))
    failure_event = dict(scenario.get("failure_event", {}))
    baseline_routes = [apply_policy_adjustment(route, None) for route in routes]
    degraded_routes = [apply_failure(route, failure_event) for route in routes]
    baseline_ranking = _rank_routes(baseline_routes, weights)
    degraded_ranking = _rank_routes(degraded_routes, weights)

    comparisons: list[dict[str, Any]] = []
    for strategy in strategies:
        selected = _select_strategy_route(strategy, degraded_routes, weights)
        selected_score = score_route(selected, weights)
        original_route = _route_by_id(routes, str(selected.get("id")))
        original_score = score_route(original_route, weights)
        comparisons.append(
            {
                "strategy_id": str(strategy.get("id")),
                "family": str(strategy.get("family") or "unknown"),
                "selected_route": str(selected.get("id")),
                "score_after_failure": selected_score,
                "score_before_failure_for_route": original_score,
                "score_delta": round(selected_score - original_score, 3),
                "latency_ms": round(_float(selected.get("latency_ms")), 3),
                "delivery_ratio": round(_float(selected.get("delivery_ratio")), 3),
                "risk": round(_float(selected.get("risk")), 3),
                "failure_affected": bool(selected.get("failure_affected", False)),
                "policy_adjusted": bool(selected.get("policy_adjusted", False)),
                "description": str(strategy.get("description") or ""),
            }
        )

    comparisons = sorted(
        comparisons,
        key=lambda item: (-_float(item["score_after_failure"]), item["strategy_id"]),
    )
    return {
        "failure_event": {
            "id": str(failure_event.get("id") or "unknown"),
            "description": str(failure_event.get("description") or ""),
            "affected_relays": [str(item) for item in failure_event.get("affected_relays", [])],
        },
        "baseline_ranking": baseline_ranking,
        "degraded_ranking": degraded_ranking,
        "strategy_comparison": comparisons,
        "recommended_strategy": comparisons[0],
    }


def build_preview(
    *,
    scenario_path: Path = SCENARIO_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> dict[str, Any]:
    scenario = load_scenario(scenario_path)
    comparison = compare_strategies(scenario)
    preview = {
        "example": "resilience_failure_injection",
        "goal": "Compare fixed, replanned, search-based, and active-policy responses on one failure scenario.",
        "scenario": str(scenario.get("scenario") or "unknown"),
        "objective": str(scenario.get("objective") or ""),
        "comparison": comparison,
        "real_policy_training": False,
        "claim_boundary": (
            "This preview explains the failure-injection contract. It is not a "
            "certified MARL benchmark or a production routing policy."
        ),
        "next_real_run": "Use sb3_trainer_project when available to train or evaluate real PPO/GA policies.",
    }
    output_path = output_path.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(preview, indent=2, sort_keys=True), encoding="utf-8")
    return preview


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview a resilience/failure-injection comparison without training a model."
    )
    parser.add_argument(
        "--scenario",
        type=Path,
        default=SCENARIO_PATH,
        help="Path to an agilab.example.resilience_failure_injection.v1 JSON scenario.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Where to write the resilience preview JSON.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> dict[str, Any]:
    args = _parse_args(argv)
    preview = build_preview(scenario_path=args.scenario, output_path=args.output)
    print(json.dumps(preview, indent=2, sort_keys=True))
    return preview


if __name__ == "__main__":
    main()
