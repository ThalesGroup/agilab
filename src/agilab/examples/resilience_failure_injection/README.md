# Resilience Failure Injection Example

## Purpose

Shows how to compare routing strategies after a controlled degradation event.
The example injects an interference event on one relay and compares four
responses over the same scenario contract:

```text
fixed route -> ILP-style replan -> GA-style guarded search -> PPO-style active mesh response
```

It is intentionally read-only by default. It does not train a model, start a
Dask cluster, or claim certified MARL behavior. It writes a deterministic JSON
preview that explains the failure event, route ranking, and recommended
strategy after failure.

## What You Learn

- Failure injection should be a scenario contract, not hidden notebook state.
- A fixed low-latency route can be optimal before failure and fragile after
  failure.
- ILP-style replanning, GA-style guarded search, and PPO-style active-mesh
  policies can be compared through the same metrics.
- Active Mesh Optimization is a useful next direction, but this preview keeps
  the claim bounded to a centralized policy-response contract.

## Install

There is no separate project install for this preview. Install AGILAB first.
Use the optional `sb3_trainer_project` later when you want a real trainer run.

## Run

From a source checkout:

```bash
uv --preview-features extra-build-dependencies run python src/agilab/examples/resilience_failure_injection/preview_resilience_failure_injection.py
```

From an installed AGILAB package, locate the packaged script:

```bash
python -c "from pathlib import Path; import agilab; print(Path(agilab.__file__).with_name('examples') / 'resilience_failure_injection' / 'preview_resilience_failure_injection.py')"
```

Then run it:

```bash
python preview_resilience_failure_injection.py
```

## Expected Input

The script reads the built-in
`uav_queue_project/scenario_templates/resilience_failure_injection_scenario.json`
scenario with:

- one relay degradation event: `jam_relay_alpha`
- four candidate routes: fast, balanced, robust, and active-mesh
- four strategy families: fixed, ILP-style, GA-style, and PPO-style
- one transparent scoring formula for delivery, latency, risk, energy, and
  control cost

## Expected Output

The script writes:

```text
~/log/execute/resilience_failure_injection/resilience_preview.json
```

and prints the same JSON summary. The expected recommendation is
`ppo_active_mesh_policy` because the simulated policy adjustment improves the
active-mesh route after the injected failure.

## Expected Preview

Read the output as a comparison table:

| Field | Meaning |
|---|---|
| `baseline_ranking` | Route ranking before failure. |
| `degraded_ranking` | Route ranking after the relay degradation. |
| `strategy_comparison` | Strategy-level result after each strategy selects a route. |
| `recommended_strategy` | Highest scoring strategy after failure. |
| `real_policy_training` | Always `false` for this preview. |
| `claim_boundary` | The explicit limitation to avoid over-claiming MARL. |

## Preview Versus Real Training

This preview is a teaching contract. It is useful before a real trainer because
it makes the failure event, candidate routes, score weights, and expected
artifact shape explicit.

Use `sb3_trainer_project` when you want a real PPO or GA execution route. Keep
this preview in demos when you need a deterministic explanation that runs
without optional ML or simulator dependencies.

## Read The Script

Open `preview_resilience_failure_injection.py` and look for these functions
first:

- `apply_failure()` applies the degradation event to affected routes.
- `score_route()` keeps the ranking formula transparent.
- `compare_strategies()` compares fixed, replan, GA-style, and PPO-style
  behavior on the same route set.
- `build_preview()` writes the JSON proof and marks
  `real_policy_training = false`.

## Change One Thing

Copy the built-in scenario template, change `delivery_penalty` from `0.4` to
`0.1`, rerun the preview with `--scenario <copy>.json`, and inspect whether the
fixed route remains competitive. Restore the value before using the sample as
the default failure case.

## Troubleshooting

- If the preview fails to read JSON, validate that the scenario template is
  still a JSON object.
- If the recommended strategy changes unexpectedly, inspect
  `score_weights` before changing route metrics.
- If you need real training metrics, do not extend this preview into a hidden
  trainer. Use a real AGILAB app such as `sb3_trainer_project` and log the run
  artifacts explicitly.
