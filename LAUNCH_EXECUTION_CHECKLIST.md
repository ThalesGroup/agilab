# AGILAB Launch Execution Checklist

Use this file to execute the current launch wave defined in:

- [STAR_GROWTH_PLAN.md](/Users/agi/PycharmProjects/agilab/STAR_GROWTH_PLAN.md)
- [GITHUB_REPO_POSITIONING.md](/Users/agi/PycharmProjects/agilab/GITHUB_REPO_POSITIONING.md)
- [LAUNCH_POST_DRAFTS.md](/Users/agi/PycharmProjects/agilab/LAUNCH_POST_DRAFTS.md)

This is not a brainstorming document. It is the run list for the current public push.

## Locked launch theme

`Reproducible AI/ML workflows from local experimentation to distributed workers and long-lived services.`

## Locked canonical demo

- published public video: `https://youtu.be/kOMDyvbnC9w`
- local upload/source reel: [`artifacts/demo_media/flight/agilab_flight.mp4`](/Users/agi/PycharmProjects/agilab/artifacts/demo_media/flight/agilab_flight.mp4)
- ML-facing alternative reel: [`artifacts/demo_media/meteo_forecast/agilab_meteo_forecast.mp4`](/Users/agi/PycharmProjects/agilab/artifacts/demo_media/meteo_forecast/agilab_meteo_forecast.mp4)
- still fallback: [`docs/source/diagrams/agilab_social_card.svg`](/Users/agi/PycharmProjects/agilab/docs/source/diagrams/agilab_social_card.svg)
- workflow explainer: [`docs/source/diagrams/agilab_readme_tour.svg`](/Users/agi/PycharmProjects/agilab/docs/source/diagrams/agilab_readme_tour.svg)
- reference app: `flight_project`

If the local video asset is missing, regenerate it before launch:

```bash
uv --preview-features extra-build-dependencies run python tools/build_product_demo_reel.py --variant flight
uv --preview-features extra-build-dependencies run python tools/build_product_demo_reel.py --variant meteo_forecast --mp4 artifacts/demo_media/meteo_forecast/agilab_meteo_forecast.mp4 --gif artifacts/demo_media/meteo_forecast/agilab_meteo_forecast.gif --poster artifacts/demo_media/meteo_forecast/agilab_meteo_forecast_poster.png
```

## Pre-flight checks

- [x] README opening still matches the locked positioning
- [x] GitHub repo description still matches the locked About text
- [x] canonical demo asset still opens and is usable
- [x] docs landing page still points first-time users to the same workflow
- [x] quick-start path still works without IDE-specific context
- [x] no new repo wording drift has appeared between README, docs, and launch copy

## Launch sequence

### Step 1: repo and docs alignment

- [x] verify [README.md](/Users/agi/PycharmProjects/agilab/README.md)
- [x] verify [GITHUB_REPO_POSITIONING.md](/Users/agi/PycharmProjects/agilab/GITHUB_REPO_POSITIONING.md)
- [x] verify [LAUNCH_POST_DRAFTS.md](/Users/agi/PycharmProjects/agilab/LAUNCH_POST_DRAFTS.md)
- [x] verify docs landing page links are still valid

### Step 2: GitHub launch

- [x] publish the GitHub discussion or release note using [LAUNCH_POST_DRAFTS.md](/Users/agi/PycharmProjects/agilab/LAUNCH_POST_DRAFTS.md)
- [x] attach or link the canonical demo asset
- [x] point readers to the README quick start and docs home

Published artifact:

- GitHub discussion: https://github.com/ThalesGroup/agilab/discussions/8

### Step 3: LinkedIn launch

- [ ] publish the LinkedIn post from [LAUNCH_POST_DRAFTS.md](/Users/agi/PycharmProjects/agilab/LAUNCH_POST_DRAFTS.md)
- [ ] use the flight demo video for broad product positioning
- [ ] use the meteo forecast reel when the post must visibly show an ML workflow
- [ ] if not, use the social card
- [ ] keep the wording aligned with the locked launch theme

### Step 4: community channels

- [ ] publish Reddit post only if the landing page still feels sharp
- [ ] publish Hacker News post only if the demo asset and landing page are both strong enough
- [ ] do not switch to another app example for the same launch wave

## 48-hour follow-up

- [x] record first star delta after the launch
- [ ] record README / docs traffic if available
- [x] record whether external questions appeared
- [x] record whether the first-time visitor path caused confusion
- [x] update [WEEKLY_GROWTH_TRACKER.md](/Users/agi/PycharmProjects/agilab/WEEKLY_GROWTH_TRACKER.md)

Observed on 2026-04-16:

- Star delta after discussion launch: `4 -> 5`
- External questions/comments on discussion `#8`: `0`
- First-time visitor friction still visible:
  - README/docs quick-start path is CLI-safe, but traffic instrumentation is still missing

## Abort conditions

Pause the launch if any of these become true:

- the README and GitHub description drift apart again
- the canonical demo path is broken or unclear
- the launch copy starts fragmenting into multiple messages
- the landing page still needs explanation before a visitor can try anything

If an abort condition is hit, fix conversion first. Do not push more traffic into a weak landing page.
