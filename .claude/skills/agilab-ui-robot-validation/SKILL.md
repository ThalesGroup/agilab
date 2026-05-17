---
name: agilab-ui-robot-validation
description: Validate AGILAB Streamlit UI changes with the repo's browser and widget robots. Use when touching ABOUT, PROJECT, ORCHESTRATE, ANALYSIS, SETTINGS, sidebar flows, first-proof wizard links, notebook import, screenshots, or public demo UI evidence.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-17
---

# AGILAB UI Robot Validation

Use this skill when a change affects user-visible Streamlit behavior, page
navigation, sidebar actions, wizard links, notebook import/upload flows, UI
screenshots, or public demo evidence.

The goal is to catch real browser/session-state failures that helper tests and
static AppTest checks can miss: broken `st.switch_page` paths, recursive
deep-links, hidden upload controls, stale sidebar state, and Streamlit
exceptions that only appear after clicking through the UI.

## Tool Choice

- Use focused unit/helper tests first when the bug is pure Python state logic.
- Use Streamlit `AppTest` when the failure is widget wiring, page hydration, or
  session-state initialization and no real browser behavior is needed.
- Use `tools/agilab_web_robot.py` for browser-level entrypoint checks, hosted
  demo checks, screenshots, and notebook upload handoff behavior.
- Use `tools/agilab_widget_robot.py` for page-by-page Streamlit widget flows,
  selected action buttons, artifact assertions, and stateful project journeys.
- Use `tools/agilab_widget_robot_matrix.py` when the change touches navigation,
  sidebar project actions, notebook import, settings, first-launch, or broad UI
  behavior that must stay consistent across pages.

Do not replace a deterministic helper regression with a slow robot. Robots are
for user journeys, browser-only behavior, and release/public-demo evidence.

## Preflight

1. Confirm the repo is the source checkout you intend to test.

```bash
git status --short --branch --untracked-files=no
```

2. Check the exact local workflow profile before inventing commands.

```bash
uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile ui-robot-matrix --print-only
```

3. If a change affects release evidence, also inspect the release shortcut.

```bash
./dev --print-only release
```

## Fast Local Commands

Use this for a first-launch smoke when the entry shell, ABOUT page, or default
navigation changed:

```bash
UV_PYTHON=3.13 uv --preview-features extra-build-dependencies run python tools/first_launch_robot.py --json --output /tmp/agilab-first-launch-robot.json
```

Use this for browser-level ABOUT and notebook handoff issues:

```bash
UV_PYTHON=3.13 uv --preview-features extra-build-dependencies run --with playwright python tools/agilab_web_robot.py \
  --json \
  --json-output /tmp/agilab-web-robot.json \
  --screenshot-dir /tmp/agilab-web-robot-screenshots
```

Use this for a selected page/action journey. Keep labels exact and fail if the
requested action is missing:

```bash
AGILAB_WIDGET_ROBOT_RUNTIME_ISOLATION=current-home \
UV_PYTHON=3.13 uv --preview-features extra-build-dependencies run --with playwright python tools/agilab_widget_robot.py \
  --apps flight_project \
  --pages ORCHESTRATE \
  --apps-pages none \
  --json \
  --json-output /tmp/agilab-widget-robot.json \
  --progress-log /tmp/agilab-widget-robot.ndjson \
  --interaction-mode full \
  --action-button-policy click-selected \
  --click-action-labels "CHECK distribute" \
  --preselect-labels "Run now" \
  --missing-selected-action-policy fail \
  --runtime-isolation current-home
```

Use this before release or after broad navigation/sidebar work:

```bash
UV_PYTHON=3.13 uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile ui-robot-matrix
```

## Choosing Scenarios

- ABOUT / first-proof wizard:
  run `first_launch_robot.py`, the focused ABOUT tests, and at least the matrix
  scenario that covers entry and app pages.
- PROJECT sidebar, create/import/rename/delete:
  run focused PROJECT tests plus matrix scenarios for project page,
  project-import-sidebar, project-rename-sidebar, and notebook import.
- Notebook import/upload:
  run notebook-import helper tests plus `agilab_web_robot.py` when the file
  chooser, upload handoff, or built-in notebook route changed.
- ORCHESTRATE action buttons:
  use `agilab_widget_robot.py --action-button-policy click-selected` with the
  exact visible button labels the end user is expected to press.
- SETTINGS or Streamlit system-menu changes:
  run settings page tests plus the settings matrix scenario.
- Public demo or HF Space UI:
  run `tools/hf_space_smoke.py --json` first, then run the web robot against the
  hosted URL if the claim is about browser-visible behavior.

## Evidence Rules

- Save JSON summaries and progress logs under `/tmp` for local debugging, or
  under `test-results/` only when the artifact is intentionally part of CI or
  release evidence.
- Use `--screenshot-dir` for browser/UI failures. Screenshots should include the
  manifest generated by the robot so evidence can be traced back to the command.
- In final notes, report the scenario name, command class, JSON output path, and
  whether screenshots were generated. Do not claim a full UI sweep when only one
  page or button was tested.
- If a robot fails from environment setup, missing Playwright, port conflict, or
  unrelated app startup, say that explicitly and keep the focused helper tests
  separate from the blocked browser evidence.

## Common Failure Patterns

- `Could not find page`: replace stale numeric filenames with central page route
  constants and add a focused navigation test.
- `maximum recursion depth exceeded`: deep-link intent was not consumed/cleared
  before rerun; test both first click and reload behavior.
- Upload link opens the page but no chooser appears: browser-level robot is
  required because Streamlit file chooser behavior cannot be proven by static
  text checks alone.
- Spinner keeps running after an action: assert action-result status and fatal
  log classification, not just that a success message was rendered.
- Stale project/sidebar state: test both cold sessions and warm sessions after
  switching or deleting projects.

## Close-Out Checklist

- The narrow helper/AppTest regression for the root cause is green.
- The selected robot scenario that matches the user journey is green, or the
  blocker is explicitly reported.
- No generated screenshots or `test-results/` artifacts are committed unless the
  task intentionally updates evidence fixtures.
- If public docs or README copy describes the UI behavior, the wording matches
  the validated path and does not overclaim coverage.
