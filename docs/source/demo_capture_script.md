# AGILAB Video Tutorial Guide

Use this guide when you want to produce a short AGILAB tutorial package instead of
an isolated video file.

The package has three complementary assets:

- a short live tutorial video or GIF
- a self-generated explainer MP4/GIF/poster
- a static SVG/social kit for README, docs, and launch posts

## Recommended tutorial package

Keep one app per video, but support two stable narrative packs:

- `flight_project`
  - safest default
  - best for newcomer onboarding and first local proof
- `UAV Relay Queue` (`uav_relay_queue_project`)
  - strongest public `PIPELINE` + `ANALYSIS` story
  - best for the main full-tour demo assets

Default recommendation:

- use `flight_project` for newcomer onboarding clips and first-proof demos
- use `UAV Relay Queue` (`uav_relay_queue_project`) for the main full-tour
  product demo when you want a truthful
  `PROJECT -> ORCHESTRATE -> PIPELINE -> ANALYSIS` story

Stable visual assets already tracked in the repo:

- `docs/source/diagrams/agilab_readme_tour.svg`
- `docs/source/diagrams/agilab_social_card.svg`

Generated demo media is intentionally local. Rebuild it when needed instead of
linking documentation to repo-local `artifacts/demo_media/...` files.

Keep two stable public messages instead of forcing one app to carry both roles:

- `flight_project`: `PROJECT -> ORCHESTRATE -> ANALYSIS`, with visible output files
  in between
- `UAV Relay Queue`: `PROJECT -> ORCHESTRATE -> PIPELINE -> ANALYSIS`, ending on
  queue evidence

## Which format to use

Use a live tutorial when you want to show the real UI flow:

- selecting the app
- launching orchestration
- checking the produced files
- ending on analysis results

Use the self-generated explainer when you want a lightweight shareable asset:

- launch posts
- README/social embeds
- quick product intros

Use the static SVG/social kit when you need a lightweight companion asset
around the video:

- one README figure
- one social/static card
- one poster frame

## Fastest live workflow

Concrete capture command for the default `flight_project` tutorial:

```bash
tools/capture_demo_workflow.sh --name agilab-flight --duration 45 --trim 30
```

If you launch the recording from Codex, PyCharm, or another non-interactive
runner, use the Terminal handoff so the interactive macOS recorder runs in a
real operator shell:

```bash
tools/capture_demo_workflow.sh --name agilab-flight --duration 45 --trim 30 --via-terminal
```

Concrete capture command for the `uav_relay_queue_project` variant:

```bash
tools/capture_demo_workflow.sh --name agilab-uav-queue --duration 60 --trim 45
```

This wrapper:

- launches an interactive macOS screen recording with `screencapture`
- stores the raw `.mov` under `artifacts/demo_media/<name>/raw/`
- exports a shareable `.mp4` and `.gif` under `artifacts/demo_media/<name>/edited/`

If you already have a raw recording and only want the export step:

```bash
uv --preview-features extra-build-dependencies run --with imageio-ffmpeg \
  python tools/export_demo_media.py \
  --input artifacts/demo_media/agilab-flight/raw/example.mov \
  --mp4 artifacts/demo_media/agilab-flight/edited/agilab-flight.mp4 \
  --gif artifacts/demo_media/agilab-flight/edited/agilab-flight.gif \
  --duration 30
```

### Data IO 2026 autonomous decision demo

Use this when one app is not enough and the audience needs a sharper story:
mission data enters AGILAB, computation is distributed, constraints change, and
the system returns a decision. The positioning is intentionally execution-first:
chatbot-style demos answer questions, while this demo shows a reproducible path
from data to action.

This is not a chatbot or short teaser. Treat it as a technical hero demo and
keep the recording in the `70-75s` final range.

Tracked companion card:

![Data IO 2026 AGILAB demo card](diagrams/agilab_data_io_2026_card.svg)

Use `docs/source/diagrams/agilab_data_io_2026_card.svg` as the lightweight
shareable poster or thumbnail. The MP4/GIF remain generated local artifacts
under `artifacts/demo_media/` and are intentionally not tracked.

Concrete command:

```bash
tools/capture_three_project_demo.sh --name agilab-data-io-2026 --duration 82 --trim 74
```

If the capture is triggered from an automated or agent-driven shell, use:

```bash
tools/capture_three_project_demo.sh --name agilab-data-io-2026 --duration 82 --trim 74 --via-terminal
```

This wrapper:

