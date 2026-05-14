# Train-Then-Serve Example

## Purpose

Shows the product handoff after a policy has been trained: keep the training
artifact, freeze a service IO contract, run one prediction sample, and evaluate
a service health payload. It is intentionally read-only by default. It does not
train SB3, start Dask, or launch persistent service workers.

Use this when you want to explain:

```text
trained policy -> service contract -> prediction sample -> health gate
```

## What You Learn

- A trained model is not enough; operators also need IO schemas, a model
  artifact path, and health thresholds.
- `service_contract.json`, `prediction_sample.json`, and `service_health.json`
  are the minimal bridge between experiment evidence and an operational
  prototype.
- AGILAB can teach the handoff without inventing a model registry or starting
  a long-lived serving stack.
- The real SB3 service route can reuse the same artifact shape once a real
  policy exists.

## Install

There is no separate project install for this preview. Install AGILAB first.
Use the optional `sb3_trainer_project` later when you want a real train and
service run.

## Run

From a source checkout:

```bash
uv --preview-features extra-build-dependencies run python src/agilab/examples/train_then_serve/preview_train_then_serve.py
```

From an installed AGILAB package, locate the packaged script:

```bash
python -c "from pathlib import Path; import agilab; print(Path(agilab.__file__).with_name('examples') / 'train_then_serve' / 'preview_train_then_serve.py')"
```

Then run it:

```bash
python preview_train_then_serve.py
```

## Expected Input

The script reads the built-in
`uav_relay_queue_project/service_templates/train_then_serve_policy_run.json`
policy handoff contract with:

- one source training run and model artifact path
- service name, version, IO schemas, and health thresholds
- one prediction request with candidate relay features
- one transparent deterministic scoring rule used only for the preview

## Expected Output

The script writes:

```text
~/log/execute/train_then_serve/train_then_serve_preview.json
~/log/execute/train_then_serve/artifacts/service_contract.json
~/log/execute/train_then_serve/artifacts/service_health.json
~/log/execute/train_then_serve/artifacts/prediction_sample.json
```

The expected selected relay is `relay_beta`, and `service_ready` should be
`true` because the prediction sample stays within the latency budget.

## Expected Preview

Read the output as the handoff checklist:

| Field | Meaning |
|---|---|
| `phases` | The train-then-serve sequence represented by the preview. |
| `selected_relay` | The relay chosen by the deterministic sample policy. |
| `service_ready` | Whether the sample health payload passes the latency gate. |
| `artifacts.service_contract` | The frozen IO and health contract. |
| `artifacts.prediction_sample` | The sample decision that proves the contract shape. |
| `real_service_started` | Always `false` for this preview. |

## Preview Versus Real Serving

This preview is a teaching contract. A real run should happen in
`sb3_trainer_project` with an actual model artifact. The preview stays useful
because it makes the expected service files explicit before operators start a
persistent worker loop.

## Read The Script

Open `preview_train_then_serve.py` and look for these functions first:

- `build_prediction_sample()` scores candidate relays and writes one decision.
- `build_service_contract()` freezes the IO schema and model artifact path.
- `build_service_health()` evaluates the sample against the latency budget.
- `run_preview()` writes all artifacts and marks `real_service_started = false`.

## Change One Thing

Copy the built-in policy handoff template, change `latency_budget_ms` from
`80.0` to `50.0`, rerun the preview with `--config <copy>.json`, and inspect how
`service_ready` changes. Restore the default before using the sample as the
normal handoff proof.

## Troubleshooting

- If the preview fails to read JSON, validate that the policy handoff template
  is still a JSON object.
- If `selected_relay` changes unexpectedly, inspect `policy_scoring` and the
  candidate relay metrics first.
- If you need real service lifecycle operations, use the `service_mode` example
  or `AGI.serve`; do not extend this preview into a hidden service runner.
