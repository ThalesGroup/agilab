---
name: agilab-huggingface-spaces
description: Maintain and deploy the official AGILAB Hugging Face Docker Space using the sibling thales_agilab/huggingface bundle and public agilab checkout.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-15
---

# Hugging Face Spaces Skill (AGILAB)

Use this skill when preparing, validating, or deploying the official AGILAB Hugging Face Space.

The current source of truth is the sibling apps/docs checkout, normally
`../thales_agilab` relative to the public `agilab` checkout:
- `<apps-repo>/huggingface/README.md`
- `<apps-repo>/huggingface/README.advanced.md`
- `<apps-repo>/huggingface/hf_space_deploy.sh`
- `<apps-repo>/huggingface/Dockerfile`
- `<apps-repo>/huggingface/seed_hf_app_settings.py`

Do not default to a generic “lightweight one-page demo” plan when the repo already defines a concrete Space contract.

## Current Space Contract

The official Space is currently:
- a **Docker Space**
- named like `<user>/agilab` for the default `first-proof` profile
- optionally named like `<user>/agilab-advanced` for the heavier `advanced`
  profile
- launched on port `7860`
- backed by the AGILAB Streamlit interface
- built from the public `agilab` repo plus the sibling apps/docs `huggingface` packaging bundle

Treat `first-proof` as the default target unless the user explicitly asks for
the advanced companion Space.

## What the Space Actually Publishes

The current deploy path stages:
- profile README from `thales_agilab/huggingface`
  - `README.md` for `first-proof`
  - `README.advanced.md` for `advanced`
- `Dockerfile` from `thales_agilab/huggingface`
- `.dockerignore` from `thales_agilab/huggingface`
- `seed_hf_app_settings.py` from `thales_agilab/huggingface`
- `docker/install.sh` from the public `agilab` repo
- `src/` from the public `agilab` repo
- `pyproject.toml` from the public `agilab` repo
- `uv_config.toml` from the public `agilab` repo

This is not a raw repo push and not a generic Space scaffold. The deploy script assembles a bounded staging directory and uploads that to Hugging Face.

Profile app/page sets:
- `first-proof`
  - apps: `flight_telemetry_project`, `weather_forecast_project`
  - pages: `view_maps`, `view_forecast_analysis`, `view_release_decision`
- `advanced`
  - apps: `execution_pandas_project`, `execution_polars_project`,
    `flight_telemetry_project`, `global_dag_project`,
    `mission_decision_project`, `mycode_project`, `tescia_diagnostic_project`,
    `uav_queue_project`, `uav_relay_queue_project`,
    `weather_forecast_project`
  - pages: `view_data_io_decision`, `view_forecast_analysis`, `view_maps`,
    `view_maps_network`, `view_queue_resilience`, `view_relay_resilience`,
    `view_release_decision`

The advanced profile installs every current built-in demo app, but it still
avoids unrelated historical heavyweight pages that are not part of the current
Advanced Proof Pack.

## Profile Drift Guardrail

Before every deploy, compare the profile app/page lists in
`<apps-repo>/huggingface/hf_space_deploy.sh`, `README.md`,
`README.advanced.md`, and `Dockerfile` with the actual public checkout:

```bash
find <agilab-checkout>/src/agilab/apps/builtin -maxdepth 1 -mindepth 1 -type d -exec basename {} \; | sort
find <agilab-checkout>/src/agilab/apps-pages -maxdepth 1 -mindepth 1 -type d -exec basename {} \; | sort
rg -n "flight_project|meteo_forecast_project|data_io_2026_project|view_uav_queue_analysis|view_uav_relay_queue_analysis" \
  <apps-repo>/huggingface <agilab-checkout>/.claude/skills/agilab-huggingface-spaces <agilab-checkout>/.codex/skills/agilab-huggingface-spaces
```

If stale names appear, fix the sibling `huggingface` bundle first, then update
this skill through `repo-skill-maintenance`. Do not deploy by adding aliases to
paper over stale profile names; the Space profile should reference the current
public app IDs directly.

## Runtime and Product Constraints

Keep the skill aligned with the README contract:
- the Space README presents AGILAB as an anti-lock-in reproducibility workbench,
  not as a generic AI platform
- the default and advanced Space cards both mention runnable notebook export as
  the user exit path: review, handoff, and reuse outside AGILAB
- the Space exposes the AGILAB Streamlit interface
- Space mode is single-container only
- local Dask multi-worker execution may be demonstrated inside that container
  using `127.0.0.1:8786`, `{"127.0.0.1": 2}`, and a writable in-container
  `AGI_CLUSTER_SHARE`
- offline/local LLM paths such as Ollama are not available there
- storage is ephemeral unless a Hugging Face dataset mount is used

Do not promise:
- remote multi-node ORCHESTRATE behavior
- remote-cluster parity
- remote SSH workers from the hosted Space
- local `~/agi-space` or `~/wenv` semantics
- developer-machine assumptions

## Secrets and Environment Variables

The current README advertises these Hugging Face secrets:
- `OPENAI_API_KEY` — optional
- `CLUSTER_CREDENTIALS` — optional

