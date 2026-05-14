# AGILAB Adoption Guide

Use this guide when you want the shortest path from "what is AGILAB?" to one
verified result. Keep the first pass narrow, then branch into notebooks,
external apps, or cluster work after the local proof succeeds once.

## Fast Adoption Path

| Stage | Action | Stop when |
|---|---|---|
| Preview | Open the public [AGILAB Space](https://huggingface.co/spaces/jpmorard/agilab). | The hosted UI opens the lightweight `flight_telemetry_project` path. |
| Prove locally | Clone the source checkout and run the built-in `flight_telemetry_project`. | `PROJECT` -> `ORCHESTRATE` -> `ANALYSIS` works locally. |
| Record evidence | Run `agilab first-proof --json`. | `~/log/execute/flight_telemetry/run_manifest.json` reports `status: pass`. |
| Expand | Move to notebooks, PyPI package checks, external apps, or cluster work. | You have one known-good baseline to compare against. |

## Choose Your First Path

| Goal | Route | Time box | Success signal |
|---|---|---:|---|
| Preview the UI | Open the public [AGILAB Space](https://huggingface.co/spaces/jpmorard/agilab) | 2 minutes | The Space opens with the lightweight `flight_telemetry_project` path. |
| Prove the product path locally | Follow the source-checkout first run in `README.md` | 10 minutes | `agilab first-proof --json` exits 0, reports `"success": true`, and writes `~/log/execute/flight_telemetry/run_manifest.json`. |
| Check the package entry point | Install from PyPI with `pip install agilab` | 5 minutes | `agilab` starts from a clean environment. |
| Try the smaller runtime API | Use the notebook quickstart | 10 minutes | A notebook run reaches `AGI.run(...)` without launching the web UI. |
| Update external apps | Rerun the installer with `APPS_REPOSITORY` or `--apps-repository` | 10 minutes | The installed app path is a symlink to the apps repository copy. |
| Contribute to AGILAB | Start with `CONTRIBUTING.md` | 15 minutes | A focused local check passes before opening a pull request. |

## Local First Proof

Run this source-checkout path before trying private apps or cluster mode:

```bash
git clone https://github.com/ThalesGroup/agilab.git
cd agilab
./install.sh --install-apps
uv --preview-features extra-build-dependencies run streamlit run src/agilab/main_page.py
```

In the web UI, stay on the built-in `flight_telemetry_project`:

| Page | Action |
|---|---|
| `PROJECT` | Select `src/agilab/apps/builtin/flight_telemetry_project`. |
| `ORCHESTRATE` | Click `INSTALL`, then `EXECUTE`. |
| `ANALYSIS` | Open the default analysis view. |

For a machine-readable proof:

```bash
uv --preview-features extra-build-dependencies run agilab first-proof --json
```

You are past the newcomer hurdle when the proof exits 0, fresh output exists
under `~/log/execute/flight_telemetry/`, and `run_manifest.json` is present.

## Avoid On Day 1

- Do not start with cluster mode; prove the local path first.
- Do not start with private apps; use the public built-in `flight_telemetry_project`.
- Do not run full test suites during first install unless validation is the goal.
- Do not use `uvx agilab` from inside a source checkout; it runs the published wheel.
- Do not assume PyCharm is required; shell and browser are the supported first route.

## If The First Proof Fails

Keep the scope narrow and rerun the proof command before changing routes:

```bash
uv --preview-features extra-build-dependencies run agilab first-proof
```

Use the public troubleshooting page for first-run failures:
https://thalesgroup.github.io/agilab/newcomer-troubleshooting.html

Common first checks:

- `uv` is installed and visible in the shell.
- `./install.sh --install-apps` completed without installer errors.
- The selected app is `src/agilab/apps/builtin/flight_telemetry_project`.
- The Streamlit command is run from the repository root.
- Output is checked under `~/log/execute/flight_telemetry/`, not a copied project path.

## Contributor Day 1

For contribution work, start with the same local-first discipline, then pick
one contribution lane from `CONTRIBUTING.md` before editing:

```bash
git clone https://github.com/ThalesGroup/agilab.git
cd agilab
git config core.hooksPath .githooks
uv --preview-features extra-build-dependencies sync --group dev
uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py
```

Before opening a pull request, run the narrowest check that proves your change.
For docs-only changes, `git diff --check` is usually enough. For code changes,
prefer targeted `pytest` or the matching `tools/workflow_parity.py --profile`
command before broader validation.

Paste the validation command and result in the pull request. If you are unsure
which lane applies, open a `[CONTRIBUTOR]` issue with the command you ran and
the first failing log lines.
