---
name: agilab-huggingface-spaces
description: Maintain and deploy the official AGILAB Hugging Face Docker Space using the sibling thales_agilab/huggingface bundle and public agilab checkout.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-04-28
---

# Hugging Face Spaces Skill (AGILAB)

Use this skill when preparing, validating, or deploying the official AGILAB Hugging Face Space.

The current source of truth is:
- `/Users/agi/PycharmProjects/thales_agilab/huggingface/README.md`
- `/Users/agi/PycharmProjects/thales_agilab/huggingface/hf_space_deploy.sh`
- `/Users/agi/PycharmProjects/thales_agilab/huggingface/Dockerfile`

Do not default to a generic “lightweight one-page demo” plan when the repo already defines a concrete Space contract.

## Current Space Contract

The official Space is currently:
- a **Docker Space**
- named like `<user>/agilab`
- launched on port `7860`
- backed by the AGILAB Streamlit interface
- built from the public `agilab` repo plus the private `thales_agilab/huggingface` packaging bundle

Treat this as the default target unless the user explicitly asks for a different Space shape.

## What the Space Actually Publishes

The current deploy path stages:
- `README.md` from `thales_agilab/huggingface`
- `Dockerfile` from `thales_agilab/huggingface`
- `.dockerignore` from `thales_agilab/huggingface`
- `docker/install.sh` from the public `agilab` repo
- `src/` from the public `agilab` repo
- `pyproject.toml` from the public `agilab` repo
- `uv_config.toml` from the public `agilab` repo

This is not a raw repo push and not a generic Space scaffold. The deploy script assembles a bounded staging directory and uploads that to Hugging Face.

## Runtime and Product Constraints

Keep the skill aligned with the README contract:
- the Space exposes the AGILAB Streamlit interface
- Space mode is single-node only
- offline/local LLM paths such as Ollama are not available there
- storage is ephemeral unless a Hugging Face dataset mount is used

Do not promise:
- multi-node ORCHESTRATE behavior
- remote-cluster parity
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
3. Run the deploy script from the sibling private repo:

```bash
./huggingface/hf_space_deploy.sh \
  --agilab-path </path/to/agilab> \
  --space <user>/agilab \
  --create
```

For an existing Space:

```bash
./huggingface/hf_space_deploy.sh \
  --agilab-path </path/to/agilab> \
  --space <user>/agilab
```

Relevant options from the script:
- `--agilab-path`
- `--space`
- `--private`
- `--create`

Do not replace this with hand-written deployment steps unless the user explicitly wants a new deploy path.

## Validation Before Deploy

Before touching the Space deployment, verify:

1. The public `agilab` checkout exists and is the intended source tree.
2. The sibling `thales_agilab/huggingface` bundle exists and matches the intended Space contract.
3. `hf auth whoami` succeeds, or `HF_TOKEN` is present.
4. The current README, Dockerfile, and deploy script still agree on:
   - SDK type
   - exposed port
   - secret names
   - target repo content
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
git worktree add --detach "$tmpdir" origin/main
git -C "$tmpdir" lfs install --local
git -C "$tmpdir" lfs pull
find "$tmpdir/src/agilab/apps" -maxdepth 1 -mindepth 1 -exec basename {} \; | sort
/Users/agi/PycharmProjects/thales_agilab/huggingface/hf_space_deploy.sh \
  --agilab-path "$tmpdir" \
  --space jpmorard/agilab
```

After upload, verify the Space cutover separately from the file upload:

```bash
hf spaces info jpmorard/agilab --format json
curl -I -L --max-time 20 https://jpmorard-agilab.hf.space/
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
import subprocess
import time

for attempt in range(1, 31):
    info = json.loads(subprocess.check_output(
        ["hf", "spaces", "info", "jpmorard/agilab", "--format", "json"],
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

If the Space is stuck in `RUNNING_BUILDING` or `RUNNING_APP_STARTING`, inspect
the relevant logs before making another upload:

```bash
hf spaces logs jpmorard/agilab --build --tail 120
hf spaces logs jpmorard/agilab --tail 160
```

## When Editing the Space Contract

If the user asks to change the Space behavior:
- update the private `thales_agilab/huggingface` bundle first
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
