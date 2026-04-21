# AGILAB Launch Package

This file is the execution-ready launch package for the current public positioning wave.

Use it with:

- [GITHUB_REPO_POSITIONING.md](../growth/GITHUB_REPO_POSITIONING.md)
- [STAR_GROWTH_PLAN.md](../growth/STAR_GROWTH_PLAN.md)
- [LAUNCH_EXECUTION_CHECKLIST.md](LAUNCH_EXECUTION_CHECKLIST.md)
- [WEEKLY_GROWTH_TRACKER.md](../growth/WEEKLY_GROWTH_TRACKER.md)

## Locked launch theme

`Reproducible AI/ML workflows from local experimentation to distributed workers and long-lived services.`

Everything in this package should reinforce the same idea:

- AGILAB is for reproducible AI/ML workflows
- the same app can move from local run to distributed execution
- the workflow does not stop at one-off experiments because service mode is part of the path

Do not fragment this launch wave across multiple unrelated product stories.

## Canonical demo asset

Use one primary demo asset for this wave:

- published public video: `https://youtu.be/kOMDyvbnC9w`
- local canonical reel: regenerate locally when needed with the command below
- primary still image fallback: [`docs/source/diagrams/agilab_social_card.svg`](../../docs/source/diagrams/agilab_social_card.svg)
- supporting workflow explainer: [`docs/source/diagrams/agilab_readme_tour.svg`](../../docs/source/diagrams/agilab_readme_tour.svg)

If the local video asset is missing, regenerate it before packaging the post:

```bash
uv --preview-features extra-build-dependencies run python tools/build_product_demo_reel.py --variant flight
```

Reference app for all copy:

- `flight_project`

Reason:

- it is built-in
- it already anchors the README tour
- it gives one concrete path from UI to workers to analysis

## ML-facing secondary asset

Use this package when the channel needs proof of a real ML workflow, not just a
general product tour.

- published public video: `https://youtu.be/yIZ6vTBg95w`
- local ML reel/poster: regenerate locally when needed with the command below

If the local video asset is missing, regenerate it before packaging the post:

```bash
uv --preview-features extra-build-dependencies run python tools/build_product_demo_reel.py --variant meteo_forecast --mp4 artifacts/demo_media/meteo_forecast/agilab_meteo_forecast.mp4 --gif artifacts/demo_media/meteo_forecast/agilab_meteo_forecast.gif --poster artifacts/demo_media/meteo_forecast/agilab_meteo_forecast_poster.png
```

Reference app for this package:

- `meteo_forecast_project`

Use it for:

- YouTube packaging of the public ML reel
- LinkedIn posts aimed at applied ML engineers
- any channel where the proof must visibly end on metrics and prediction curves

Do not use it as the general first-wave repo asset. Keep `flight_project` as the
primary broad launch path.

## Technical three-project demo plan

Use this plan when the goal is to prove that AGILAB can cover:

- data workflow
- ML workflow
- RL workflow

This is not a 45-second teaser anymore. Treat it as a technical hero demo.

### Format

- target length: `70-75 seconds`
- preferred capture style: real live capture, not a synthetic one-app reel
- editing rule: one short act per project, then one closing synthesis frame

Do not force this into the current short-reel pattern. The existing reel system
is optimized for one app and one claim. A three-project proof needs more time and
must stay honest.

### Project sequence

1. Data workflow: `execution_pandas_project`
2. ML workflow: `meteo_forecast_project`
3. RL workflow: `sb3_trainer_project`

### Scope note

The first two projects are public built-ins in `agilab`.

The RL proof comes from the sibling apps repo via
[`sb3_trainer_project`](/Users/agi/PycharmProjects/thales_agilab/apps/sb3_trainer_project).
Do not imply that all three acts come from the same built-in public app set.

### Why this trio

- `execution_pandas_project` proves data generation, partitioning, and repeatable
  compute instead of a toy notebook
- `meteo_forecast_project` proves a real ML path ending on forecast metrics and
  prediction curves
- `sb3_trainer_project` proves AGILAB can also host RL policy training instead of
  stopping at classic supervised workflows

### Story structure

#### Act 1: Data

- show `execution_pandas_project` selected in `PROJECT`
- show only two high-signal data settings
- show `ORCHESTRATE` building one repeatable compute run
- flash `PIPELINE` only long enough to prove replayable data/export steps
- finish the act on a concrete exported dataset/result signal, not just a config form

#### Act 2: ML

- switch to `meteo_forecast_project`
- show station and horizon in `PROJECT`
- show backtest/forecast execution intent in `ORCHESTRATE`
- flash replayable forecast steps in `PIPELINE`
- finish on `ANALYSIS` with `MAE`, `RMSE`, `MAPE`, and observed-vs-predicted curves

