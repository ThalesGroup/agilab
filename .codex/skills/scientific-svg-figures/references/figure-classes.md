# Figure Classes

Use this reference when deciding the structural pattern before drawing the SVG.

## 1. Architecture Stack

Use for:
- platform/component decomposition
- deployment architecture
- layered systems
- control/data/service separation

Layout pattern:
- top summary banner optional
- 2-4 vertical columns or horizontal layers
- arrows mainly between adjacent layers
- side notes only if they do not compete with the main stack

Good fit:
- AGILAB architecture
- agent/runtime/service separation
- app/worker/cluster decomposition

## 2. Pipeline or Workflow

Use for:
- preprocessing to training to evaluation
- ETL or simulation chains
- experiment execution order
- conceptual data flow

Layout pattern:
- strong left-to-right or top-to-bottom reading order
- one dominant connector spine
- optional parallel branches
- inputs/outputs visually separated from transformation steps

Good fit:
- FCAS scenario generation to routing evaluation
- notebook-to-project migrations
- multi-stage data preparation

## 3. Training Loop or Methodology

Use for:
- PPO or actor-critic loops
- optimizer/data collection/evaluation interactions
- online feedback cycles

Layout pattern:
- central loop with explicit arrow cycle
- offline configuration and artifacts outside the loop
- train vs inference separated as different zones if both appear
- reward/loss/evaluation arrows visually lighter than main loop arrows

Good fit:
- PPO-GNN training
- path actor-critic methodology
- benchmark-and-retrain workflows

## 4. Comparison Grid

Use for:
- baseline vs proposal
- method A vs method B
- train vs inference
- capability comparison

Layout pattern:
- 2-4 peer cards or columns
- one shared title row
- same internal structure across peers
- explicit comparison axis labels

Good fit:
- PPO-GNN vs path actor-critic
- local vs cluster execution
- old architecture vs refactored architecture

## 5. Result Summary Panel

Use for:
- KPI summary
- outcome highlights
- evaluation takeaway figure

Layout pattern:
- one dominant takeaway
- 2-6 supporting metrics or notes
- short labels and restrained connector use

Good fit:
- productivity KPI summary
- experiment outcome recap
- report executive visual summary

## 6. Timeline or Sequence

Use for:
- lifecycle phases
- release or integration steps
- event chronology

Layout pattern:
- one axis
- milestone nodes or grouped phases
- keep labels close to milestones

Good fit:
- deployment lifecycle
- experiment schedule
- document review sequence

## Selection Heuristic

- If the key idea is "what talks to what", use Architecture Stack.
- If the key idea is "what happens next", use Pipeline or Timeline.
- If the key idea is "what repeats and feeds back", use Training Loop.
- If the key idea is "how two or more things differ", use Comparison Grid.
- If the key idea is "what the outcome is", use Result Summary Panel.
