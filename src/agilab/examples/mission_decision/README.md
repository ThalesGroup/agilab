# Mission Decision Example

## Purpose

Runs `mission_decision_project`, a deterministic public demo for autonomous
mission-data decision making.

## What You Learn

- How AGILAB packages a richer decision workflow behind the same install/run
  pattern as the smaller examples.
- How scenario inputs, decision objectives, and simulated failures are passed as
  explicit `RunRequest.params`.
- How one run can produce multiple analysis artifacts for a decision page.

## Install

```bash
python ~/log/execute/mission_decision/AGI_install_mission_decision.py
```

## Run

```bash
python ~/log/execute/mission_decision/AGI_run_mission_decision.py
```

## Expected Input

The app seeds a public synthetic scenario under `mission_decision/scenarios`.

## Expected Output

The run writes decision artifacts under `mission_decision/results`, including
mission decisions, generated pipeline data, candidate routes, and timeline
tables for the analysis page.

## Read The Script

Open `AGI_run_mission_decision.py` and look for these lines first:

- `objective="balanced_mission"` explains the decision goal.
- `adaptation_mode="auto_replan"` enables the replanning behavior.
- `failure_kind="bandwidth_drop"` selects the synthetic incident.
- `reset_target=True` keeps the demo output reproducible.

## Change One Thing

After the default run works, change only `failure_kind` or `objective`. Keep
`nfile=1` so the result stays fast and easy to compare.

## Troubleshooting

- If the run has no scenario input, verify `mission_decision/scenarios`.
- If the decision page looks stale, rerun with `reset_target=True`.
- If you need a simpler example first, run `flight` before this decision demo.
