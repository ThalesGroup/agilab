# AGILAB Launch Package

This file is the execution-ready launch package for the current public positioning wave.

Use it with:

- [GITHUB_REPO_POSITIONING.md](/Users/agi/PycharmProjects/agilab/GITHUB_REPO_POSITIONING.md)
- [STAR_GROWTH_PLAN.md](/Users/agi/PycharmProjects/agilab/STAR_GROWTH_PLAN.md)
- [LAUNCH_EXECUTION_CHECKLIST.md](/Users/agi/PycharmProjects/agilab/LAUNCH_EXECUTION_CHECKLIST.md)
- [WEEKLY_GROWTH_TRACKER.md](/Users/agi/PycharmProjects/agilab/WEEKLY_GROWTH_TRACKER.md)

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
- local upload/source reel: [`artifacts/demo_media/flight/agilab_flight.mp4`](/Users/agi/PycharmProjects/agilab/artifacts/demo_media/flight/agilab_flight.mp4)
- primary still image fallback: [`docs/source/diagrams/agilab_social_card.svg`](/Users/agi/PycharmProjects/agilab/docs/source/diagrams/agilab_social_card.svg)
- supporting workflow explainer: [`docs/source/diagrams/agilab_readme_tour.svg`](/Users/agi/PycharmProjects/agilab/docs/source/diagrams/agilab_readme_tour.svg)

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

- first choice: [`artifacts/demo_media/flight/agilab_flight.mp4`](/Users/agi/PycharmProjects/agilab/artifacts/demo_media/flight/agilab_flight.mp4)
- public fallback link: `https://youtu.be/kOMDyvbnC9w`
- fallback: [`docs/source/diagrams/agilab_social_card.svg`](/Users/agi/PycharmProjects/agilab/docs/source/diagrams/agilab_social_card.svg)

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