- writes a cue sheet under `artifacts/demo_media/<name>/`
- points to the exact project roots for the ingestion, prediction, and decision
  acts
- then delegates the actual recording/export to `tools/capture_demo_workflow.sh`

Default sequence:

1. `execution_pandas_project`
2. `meteo_forecast_project`
3. `uav_relay_queue_project`, or another routing / optimization project passed
   with `--rl-app-root`

Important scope note:

- the default sequence uses public built-ins from `agilab`
- the final decision act is configurable because stronger routing /
  optimization demos may live in an external apps checkout
- keep dynamic-pipeline claims grounded in visible AGILAB steps, generated
  snippets, worker activity, and replayable evidence
- do not publish competitor-specific claims in the public guide; keep the public
  wording focused on AGILAB capability and evidence

Scenario and pipeline:

- inputs: sensor-style streams, network / satcom status, and operational
  constraints such as latency, bandwidth, and risk
- objective: optimize routing and decision-making under dynamic constraints
- pipeline shape: data, cleaning, feature extraction, model selection,
  optimization / RL, simulation, decision
- output: selected strategy plus latency, cost, and reliability metrics

Demo steps:

1. Live Data Ingestion: simulated and real-like mission data, ending on an
   artifact or dashboard refresh.
2. Automatic Pipeline Generation: generated snippets and replayable DAG-style
   steps, with adaptive workflow selection shown through the selected run path.
3. Distributed Execution: visible worker activity or the clearest local-worker
   equivalent, with scaling claims scoped to worker distribution.
4. AI + Optimization Loop: prediction signal plus routing / optimization under
   constraints.
5. Real-Time Adaptation: bandwidth drop, node failure, or risk increase followed
   by recompute, re-optimize, and a new decision.
6. Final Output: selected strategy plus latency, cost, and reliability metrics.

Use this asset for technical audiences. Do not replace the broad one-app intro
video with it for first-time visitors.

Preferred operator cut:

- opener: `4s`
- live ingestion: `15s`
- prediction / constraints: `15s`
- distributed optimization: `21s`
- failure injection and adaptation: `11s`
- decision metrics: `8s`

Keep the act discipline strict:

- show at most two settings before moving on
- use one fast `ORCHESTRATE` proof frame per act
- flash `PIPELINE` only long enough to prove replayability
- end each act on evidence, then cut immediately
- make distributed execution the key moment: show worker activity or the
  clearest available local-worker equivalent
- show the failure injection as a before/after decision change, not as a long
  training sequence
- close on metrics: latency, cost, and reliability

Recommended narration:

- opening: "Most AI demos answer questions. This one takes decisions."
- mid-demo: "This is not a model. This is an autonomous system."
- closing: "AGILAB turns mission data into an executable decision."

Optional add-on:

- air-gapped mode with no internet access and local models only, when the
  environment is configured and validated

Winning criteria:

| Criteria | Strength |
|---|---|
| Innovation | Autonomous pipeline path |
| Scalability | Distributed worker execution |
| Real use case | Mission / network optimization |
| AI depth | ML + optimization / orchestration |
| Differentiation | Not a chatbot |

If interactive screen capture is not possible from your environment, build the
coherent synthetic composite instead:

```bash
uv --preview-features extra-build-dependencies run --with imageio --with imageio-ffmpeg \
  python tools/build_three_project_demo_reel.py
```

Outputs:

- `artifacts/demo_media/agilab-data-io-2026/edited/agilab_data_io_2026_synthetic.mp4`
- `artifacts/demo_media/agilab-data-io-2026/edited/agilab_data_io_2026_synthetic.gif`
- `artifacts/demo_media/agilab-data-io-2026/edited/agilab_data_io_2026_synthetic_poster.png`

These files are generated for local review and publishing workflows. Keep them
out of git unless a separate release channel explicitly needs a media upload.

Current synthetic reel contract:

- `1920x1080`
- `30 fps`
- about `52s`
- one consistent visual system across the three acts
- ingestion and prediction acts rendered from the same AGILAB reel engine as the
  public one-app demos
- decision act rendered in the same style, with routing evidence used only as
  proof material

This is not the old crude fallback anymore. It is a coherent technical
composite built from the same scene language as the one-app reels, then stitched
into one mission-data story:

- intro card
- `execution_pandas_project`
- `meteo_forecast_project`
- `uav_relay_queue_project`, or a configurable routing / optimization decision act
- closing decision card