#### Act 3: RL

- switch to `sb3_trainer_project`
- show a real trainer choice such as PPO-GNN or path actor-critic in `PROJECT`
- show the runnable training path in `ORCHESTRATE`
- show replayable training/inference steps in `PIPELINE` only if already visible
- finish on exported policy artifacts or routing-analysis evidence, not just the args form

#### Closing frame

- one simple synthesis panel:
  - `DATA -> ML -> RL`
  - `one reproducible workflow shell`
  - `PROJECT -> ORCHESTRATE -> PIPELINE -> ANALYSIS`

### Timing guide

- intro: `3s`
- data act: `18s`
- ML act: `21s`
- RL act: `22s`
- closing synthesis: `8s`

### Recording rule

Each act must show one visible proof outcome:

- data: generated/exported dataset or compute result
- ML: forecast metrics and prediction curve
- RL: trained policy artifact, trainer output, or routing-analysis evidence

If one act cannot finish on evidence, do not record yet. Fix the app state first.

Editing rule:

- use hard cuts between acts
- do not leave long-running waits on screen
- if an act needs more than two visible settings, it is too slow

### Positioning rule

Use this asset for:

- technical LinkedIn posts
- direct outreach to ML / RL engineers
- a richer landing-page or release companion video

Do not replace the broad `flight_project` asset with this one for first-time
visitors who only need the product story fast.

### Working title options

- `AGILAB Demo: Data, ML, and RL Workflows in One Reproducible Stack`
- `From Data Pipeline to Forecasting to RL Training in AGILAB`
- `AGILAB Technical Demo: Data Prep, ML Forecasting, and RL Policy Training`

### Capture constraint

The RL act is the pacing risk. If `sb3_trainer_project` makes the video too heavy,
keep the live capture but trim the visible training setup to one clear trainer
selection, one run snippet, and one final policy/output evidence frame.

### Technical fallback asset

If live screen capture is blocked by the operator environment, use the synthetic
composite fallback generated by:

```bash
uv --preview-features extra-build-dependencies run --with imageio --with imageio-ffmpeg \
  python tools/build_three_project_demo_reel.py
```

Use it honestly as a composite technical explainer, not as a claimed live UI
walkthrough.

Current fallback quality bar:

- about `52s`
- `1920x1080`, `30 fps`
- one shared reel language across the three acts
- explicit intro and closing synthesis cards
- data and ML acts rendered by the same AGILAB reel engine as the public
  one-app demos
- RL act rendered in the same visual system, using FCAS routing figures only as
  evidence support

This means the fallback is now credible for technical launch channels. It is no
longer just a placeholder video.

## GitHub About / Topics

### Primary About text

`Open-source platform for reproducible AI/ML workflows, from local experimentation to distributed workers and long-lived services.`

### Backup About text

`Reproducible AI/ML workflows from local UI or CLI to distributed workers, service mode, and analysis.`

### Topics

- `mlops`
- `workflow-orchestration`
- `machine-learning`
- `python`
- `streamlit`
- `distributed-computing`
- `reproducibility`
- `agents`
- `codex`
- `free-threading`

## Launch sequence

### Day 0: repo and asset lock

- confirm README hero, GitHub About text, and docs landing page still match
- confirm `flight_project` remains the canonical demo path
- confirm the video and still asset are both usable

### Day 1: GitHub release / discussion

- publish a release note or pinned discussion using the copy below
- attach or link the flight demo asset
- point readers to the README quick start

### Day 2: LinkedIn

- publish the LinkedIn post below with the same launch theme
- use the flight demo video if possible
- use the social card if video is not practical

### Day 3+: community posts

- Reddit only after checking that the repo landing page still feels sharp
- Hacker News only if the demo and landing page are both clearly stronger than the previous wave

## GitHub discussion / release note

### Title

`AGILAB: clearer onboarding for reproducible AI/ML workflows`

### Body

We refreshed the public AGILAB repo around one clearer idea:

AGILAB is an open-source platform for reproducible AI/ML workflows, from local experimentation to distributed workers and long-lived services.

This launch wave tightens the first-time user path around a built-in `flight_project` demo and a more explicit README story.

What a first-time visitor should now see more quickly:

- what AGILAB is for
- how one app moves from local UI or CLI entrypoints to workers
- where service mode fits
- where analysis fits after execution

What changed in the public repo:

- clearer README positioning
- a more explicit quick-start path
- a 3-minute tour around `flight_project`
- clearer public positioning around reproducibility and orchestration
- better alignment between landing-page text, docs, and demo assets

