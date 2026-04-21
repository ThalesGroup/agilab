# GitHub Repo Positioning

Use this file when updating the GitHub repository `About` section, topics, and short-form promotional copy.

## Locked positioning

### Primary About text

`Open-source platform for reproducible AI/ML workflows, from local experimentation to distributed workers and long-lived services.`

### Backup About text

`Reproducible AI/ML workflows from local UI or CLI to distributed workers, service mode, and analysis.`

### Primary one-line pitch

`AGILAB is an open-source platform for reproducible AI/ML workflows that takes you from local experimentation to distributed execution and long-lived services.`

This should stay semantically aligned with the README opening.

### Primary audience

Applied ML engineers and technical teams who need one workflow to stay
reproducible from local experimentation to distributed execution and service
mode.

### Above-the-fold rule

Before the reader scrolls, the repo should answer three things only:

1. what AGILAB is
2. who it is for
3. what the first proof outcome looks like

Do not spend the first screen on secondary badges, creator biography, or
supporting hooks such as agents/free-threading before those three points are clear.

### One dominant first-proof path

The public entry path should stay locked to:

`source checkout -> web UI -> flight_project -> local run -> analysis`

Do not present packaged install, notebook-first, cluster setup, or private-app
flows as equal first-step alternatives on the landing screen.

### Ease-of-use rule

- One recommended path first.
- Alternatives only after the reader sees the first proof outcome.
- Do not duplicate the same onboarding story in multiple equal sections of the README.
- If a section does not help the first local `flight_project` proof, move it lower.

## Locked topics

- `mlops`
- `workflow-orchestration`
- `machine-learning`
- `python`
- `streamlit`
- `distributed-computing`
- `agents`
- `codex`
- `reproducibility`
- `free-threading`

## Canonical launch asset

Use one primary launch asset across the repo, release notes, and social posts:

- public video: `https://youtu.be/kOMDyvbnC9w`
- local upload/source reel: [`artifacts/demo_media/flight/agilab_flight.mp4`](../../artifacts/demo_media/flight/agilab_flight.mp4)
- still fallback: [`docs/source/diagrams/agilab_social_card.svg`](../../docs/source/diagrams/agilab_social_card.svg)
- supporting explainer: [`docs/source/diagrams/agilab_readme_tour.svg`](../../docs/source/diagrams/agilab_readme_tour.svg)

Do not rotate between unrelated demos for the same launch wave. The first wave should
anchor on `flight_project` so the landing page, demo, and post copy all point to the same path.

## Short-form positioning

### What AGILAB is

AGILAB is a platform for reproducible AI/ML workflows. It gives the same application a clear control path from local UI or CLI entrypoints to packaged workers, distributed execution, service mode, and analysis.

### Why it is different

- It keeps **one control path** from local run to distributed workers and analysis.
- It makes **reproducibility explicit** through managed environments, per-app settings, and execution history.
- It supports **service mode** instead of stopping at one-off runs.
- It is **agent-friendly** and **free-threaded-aware**, but those should be supporting proof points, not the opening hook.

## Priority order for public copy

Lead with these points in this order:

1. reproducible AI/ML workflows
2. local to distributed execution
3. long-lived services / service mode
4. environment isolation and orchestration
5. agent-friendly workflow
6. free-threaded awareness

If a short-form asset only has room for one sentence, stop after point 3.

### What not to say

- Do not claim free-threaded Python is always enabled by default.
- Do not describe AGILAB as a full enterprise platform if the user has not yet seen the workflow proof.
- Do not market it as “everything for AI” or “all-in-one MLOps”.
- Do not lead with badges, internal package names, or Codex-specific details before explaining the workflow value.