Use it when you need a deterministic technical explainer rather than a live UI
walkthrough, but still want the video to feel like one consistent product asset.

## Self-generated fallback

Use this when you do not want to rely on interactive capture:

```bash
uv --preview-features extra-build-dependencies run --with imageio --with imageio-ffmpeg \
  python tools/build_demo_explainer.py
```

This produces:

- `artifacts/demo_media/agilab_explainer.gif`
- `artifacts/demo_media/agilab_explainer.mp4`
- `artifacts/demo_media/agilab_explainer_poster.png`

Treat those outputs as local build artifacts, not as stable tracked docs assets.

## Storyboard

### Flight 30-second version

Use this when you want a quick social/demo clip.

1. Show the AGILAB home screen.
2. Show `flight_project` selected in `PROJECT`.
3. Jump to `ORCHESTRATE` and trigger the run path.
4. Show the fresh output folder under `~/log/execute/flight/`.
5. End in `ANALYSIS` on a visible result.

Narration:

`AGILAB gives one app a single control path from selection to execution to analysis.`

### Flight 45-second version

Use this as the default newcomer tutorial.

1. Open AGILAB.
2. Select `src/agilab/apps/builtin/flight_project` in `PROJECT`.
3. Briefly show app settings or source context.
4. Move to `ORCHESTRATE`.
5. Trigger install, distribute, and run.
6. Show that the workflow is packaged and executed without ad-hoc shell glue.
7. Show the fresh files under `~/log/execute/flight/`.
8. Move to `ANALYSIS`.
9. End on a built-in page over produced artifacts.

Narration:

`Instead of hand-wiring environments, scripts, and checks, AGILAB gives the same app one controlled path from UI to workers to analysis.`

### Meteo forecast 45-second version

Use this when the audience expects an actual ML workflow, not only a product tour.

1. Open AGILAB.
2. Select `src/agilab/apps/builtin/meteo_forecast_project` in `PROJECT`.
3. Briefly show the forecasting context:
   - weather dataset
   - target column
   - lag / horizon setup
4. Move to `ORCHESTRATE`.
5. Show one runnable forecast / backtest execution path.
6. Move to `PIPELINE`.
7. Show the replayable steps:
   - load series
   - backtest forecaster
   - forecast next days
   - export metrics and predictions
8. Move to `ANALYSIS`.
9. End on forecast metrics and observed-vs-predicted evidence.

Narration:

`This AGILAB path is a real ML workflow: select the forecasting project, run the backtest cleanly, keep the pipeline replayable, and finish on exported metrics and predictions instead of a notebook-only result.`

### Flight 60-second version

Use this only when you need a slightly more explanatory walkthrough.

Keep the same path, but add one explicit sentence on each stage:

- `PROJECT` defines the app and settings
- `ORCHESTRATE` packages and runs the workflow
- fresh output files make the first proof visible
- `ANALYSIS` ends on visible evidence

Do not add a second app. Do not branch into alternative flows.

### Flight 3-minute version

Use this when you want a narrated newcomer walkthrough, not the full four-page
pipeline tour.

Keep the same single-app path:

1. `PROJECT`
2. `ORCHESTRATE`
3. output folder
4. `ANALYSIS`

Do not introduce a second app, an alternative branch, or a second execution
mode. The extra time is for clarity, not breadth.

Suggested timeline:

1. `0:00 -> 0:20`
   Open the AGILAB home screen and state the single message:
   `one app, one control path from project selection to visible evidence.`
2. `0:20 -> 0:50`
   Go to `PROJECT`, select `src/agilab/apps/builtin/flight_project`, and show
   that the app already carries its own arguments, pages, and outputs.
3. `0:50 -> 1:35`
   Move to `ORCHESTRATE`, show the install / distribute / run areas, and
   explain that AGILAB generates the operational snippet instead of asking the
   user to hand-wire the workflow first.
4. `1:35 -> 2:05`
   Show the fresh output folder under `~/log/execute/flight/` and explain that
   the first proof leaves explicit files instead of only transient logs.
5. `2:05 -> 2:40`
   Move to `ANALYSIS`, open a visible result page, and show that the run ends
   on an operator-facing view rather than raw infrastructure logs.
6. `2:40 -> 3:00`
   Return to the core message and close on the same app/result:
   `AGILAB keeps one app on one coherent path from setup to evidence.`

Suggested narration:

