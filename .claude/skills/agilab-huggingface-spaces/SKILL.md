---
name: agilab-huggingface-spaces
description: Package and publish a lightweight public AGILAB demo to Hugging Face Spaces without leaking local-only runtime assumptions.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-04-22
---

# Hugging Face Spaces Skill (AGILAB)

Use this skill when preparing, packaging, or publishing an AGILAB demo to Hugging Face Spaces.

## Scope

This skill is for a **public lightweight demo surface**, not for shipping the full AGILAB local/distributed shell as-is.

Prefer:
- one built-in app or one apps-pages view
- tiny bundled data or deterministic sample data generation
- CPU-safe execution
- no private repositories
- no cluster/share assumptions

Do not treat Spaces as a first target for:
- ORCHESTRATE cluster workflows
- multi-node demos
- demos that require local `~/agi-space`, `~/wenv`, or external mounted shares
- demos that depend on private Thales repos or non-public datasets

## First Decision: What Exactly Goes To Spaces

Choose the narrowest truthful demo surface.

Good candidates:
- one `src/agilab/apps-pages/*` view with a built-in app and tiny sample outputs
- one newcomer-first built-in demo with precomputed artifacts
- one notebook-derived public mini-demo converted into a simple page

Avoid “whole product in the browser” as a first Space.
The correct first release is usually:
- one page
- one scenario
- one clear outcome

## Space Type Decision

### Use a Streamlit Space when:
- the demo is a single Streamlit app
- startup is simple
- runtime can be expressed with normal Python dependencies
- no custom system packages or process orchestration are required

### Use a Docker Space when:
- the demo needs stricter environment control
- startup requires custom launch steps
- the AGILAB runtime assumptions do not fit the default Streamlit Space contract cleanly

Default to **Streamlit Space** only if the demo really is lightweight and standalone.
Otherwise choose **Docker Space** early instead of fighting the platform.

## Required Public Demo Contract

Before publishing, make sure the demo has:
- one explicit entrypoint
- one clear README with what the user is seeing
- one bounded dependency set
- one bounded data contract
- one bounded resource profile

The packaging must state clearly:
- which app/page is exposed
- what data is bundled vs generated on startup
- whether secrets are required
- whether the demo is CPU-only
- expected startup latency
- expected memory footprint

## AGILAB-Specific Guardrails

### Remove local-only assumptions

The demo must not depend on:
- `~/agi-space`
- local `APPS_REPOSITORY`
- cluster credentials
- mounted cluster shares
- source checkout sibling repos
- developer machine `HOME` state

If the page expects AGILAB runtime state, provide a public-safe bootstrap path explicitly.

### Keep the demo app-local when possible

Do not patch shared core just to satisfy a Spaces packaging quirk unless the same problem is real for normal AGILAB users too.

Prefer:
- a demo wrapper
- a demo-specific bootstrap helper
- a small public sample-data path

over a broad runtime change.

### Public data only

Use:
- bundled tiny public sample files
- synthetic/generated demo data
- precomputed public artifacts

Do not publish:
- private customer data
- large internal datasets
- anything requiring credentials just to render the first screen

## Packaging Checklist

For every Spaces demo, define:
- entry script
- dependency file (`requirements.txt` or Dockerfile path)
- sample-data location
- cache directory policy
- secret/env var list
- startup command
- local reproduction command

The Space should be reproducible locally with one command from a clean checkout.

## Validation Before Publish

Run these checks before pushing a Space-oriented demo:

1. Local clean-home check
- force a clean `HOME`
- verify the demo does not read polluted local AGILAB state

2. Standalone launch check
- run the exact public entrypoint locally
- confirm no private repo path is required

3. App/page smoke check
- if Streamlit-based, use the narrowest local smoke or AppTest path available
- keep the validation focused on the actual public entrypoint

4. Data contract check
- verify sample data exists or is generated deterministically
- verify startup does not need heavyweight downloads unless explicitly intended

5. Resource check
- confirm the demo still works under a constrained CPU-only profile

## Documentation Checklist

For a new Space, keep the public docs aligned:
- README demo links
- `docs/source/demos.rst`
- any newcomer/demo chooser page
- screenshots or GIFs only if they still match the deployed Space

Do not advertise a Space until:
- the local repro path works
- the Space entrypoint is stable
- the public docs describe the real constraints

## Recommended Companion Skills

Use with:
- `agilab-streamlit-pages` when the Space entrypoint is a Streamlit page
- `agilab-testing` for the narrow smoke and regression slice
- `agilab-docs` when adding public demo links or updating demo docs
- `agilab-product-reels` when the Space should align with a public demo video or GIF

## Default Execution Pattern

1. Choose one truthful public demo surface.
2. Decide Streamlit Space vs Docker Space early.
3. Strip local/private runtime assumptions.
4. Package only public-safe assets and dependencies.
5. Prove the exact public entrypoint locally from a clean environment.
6. Update docs/demo routing only after the demo is actually reproducible.
