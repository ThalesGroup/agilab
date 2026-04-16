# AGILAB Weekly Growth Tracker

Use this file to record the weekly signals defined in [STAR_GROWTH_PLAN.md](/Users/agi/PycharmProjects/agilab/STAR_GROWTH_PLAN.md).

The goal is not bookkeeping. The goal is to learn which launch actions are improving conversion.

## Metrics to record

- GitHub stars
- README views to stars conversion
- docs visits
- PyPI installs
- new external discussions/issues
- time-to-first-success for a newcomer following the quick start

## Weekly table

| Week | Stars start | Stars end | Net stars | README views | Docs visits | PyPI installs | External questions | Main traffic source | Main leak in funnel | Decision for next week |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-04-13 | 4 | 5 | 1 | n/a | n/a | n/a | 0 | GitHub discussion #8 | launch wave incomplete, traffic not instrumented, and docs/demo conversion still leaks | publish LinkedIn post, restore the canonical flight video asset, and tighten docs landing wording |
| YYYY-MM-DD |  |  |  |  |  |  |  |  |  |  |
| YYYY-MM-DD |  |  |  |  |  |  |  |  |  |  |

## Current launch artifacts

- GitHub discussion: https://github.com/ThalesGroup/agilab/discussions/8

## 2026-04-16 status note

- Public repo stars: `5`
- Launch artifact executed: GitHub discussion `#8`
- External questions/comments observed on the discussion: `0`
- README and GitHub repo description are aligned with the locked positioning
- Docs landing copy still drifts from the locked positioning
- The CLI-safe quick-start path is present in both README and docs
- The primary canonical demo video `artifacts/demo_media/flight/agilab_flight.mp4` is missing from the working tree, so the launch package currently depends on still-image fallback assets

## Weekly review questions

Answer these in plain language after filling the table.

1. What new external proof exists this week?
2. Which launch asset actually generated qualified traffic?
3. Where did first-time users still get confused?
4. Did traffic improve conversion, or only impressions?
5. What should be tightened before the next public push?

## Funnel diagnosis template

Use this when growth is weak.

- `Impression`: did people see the post or asset?
- `Landing`: did they actually open the repo or docs?
- `Understanding`: could they explain what AGILAB is in one sentence?
- `Trial`: could they identify the first thing to run?
- `Proof`: did they reach one convincing success point?
- `Conversion`: did they star, watch, discuss, or share?

If the leak is before `Trial`, improve landing-page clarity.
If the leak is after `Trial`, improve the demo and first-run proof.
If the leak is after `Proof`, improve the call to action and public packaging.