`This is AGILAB in one path. In PROJECT, I select the app and keep its context.
In ORCHESTRATE, AGILAB packages and runs the workflow without ad-hoc shell glue.
Then I check the fresh output files. In ANALYSIS, the workflow ends on visible
evidence, not just logs. The point is not another generic DAG. The point is
one app, one controlled path, from setup to result.`

Suggested click path:

1. Home page
2. `PROJECT`
3. app selector -> `flight_project`
4. one short pause on app context
5. `ORCHESTRATE`
6. one short pause on generated install / run area
7. output folder / run files
8. `ANALYSIS`
9. final pause on a visible result

### UAV queue 45-second version

Use this as the default full-tour product clip.

Keep the same page order:

1. `PROJECT`
2. `ORCHESTRATE`
3. `PIPELINE`
4. `ANALYSIS`

Suggested flow:

1. Open AGILAB.
2. Select `src/agilab/apps/builtin/uav_relay_queue_project` in `PROJECT`
   (`UAV Relay Queue`).
3. Briefly show the routing policy and scenario file.
4. Move to `ORCHESTRATE`.
5. Trigger the run.
6. Move to `PIPELINE`.
7. Show that the run is now replayable as a tracked step.
8. Move to `ANALYSIS`.
9. Open `view_uav_relay_queue_analysis`.
10. End on queue buildup, drops, or route usage.

Narration:

`AGILAB can also turn a lightweight UAV routing experiment into a reproducible
workflow. The point is still the same: one app, one control path, ending on a
visible analysis result.`

### UAV Relay Queue 3-minute version

Use this when you want the more memorable technical demo.

Do not mix it with `flight_project` in the same video. The clarity rule still
holds: one app, one path.

Suggested timeline:

1. `0:00 -> 0:20`
   Open the AGILAB home screen and state the goal:
   `turn a queueing experiment into a reproducible workflow.`
2. `0:20 -> 0:55`
   Go to `PROJECT`, select `src/agilab/apps/builtin/uav_relay_queue_project`
   (`UAV Relay Queue`), and show the scenario file plus the routing policy
   selector.
3. `0:55 -> 1:35`
   Move to `ORCHESTRATE`, launch the run, and explain that AGILAB takes a
   lightweight simulator-backed app and packages it into a controlled execution
   path.
4. `1:35 -> 2:00`
   Move to `PIPELINE`, show the generated or replayable step, and explain that
   the experiment is now explicit instead of being buried in one-off scripts.
5. `2:00 -> 2:40`
   Move to `ANALYSIS`, open `view_uav_relay_queue_analysis`, and show queue
   timeseries, drops, and routing summary.
6. `2:40 -> 3:00`
   Optionally open `view_maps_network` or end on the queue page, then close on:
   `AGILAB keeps the experiment reproducible all the way to visible evidence.`

Suggested narration:

`This is the more technical AGILAB story. In PROJECT, I choose a UAV queueing
experiment and its routing policy. In ORCHESTRATE, AGILAB runs it without
ad-hoc glue. In PIPELINE, the execution becomes replayable. In ANALYSIS, I land
on queue buildup, packet drops, and route usage. The point is not only to run a
simulation. The point is to turn it into a controlled, inspectable workflow.`

Suggested click path:

1. Home page
2. `PROJECT`
3. app selector -> `uav_relay_queue_project` (`UAV Relay Queue`)
4. short pause on scenario and routing policy
5. `ORCHESTRATE`
6. short pause on run controls
7. `PIPELINE`
8. short pause on the explicit step
9. `ANALYSIS`
10. `view_uav_relay_queue_analysis`
11. optional final pause on `view_maps_network`

## Recording and visual rules

- Record at `1440p` or `1080p`, then crop tightly.
- Keep the cursor slow and deliberate.
- Avoid typing during capture unless the command is the point.
- Use one app only. The point is clarity, not breadth.
- End on a visible result, not logs.
- Trim dead time during export instead of re-recording immediately.
- Keep the visible UI path aligned with the narration path.
- Prefer one strong sentence on screen rather than many small labels.

## Quality checklist

- each tutorial uses one app only
- `flight_project` clips show `PROJECT -> ORCHESTRATE -> ANALYSIS`, with fresh
  output files in between
- `UAV Relay Queue` clips show `PROJECT -> ORCHESTRATE -> PIPELINE -> ANALYSIS`
- the ending frame shows a result, not infrastructure noise
- the video and static assets use the same message
- the social/static assets do not contradict the live capture
- the clip stays short enough to rewatch once without fatigue

## Default tagline

`AGILAB gives one app one control path from selection to visible evidence.`
