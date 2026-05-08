---
name: agilab-product-reels
description: Build and refine short AGILAB product reels and technical demo videos with one-app storytelling, semantic guardrails, frame review, and YouTube packaging.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-07
---

# Product Reels Skill (AGILAB)

Use this skill when the user wants a short AGILAB teaser, technical benchmark reel,
live-demo plan, or YouTube-ready demo package.

## Pick The Right Demo Type

- `Product teaser`: product-first, fast, broad, one core claim.
- `Technical benchmark reel`: same scenario, same load/seed, one meaningful variable changes.
- `Live walkthrough`: real cursor capture for the final “hero” demo; use only after the story is already clear.

Do not mix multiple apps in one short demo.

## Default App Positioning

- `flight_project`: safest product teaser.
- `uav_queue_project`: best short technical benchmark reel.

If the user wants a short public video, prefer one of those two first.

## Core Story Rule

Every short AGILAB demo must have one central claim, then map that claim through:

1. `PROJECT`
2. `ORCHESTRATE`
3. `WORKFLOW`
4. `ANALYSIS`

Do not make a feature tour. A short reel needs one story only.

## Semantic Guardrails

- Do not show an empty replayable stage or empty generated snippet.
- Do not end on decorative `ANALYSIS`; show real evidence.
- Do not show a “map” without credible geographic meaning.
- Do not imply unsupported product behavior.
- When saying `scalability`, state whether it means worker distribution or data-volume / big-data scale.
- If the app supports a real benchmark comparison, show that comparison instead of generic workflow text.

If the content feels weak, improve the story before polishing the visuals.

## Reel Workflow

1. Choose one app.
2. Write one sentence for the core claim.
3. Decide which content must be visible in each page:
   - `PROJECT`: scenario or app context
   - `ORCHESTRATE`: runnable packaging / orchestration intent
   - `WORKFLOW`: replayable snippet, saved stage content, or workflow graph
   - `ANALYSIS`: visible outcome or comparison evidence
4. Generate or refresh the reel.
5. Extract fresh frames and inspect them before treating the reel as ready.
6. Only after the content is clear, prepare the YouTube title/description/comment package.

## Current Generator

- Generator: `tools/build_product_demo_reel.py`
- Outputs: `artifacts/demo_media/<variant>/`

Typical runs:

```bash
uv run python tools/build_product_demo_reel.py --variant flight
uv run python tools/build_product_demo_reel.py --variant uav_queue
```

## Known Good Narrative Patterns

### `flight_project`

- Tell the product story.
- Keep the sequence simple and clean.
- For scale wording, prefer data-volume / big-data tractability over worker-count claims unless the user explicitly wants cluster scale.

### `uav_queue_project`

- Tell a benchmark story, not a workflow story.
- Keep the same scenario, load, and seed fixed.
- Change one meaningful variable only, such as routing policy.
- Show concrete evidence in `ANALYSIS`: drops, delay, bottleneck, route usage, queue buildup.

## Review Loop

After every meaningful change, extract and inspect frames for at least:

- `PROJECT`
- `ORCHESTRATE`
- `WORKFLOW`
- `ANALYSIS`

Useful checks:

```bash
uv run python -m py_compile tools/build_product_demo_reel.py
/opt/homebrew/bin/ffmpeg -y -ss 00:00:03 -i artifacts/demo_media/flight/agilab_flight.mp4 -frames:v 1 /tmp/frame.png
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate,bit_rate -of default=noprint_wrappers=1 artifacts/demo_media/flight/agilab_flight.mp4
```

Do not trust the code alone; verify the rendered frame.

## YouTube Packaging

Once the reel is visually and semantically stable, prepare:

- title
- description
- chapters
- pinned comment
- thumbnail text

Keep the upload copy aligned with the reel type:

- teaser: product-first
- benchmark reel: scenario-first and evidence-first
- live walkthrough: action-first and page-by-page

## Escalation Rule

If repeated iterations still look synthetic or “not pro”, stop tuning the composed reel
and switch to a real live capture plan. Use the reel as intro/outro material only.