When updating docs or deploy instructions, keep the wording aligned with the README and do not invent new required secrets unless the Space contract actually changed.

## Deployment Workflow

Use the documented flow:

1. Install the Hugging Face CLI.
2. Authenticate with either:
   - `hf auth login`
   - or `HF_TOKEN` in the environment
3. Run the deploy script from the sibling apps/docs repo:

```bash
<apps-repo>/huggingface/hf_space_deploy.sh \
  --profile first-proof \
  --agilab-path </path/to/agilab> \
  --space <user>/agilab \
  --create
```

For an existing Space:

```bash
<apps-repo>/huggingface/hf_space_deploy.sh \
  --profile first-proof \
  --agilab-path </path/to/agilab> \
  --space <user>/agilab
```

For the heavier companion Space:

```bash
<apps-repo>/huggingface/hf_space_deploy.sh \
  --profile advanced \
  --agilab-path </path/to/agilab> \
  --space <user>/agilab-advanced \
  --create
```

Relevant options from the script:
- `--profile first-proof|advanced`
- `--agilab-path`
- `--space`
- `--private`
- `--create`

Do not replace this with hand-written deployment steps unless the user explicitly wants a new deploy path.

## Validation Before Deploy

Before touching the Space deployment, verify:

1. The public `agilab` checkout exists and is the intended source tree.
2. The sibling apps/docs `huggingface` bundle exists and matches the intended Space contract.
3. `hf auth whoami` succeeds, or `HF_TOKEN` is present.
4. The current README, Dockerfile, and deploy script still agree on:
   - SDK type
   - exposed port
   - secret names
   - anti-lock-in / runnable-notebook-export positioning
   - profile app/page lists
   - target repo content
   - current public app IDs, especially `flight_telemetry_project` and
     `weather_forecast_project`
5. `src/agilab/apps` in the deploy source contains only public entries such as
   `builtin`, `templates`, `install.py`, and package metadata. If the working
   checkout has ignored private app symlinks, deploy from a temporary clean
   worktree at `origin/main` rather than from the dirty checkout.
   Also verify LFS-backed built-in assets are present in that clean worktree
   before staging the Space.
6. Any public-facing AGILAB docs that link to the Space are updated only after the deployment contract is stable.

When feasible, inspect the deploy script rather than paraphrasing it from memory.

Clean worktree pattern when private app symlinks are present:

```bash
tmpdir=$(mktemp -d /tmp/agilab-hf-public.XXXXXX)
apps_repo="../thales_agilab"
space_owner="<space-owner>"
git worktree add --detach "$tmpdir" origin/main
git -C "$tmpdir" lfs pull
find "$tmpdir/src/agilab/apps" -maxdepth 1 -mindepth 1 -exec basename {} \; | sort
"$apps_repo/huggingface/hf_space_deploy.sh" \
  --profile first-proof \
  --agilab-path "$tmpdir" \
  --space "$space_owner/agilab"
```

Do not force-install Git LFS hooks in the temporary worktree. If
`git lfs install --local` reports an existing repo pre-push hook, keep the hook
untouched and run `git -C "$tmpdir" lfs pull` directly; deployment only needs
the LFS-backed assets materialized, not a rewritten hook.

Use `--profile advanced --space "$space_owner/agilab-advanced"` for the heavier
Advanced Proof Pack companion Space.

After upload, verify the Space cutover separately from the file upload. Hugging
Face may report `No files have been modified since last commit` and return the
previous Space commit when the staged runtime payload is already current; treat
that as a valid no-op redeploy only if the deploy script verifier, public
visibility check, runtime SHA check, and public smoke all pass.

```bash
space_owner="<space-owner>"
hf spaces info "$space_owner/agilab" --format json
curl -I -L --max-time 20 "https://${space_owner}-agilab.hf.space/"
```

If the fix is about a deployed file, download that exact file from the Space and
inspect it. Do not assume the runtime is serving the new code until
`runtime.stage` is `RUNNING` and the runtime SHA matches the uploaded Space SHA.
Only remove the temporary worktree after this cutover check passes:

```bash
git worktree remove "$tmpdir"
```

Runtime cutover check:

```bash
python3 - <<'PY'
import json
import os
import subprocess
import time

space = os.environ.get("AGILAB_HF_SPACE", "<space-owner>/agilab")
for attempt in range(1, 31):
    info = json.loads(subprocess.check_output(
        ["hf", "spaces", "info", space, "--format", "json"],
        text=True,
    ))
    runtime = info.get("runtime") or {}
    raw = runtime.get("raw") or {}
    stage = runtime.get("stage") or raw.get("stage")
    repo_sha = info.get("sha")
    runtime_sha = raw.get("sha")
    private = info.get("private")
    print(f"attempt={attempt} stage={stage} private={private} repo_sha={repo_sha} runtime_sha={runtime_sha}")
    if stage in {"RUNNING", "READY"} and private is False and runtime_sha == repo_sha:
        raise SystemExit(0)
    time.sleep(20)
raise SystemExit(1)
PY
```

