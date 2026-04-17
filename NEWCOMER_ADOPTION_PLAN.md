# Newcomer Adoption Plan

## Goal

Move AGILAB newcomer adoption from documentation-heavy onboarding to a product-guided first proof.

The target is simple:

- one recommended first path
- one visible success contract
- one short recovery path when that first proof fails

## Current assessment

Current status is roughly `8/10`.

What already works:

- `README.md` has a clear `Start Here` path.
- `docs/source/quick-start.rst` and `docs/source/newcomer-guide.rst` already push newcomers toward the built-in `flight_project` proof path.
- The four-page story is coherent: `PROJECT -> ORCHESTRATE -> PIPELINE -> ANALYSIS`.

What still hurts:

1. The newcomer still has to assemble the first proof manually.
2. Success is documented, but not yet enforced as an in-product checklist.
3. First-failure recovery is still too engineer-oriented.
4. Alternative routes still compete too early with the recommended path.

## Prioritized moves

### 1. Add an in-product first-proof contract

Status: implemented in `src/agilab/About_agilab.py`

What it does:

- shows one recommended path directly on the landing page
- defines the exact first proof steps
- defines the exact success criteria
- links to the three most relevant newcomer docs only

Why first:

- low blast radius
- high visibility
- reduces the chance that users branch too early into cluster, package, or notebook routes

### 2. Add a true newcomer proof command

Status: implemented

Current outcome:

- one command that validates the local built-in proof path
- explicit pass/fail verdict
- output tailored to first-time users instead of maintainers

Implemented as:

- `uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py`

Current behavior:

- validates the built-in `flight_project` path
- runs the preinit smoke
- runs a source UI smoke for `About` + `ORCHESTRATE`
- prints a clear `PASS` / `FAIL` verdict
- optionally runs `src/agilab/apps/install.py` and checks seeded `AGI_*.py` helpers with `--with-install`

Scope:

- install prerequisites check
- built-in app discovery
- local UI smoke
- optional artifact existence check
- concise recovery messages

### 3. Add a first-failure recovery page

Status: pending

Target outcome:

- one short doc focused on the most common newcomer failures
- exact commands for recovery
- no deep internal architecture content

Initial failure set:

- `uv` missing
- install failed
- built-in app path not found
- Streamlit launch failed
- first output not produced

### 4. Compress the top of the README further

Status: pending

Target outcome:

- keep only the first-proof path above the fold
- push benchmarks, alternatives, and deeper stack description lower

### 5. Add one visual newcomer artifact

Status: pending

Target outcome:

- one GIF or screenshot strip showing the first proof path
- same app
- same four pages
- same success signal

## Success signals

The onboarding work is good enough when a newcomer can do all of this without reading deep docs first:

1. install AGILAB from source
2. launch the web UI
3. select the built-in `flight_project`
4. produce visible output once
5. understand what “done” means without asking for help

## Non-goals

These are not newcomer-first goals and should not displace the items above:

- cluster onboarding
- private app repository setup
- contributor workflow depth
- benchmark storytelling
- advanced package/distribution explanations