If you work on applied ML systems and spend too much time stitching together setup, execution, remote runs, and analysis by hand, that is the workflow gap AGILAB is trying to reduce.

Repo:
https://github.com/ThalesGroup/agilab

Docs:
https://thalesgroup.github.io/agilab

## LinkedIn

### Primary post

AGILAB is an open-source platform for reproducible AI/ML workflows.

The core idea is simple: the same app should be able to move from local experimentation to distributed workers and long-lived services without inventing a different control path at each step.

We tightened the public repo around that story:

- clearer README positioning
- a cleaner quick-start path
- a built-in `flight_project` tour
- better visual assets for the landing page

If your team is still hand-wiring environments, scripts, remote execution, and analysis around experiments, that is the workflow overhead AGILAB is meant to reduce.

Repo:
https://github.com/ThalesGroup/agilab

Docs:
https://thalesgroup.github.io/agilab

### Asset for LinkedIn

- first choice: current regenerated `flight` reel
- public fallback link: `https://youtu.be/kOMDyvbnC9w`
- fallback: [`docs/source/diagrams/agilab_social_card.svg`](../../docs/source/diagrams/agilab_social_card.svg)

## ML-facing video package

Use this package with the public meteo reel:

- video: `https://youtu.be/yIZ6vTBg95w`
- poster: regenerate locally if you need a static companion image

### YouTube title

`AGILAB in 45 Seconds: A Real ML Forecast Workflow`

### Backup YouTube title

`AGILAB Demo: A Real ML Forecast Workflow in 45 Seconds`

### YouTube description

This reel shows a real ML workflow in AGILAB, not just a generic product tour.

Using the built-in `meteo_forecast_project`, the flow goes from project selection
to a runnable forecast/backtest path, then ends on analysis with MAE, RMSE, MAPE,
and observed-vs-predicted curves.

Why this matters:

- one reproducible workflow from local experimentation to execution and analysis
- a concrete built-in app instead of a synthetic placeholder
- proof that AGILAB can show real ML outcomes, not only orchestration UI

Repo:
https://github.com/ThalesGroup/agilab

Docs:
https://thalesgroup.github.io/agilab

Video:
https://youtu.be/yIZ6vTBg95w

### Pinned comment

If you want the shortest proof point, watch the last frames: the reel finishes on
forecast metrics and observed-vs-predicted curves, not only on UI navigation.

The built-in app used here is `meteo_forecast_project`.

Repo:
https://github.com/ThalesGroup/agilab

### Thumbnail text

`REAL ML WORKFLOW IN 45s`

### LinkedIn post

Most short product reels show interface motion. This one shows a real ML workflow.

In 45 seconds, AGILAB uses a built-in weather forecasting app to move from project
selection to a runnable forecast/backtest path, then ends on analysis with MAE,
RMSE, MAPE, and observed-vs-predicted curves.

That is the point of AGILAB: keep one reproducible workflow from local
experimentation to execution, service mode, and analysis without rebuilding the
control path at each step.

Video:
https://youtu.be/yIZ6vTBg95w

Repo:
https://github.com/ThalesGroup/agilab

Docs:
https://thalesgroup.github.io/agilab

## Reddit

### Draft

We tightened the open-source AGILAB repo around one clearer workflow story.

AGILAB is aimed at reproducible AI/ML workflows where the same app can move from local experimentation to distributed execution and service mode without rebuilding the whole control path each time.

The public repo now emphasizes:

- a clearer quick-start path
- one built-in demo around `flight_project`
- stronger README positioning for applied ML / orchestration use cases

I would value feedback on whether the landing page now explains the workflow clearly enough:

https://github.com/ThalesGroup/agilab

## Hacker News

Only use this if the landing page and demo asset are both clearly ready.

### Title

`AGILAB: reproducible AI/ML workflows from local experimentation to distributed workers`

### Draft

We have been tightening the open-source presentation of AGILAB, a platform for reproducible AI/ML workflows.

The central idea is that one application should be able to move from local experimentation to distributed workers and long-lived services without creating a different control path at each stage.

This launch wave focuses on:

- clearer public positioning
- a built-in `flight_project` demo
- a tighter README and quick-start path

The angle I would especially value feedback on is whether AGILAB now reads clearly as a workflow/orchestration layer for applied ML rather than just another example-heavy repo.

Repo:
https://github.com/ThalesGroup/agilab

## Do not drift from these rules

- Do not use a different example app in each channel for the same launch wave.
- Do not lead with agent-friendly or free-threaded wording before the reproducibility story is clear.
- Do not post to Hacker News before the repo page is conversion-ready.
- Do not treat this file as brainstorming; update it only when the actual launch package changes.
