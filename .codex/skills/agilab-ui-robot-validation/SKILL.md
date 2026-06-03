---
name: agilab-ui-robot-validation
description: Validate AGILAB Streamlit UI changes with the repo's browser and widget robots. Use when touching ABOUT, PROJECT, ORCHESTRATE, ANALYSIS, SETTINGS, sidebar flows, first-proof wizard links, notebook import, screenshots, or public demo UI evidence.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-31
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
- For Streamlit or React/`agi-web` page validation, inspect browser dev-log
  evidence too: console errors/warnings, `pageerror`, failed requests, and HTTP
  4xx/5xx responses. A page is not validated just because the visible DOM
  rendered when the browser log shows a relevant runtime or asset failure.

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

Use this for Streamlit dependency, run-configuration, theme, or blank-page
frontend issues. It launches the dev app, checks JS/CSS MIME types, then verifies
the first page hydrates in Chromium:

```bash
UV_PYTHON=3.13 uv --preview-features extra-build-dependencies run --extra ui --with playwright python tools/agilab_web_robot.py \
  --frontend-smoke-only \
  --timeout 45 \
  --target-seconds 45 \
  --json \
  --screenshot-dir /tmp/agilab-frontend-smoke-screenshots \
  > /tmp/agilab-frontend-smoke.json
```

Use this for browser-level ABOUT and notebook handoff issues:

```bash
UV_PYTHON=3.13 uv --preview-features extra-build-dependencies run --extra ui --with playwright python tools/agilab_web_robot.py \
  --json \
  --screenshot-dir /tmp/agilab-web-robot-screenshots \
  > /tmp/agilab-web-robot.json
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

Use this when an embedded ANALYSIS app surface must expose app-owned controls
without firing callbacks. The text and button probes inspect the top page and
child iframes, and `--required-action-labels` only trial-clicks buttons:

```bash
UV_PYTHON=3.13 uv --preview-features extra-build-dependencies run --with playwright python tools/agilab_widget_robot_matrix.py \
  --scenario isolated-pytorch-playground-analysis \
  --json \
  --quiet-progress \
  --no-result-cache \
  --output-dir /tmp/agilab-pytorch-analysis-robot \
  --screenshot-dir /tmp/agilab-pytorch-analysis-robot-screenshots
```

Use explicit browser-error evidence when React/`agi-web`, custom components,
iframes, or Streamlit frontend assets are part of the change. The widget robot
captures Chromium console warnings/errors, `pageerror`, failed requests, and
HTTP error responses into its JSON/progress evidence and failure bundle:

```bash
UV_PYTHON=3.13 uv --preview-features extra-build-dependencies run --with playwright python tools/agilab_widget_robot_matrix.py \
  --scenario isolated-browser-error-core-pages \
  --json \
  --quiet-progress \
  --no-result-cache \
  --output-dir /tmp/agilab-browser-error-robot \
  --screenshot-dir /tmp/agilab-browser-error-robot-screenshots
```

Use this before release or after broad navigation/sidebar work:

```bash
UV_PYTHON=3.13 uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile ui-robot-matrix
```

Use this to inspect the exact sharded matrix commands without launching the
robots:

```bash
uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile ui-robot-matrix --print-only
```

## Choosing Scenarios

- ABOUT / first-proof wizard:
  run `first_launch_robot.py`, the focused ABOUT tests, and at least the matrix
  scenario that covers entry and app pages.
  When the first visible copy or product journey wording changes, update
  `tools/first_launch_robot.py` expectations in the same change so CI validates
  the current pitch instead of stale labels.
- Streamlit dependency, `pyproject.toml`, run config, theme, or launch wrapper:
  run `tools/agilab_web_robot.py --frontend-smoke-only` first. This is the
  fastest real-browser guard for blank pages caused by static frontend assets
  being served with the wrong MIME type.
- React/`agi-web`, custom components, canvas/WebGL, or embedded iframe changes:
  run a Chromium/Chrome browser robot and inspect the captured browser issues
  even when the page looks correct. Treat relevant console errors, page errors,
  failed asset/API requests, and HTTP 4xx/5xx responses as validation failures
  unless there is an explicit ignore rule.
- PROJECT sidebar, create/import/rename/delete:
  run focused PROJECT tests plus matrix scenarios for project page,
  project-import-sidebar, project-rename-sidebar, and notebook import.
- Notebook import/upload:
  run notebook-import helper tests plus `agilab_web_robot.py` when the file
  chooser, upload handoff, or built-in notebook route changed.
- ORCHESTRATE action buttons:
  use `agilab_widget_robot.py --action-button-policy click-selected` with the
  exact visible button labels the end user is expected to press.
  If the button is intentionally not clicked by generic robots because it writes
  local state, launches external work, or is advisory-only, add or update its
  disposition in `tools/ui_robot_action_contract.py` and cover the behavior with
  focused helper/AppTest regressions. Examples include LAN discovery/cache
  controls and advisory planning actions such as `Build cluster plan`.
- When a UI action keeps the same visible button label but changes semantics
  behind a selector or multiselect, update the robot action disposition for the
  exact visible label and add focused regressions for the selector state. Do not
  rename robot dispositions to internal semantics such as `Update selected`
  unless that is the actual button text users see.
- SETTINGS or Streamlit system-menu changes:
  run settings page tests plus the settings matrix scenario.
- Public demo or HF Space UI:
  run `tools/hf_space_smoke.py --json` first, then run the web robot against the
  hosted URL if the claim is about browser-visible behavior.

## Evidence Rules

- Save JSON summaries and progress logs under `/tmp` for local debugging, or
  under `test-results/` only when the artifact is intentionally part of CI or
  release evidence.
- For any browser validation, inspect the dev-log evidence before declaring the
  page valid. In widget/matrix runs this means checking the JSON/progress output
  and, on failure, the `browser-issues.json` file in the failure bundle. For
  manual Chrome validation, open DevTools Console and Network and report whether
  relevant console errors/warnings, `pageerror` equivalents, failed requests, or
  HTTP 4xx/5xx responses were present.
- Use `--screenshot-dir` for browser/UI failures. Screenshots should include the
  manifest generated by the robot so evidence can be traced back to the command.
- For full matrix runs, prefer the sharded `ui-robot-matrix` profile. CI keeps
  successful scenarios lightweight and reruns only failed scenarios with
  `--retry-failed-with-artifacts`, producing trace, HAR, and video evidence under
  each shard's `failure-artifacts/` directory.
- When diagnosing a matrix failure, inspect the aggregate artifact first. The
  `ui-robot-matrix-aggregate-*` report links the shard, failure bundle, replay
  command, artifact-retry status, and any trace/HAR/video directories.
- Use `tools/ui_robot_failure_replay.py <bundle>` to print the exact command
  recorded in a failure bundle, and add `--execute` only when you intentionally
  want to rerun that recorded command.
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
- Browser dev-log evidence was inspected for Streamlit/React browser runs:
  console, page errors, failed requests, and HTTP errors are either clean or
  explicitly explained.
- No generated screenshots or `test-results/` artifacts are committed unless the
  task intentionally updates evidence fixtures.
- If public docs or README copy describes the UI behavior, the wording matches
  the validated path and does not overclaim coverage.