After cutover, download the deployed files at the Space commit and verify that
they match the intended release and profile:

```bash
space="<space-owner>/agilab"
space_sha="<space-sha>"
tmpdir=$(mktemp -d /tmp/agilab-hf-check.XXXXXX)
hf download "$space" pyproject.toml README.md Dockerfile \
  --repo-type space \
  --revision "$space_sha" \
  --local-dir "$tmpdir"
rg -n '^version = |^name = ' "$tmpdir/pyproject.toml"
rg -n 'Anti-lock-in|anti-lock-in|runnable notebooks|Notebook export exit path|flight_telemetry_project|weather_forecast_project|flight_project|meteo_forecast_project|AGILAB_HF_BUILTIN_APPS' \
  "$tmpdir/README.md" "$tmpdir/Dockerfile"
```

Treat an old `pyproject.toml` version or old app IDs as a failed alignment, even
if the live HTTP smoke passes. Treat missing anti-lock-in / notebook-export copy
as a Space-card alignment failure, even when the runtime itself is healthy.

If the Space is stuck in `RUNNING_BUILDING` or `RUNNING_APP_STARTING`, inspect
the relevant logs before making another upload:

```bash
hf spaces logs <space-owner>/agilab --build --tail 120
hf spaces logs <space-owner>/agilab --tail 160
```

For worker-install failures, look for local-source staging evidence in the build
logs. A healthy source-checkout install includes lines like `Staged uv source
'agi-env' path: ... -> _uv_sources/agi-env` for workers that depend on AGILAB
core packages. If logs mention unresolved local paths such as
`../../../core/agi-env`, fix the source worker `pyproject.toml` path relative to
that worker manifest before redeploying.

After runtime cutover, run the public smoke:

```bash
uv --preview-features extra-build-dependencies run python tools/hf_space_smoke.py --json
```

The Space source-tree verifier is an intentional deployment contract, not a
generic linter. If it fails on an expected public core page such as
`0_SETTINGS.py`, update `tools/hf_space_smoke.py` and
`test/test_hf_space_smoke.py` first, run the targeted test, commit that
guardrail fix, then rerun the deploy script:

```bash
uv --preview-features extra-build-dependencies run pytest -q test/test_hf_space_smoke.py
uv --preview-features extra-build-dependencies run python tools/hf_space_smoke.py --space <space-owner>/agilab --tree-only --json
```

If the deployed Space README or deploy contract changed, also run the sibling
apps/docs guardrail before committing the bundle:

```bash
cd <apps-repo>
uv run pytest -q apps/test/test_hf_space_deploy_contract.py
bash -n huggingface/hf_space_deploy.sh
```

If this deployment is part of a release, update release proof with the live
Space commit after the smoke passes, then sync and push both docs repos:

```bash
uv --preview-features extra-build-dependencies run python tools/release_proof_report.py \
  --docs-source ../thales_agilab/docs/source \
  --refresh-from-local \
  --hf-space-commit <space-sha> \
  --render \
  --check \
  --compact
uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py \
  --source ../thales_agilab/docs/source \
  --target docs/source \
  --apply \
  --delete
```

If the release tag changed, also refresh the canonical docs index release link
before the mirror sync:

```bash
uv --preview-features extra-build-dependencies run python - <<'PY'
from tools import pypi_publish
pypi_publish.update_docs_index_release_link("v<release>")
PY
```

Do not call the release fully synced until `runtime.stage` is `RUNNING`, the
runtime SHA matches the uploaded Space SHA, `tools/hf_space_smoke.py --json`
passes, release proof records that Space SHA, the docs index points at the
current release tag, and the published docs page contains the new Space commit.
Verify the last point against the published page, not only raw GitHub content:

```bash
curl -fsSL https://thalesgroup.github.io/agilab/release-proof.html | \
  rg '<space-sha>'
```

## When Editing the Space Contract

If the user asks to change the Space behavior:
- update the sibling apps/docs `huggingface` bundle first
- then update public docs and AGILAB links
- then validate the deploy command path

Do not let the public repo docs claim a Space behavior that the private bundle does not implement.

## What Not To Do

Do not:
- assume the current official path is a Streamlit Space
- silently redesign the Space into a different product shape
- document commands that skip `hf_space_deploy.sh` when the deploy script remains the supported contract
- describe the Space as a full cluster-capable AGILAB environment
- leak private repo paths into public user-facing docs unless they are intentionally framed as maintainer-only instructions

## Recommended Companion Skills

Use with:
- `agilab-docs` when adding or updating public demo links
- `agilab-testing` when validating repo-side changes that affect the Space contract
- `repo-skill-maintenance` when syncing this skill between `.claude/skills` and `.codex/skills`

## Default Execution Pattern

1. Read `thales_agilab/huggingface/README.md`.
2. Confirm whether the request is about the official AGILAB Docker Space or a different experimental demo.
3. If it is the official Space, follow the documented Docker + deploy-script contract.
4. Keep public docs, secrets, and deployment instructions aligned with that contract.
5. Validate the exact deploy path before advertising or linking the Space.
