from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence


CONFIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "builtin"
    / "uav_relay_queue_project"
    / "service_templates"
    / "train_then_serve_policy_run.json"
)
DEFAULT_OUTPUT_DIR = Path.home() / "log" / "execute" / "train_then_serve"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    with path.expanduser().open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise SystemExit(f"Train-then-serve config must be a JSON object: {path}")
    return payload


def score_candidate(candidate: dict[str, Any], weights: dict[str, Any]) -> float:
    capacity_score = _float(candidate.get("capacity_mbps")) / 10.0
    latency_score = _float(candidate.get("latency_ms")) / 100.0
    queue_score = _float(candidate.get("queue_depth"))
    risk_score = _float(candidate.get("risk"))
    score = (
        capacity_score * _float(weights.get("capacity_mbps"))
        + latency_score * _float(weights.get("latency_ms"))
        + queue_score * _float(weights.get("queue_depth"))
        + risk_score * _float(weights.get("risk"))
    )
    return round(score, 4)


def build_prediction_sample(config: dict[str, Any]) -> dict[str, Any]:
    request = dict(config.get("prediction_request") or {})
    candidates = [
        dict(candidate)
        for candidate in request.get("candidate_relays", [])
        if isinstance(candidate, dict)
    ]
    if not candidates:
        raise SystemExit("Train-then-serve config must define candidate_relays.")

    weights = dict(config.get("policy_scoring") or {})
    ranked = sorted(
        (
            {
                "relay_id": str(candidate.get("id")),
                "score": score_candidate(candidate, weights),
                "latency_ms": round(_float(candidate.get("latency_ms")), 3),
                "queue_depth": round(_float(candidate.get("queue_depth")), 3),
                "capacity_mbps": round(_float(candidate.get("capacity_mbps")), 3),
                "risk": round(_float(candidate.get("risk")), 3),
            }
            for candidate in candidates
        ),
        key=lambda item: (-_float(item["score"]), item["relay_id"]),
    )
    selected = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None
    margin = selected["score"] - _float(runner_up["score"]) if runner_up else selected["score"]
    confidence = max(0.0, min(1.0, 0.5 + margin * 2.5))
    return {
        "schema": "agilab.example.train_then_serve.prediction.v1",
        "request": {
            "source_queue_depth": round(_float(request.get("source_queue_depth")), 3),
            "candidate_count": len(candidates),
        },
        "decision": {
            "selected_relay": selected["relay_id"],
            "action": "route_via_relay",
            "confidence": round(confidence, 3),
            "score": selected["score"],
        },
        "ranked_relays": ranked,
    }


def build_service_contract(config: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    service = dict(config.get("service") or {})
    training_run = dict(config.get("training_run") or {})
    return {
        "schema": "agilab.example.train_then_serve.contract.v1",
        "service_name": str(service.get("name") or "policy_service"),
        "service_version": str(service.get("version") or "preview"),
        "source_training_run": {
            "app": str(training_run.get("app") or "unknown"),
            "trainer": str(training_run.get("trainer") or "unknown"),
            "run_id": str(training_run.get("run_id") or "unknown"),
            "model_artifact": str(training_run.get("model_artifact") or ""),
        },
        "input_schema": dict(service.get("input_schema") or {}),
        "output_schema": dict(service.get("output_schema") or {}),
        "health_thresholds": dict(service.get("health_thresholds") or {}),
        "sample_decision": prediction["decision"],
    }


def build_service_health(config: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    service = dict(config.get("service") or {})
    thresholds = dict(service.get("health_thresholds") or {})
    selected_latency = next(
        (
            item["latency_ms"]
            for item in prediction["ranked_relays"]
            if item["relay_id"] == prediction["decision"]["selected_relay"]
        ),
        0.0,
    )
    latency_budget = _float(thresholds.get("latency_budget_ms"), default=0.0)
    latency_ok = selected_latency <= latency_budget if latency_budget > 0 else True
    return {
        "schema": "agi.service.health.v1",
        "status": "running",
        "workers_running_count": 1,
        "workers_unhealthy_count": 0,
        "workers_restarted_count": 0,
        "restart_rate": 0.0,
        "latency_budget_ms": latency_budget,
        "sample_latency_ms": selected_latency,
        "latency_ok": latency_ok,
        "ok": latency_ok,
    }


def run_preview(
    *,
    config_path: Path = CONFIG_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    config = load_config(config_path)
    output_dir = output_dir.expanduser()
    artifact_dir = output_dir / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    prediction = build_prediction_sample(config)
    contract = build_service_contract(config, prediction)
    health = build_service_health(config, prediction)

    contract_path = artifact_dir / "service_contract.json"
    health_path = artifact_dir / "service_health.json"
    prediction_path = artifact_dir / "prediction_sample.json"
    summary_path = output_dir / "train_then_serve_preview.json"

    contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True), encoding="utf-8")
    health_path.write_text(json.dumps(health, indent=2, sort_keys=True), encoding="utf-8")
    prediction_path.write_text(json.dumps(prediction, indent=2, sort_keys=True), encoding="utf-8")

    summary = {
        "example": "train_then_serve",
        "goal": "Teach the handoff from a trained policy artifact to a service-ready IO and health contract.",
        "phases": [
            "trained_policy_artifact",
            "frozen_service_contract",
            "prediction_sample",
            "service_health_gate",
        ],
        "selected_relay": prediction["decision"]["selected_relay"],
        "service_ready": bool(health["ok"]),
        "artifacts": {
            "service_contract": str(contract_path),
            "service_health": str(health_path),
            "prediction_sample": str(prediction_path),
        },
        "real_training": False,
        "real_service_started": False,
        "claim_boundary": (
            "This preview validates the train-then-serve artifact contract. It "
            "does not train SB3, start persistent workers, or replace production "
            "serving infrastructure."
        ),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview the AGILAB train-then-serve policy handoff without starting a service."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help="Path to an agilab.example.train_then_serve.v1 JSON config.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Where to write the contract, health, prediction, and preview JSON files.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> dict[str, Any]:
    args = _parse_args(argv)
    summary = run_preview(config_path=args.config, output_dir=args.output_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


if __name__ == "__main__":
    main()
