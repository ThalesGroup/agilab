<p>
  <a href="https://pypi.org/project/agilab/"><img src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/pypi-version-agilab.svg" alt="PyPI version" /></a>
  <a href="https://opensource.org/licenses/BSD-3-Clause"><img src="https://img.shields.io/badge/License-BSD%203--Clause-blue.svg" alt="License: BSD 3-Clause" /></a>
  <a href="https://thalesgroup.github.io/agilab"><img src="https://img.shields.io/badge/Documentation-online-brightgreen.svg" alt="Documentation" /></a>
  <a href="https://github.com/ThalesGroup/agilab"><img src="https://img.shields.io/github/stars/ThalesGroup/agilab.svg" alt="GitHub stars" /></a>
</p>

<details>
<summary>More project badges</summary>

<p>
  <a href="https://pypi.org/project/agilab/"><img src="https://img.shields.io/pypi/pyversions/agilab.svg" alt="Supported Python Versions" /></a>
  <a href="https://pypi.org/project/agilab/"><img src="https://img.shields.io/pypi/dm/agilab" alt="PyPI downloads" /></a>
  <a href="https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml"><img src="https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a>
  <a href="https://github.com/ThalesGroup/agilab/issues"><img src="https://img.shields.io/github/issues/ThalesGroup/agilab" alt="Open issues" /></a>
  <a href="https://github.com/ThalesGroup/agilab/pulse"><img src="https://img.shields.io/github/commit-activity/m/ThalesGroup/agilab.svg" alt="Commit activity" /></a>
  <a href="tools/agent_workflows.md"><img src="https://img.shields.io/badge/Agents-codex%20%26%20claude%20%26%20aider%20%26%20opencode-0F766E" alt="Agents Codex Claude Aider and OpenCode" /></a>
  <a href=".codex/skills/README.md"><img src="badges/skills-codex.svg" alt="Codex skills" /></a>
  <a href=".claude/skills/README.md"><img src="badges/skills-claude.svg" alt="Claude skills" /></a>
  <a href="docs/source/environment.rst"><img src="https://img.shields.io/badge/Language-python%20free--threaded%20%26%20cythonized-5B6CFF" alt="Language Python free-threaded and Cythonized" /></a>
  <a href="https://github.com/ThalesGroup/agilab/pulls"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs welcome" /></a>
  <a href="https://pypi.org/project/agilab/"><img src="https://img.shields.io/pypi/format/agilab" alt="PyPI format" /></a>
  <a href="https://github.com/ThalesGroup/agilab"><img src="https://img.shields.io/github/repo-size/ThalesGroup/agilab" alt="Repo size" /></a>
  <a href="https://github.com/psf/black"><img src="https://img.shields.io/badge/code%20style-black-000000.svg" alt="Black code style" /></a>
  <a href="https://orcid.org/0009-0003-5375-368X"><img src="https://img.shields.io/badge/ORCID-0009--0003--5375--368X-A6CE39?logo=orcid" alt="ORCID" /></a>
</p>
<p>
  <a href="https://github.com/ThalesGroup/agilab/actions/workflows/coverage.yml"><img src="https://github.com/ThalesGroup/agilab/actions/workflows/coverage.yml/badge.svg?branch=main" alt="Coverage workflow" /></a>
  <a href="https://codecov.io/gh/ThalesGroup/agilab"><img src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agilab.svg" alt="agilab coverage" /></a>
  <a href="https://codecov.io/gh/ThalesGroup/agilab?flags%5B0%5D=agi-gui"><img src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agi-gui.svg" alt="agi-gui coverage" /></a>
  <a href="https://codecov.io/gh/ThalesGroup/agilab?flags%5B0%5D=agi-env"><img src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agi-env.svg" alt="agi-env coverage" /></a>
  <a href="https://codecov.io/gh/ThalesGroup/agilab?flags%5B0%5D=agi-node"><img src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agi-node.svg" alt="agi-node coverage" /></a>
  <a href="https://codecov.io/gh/ThalesGroup/agilab?flags%5B0%5D=agi-cluster"><img src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agi-cluster.svg" alt="agi-cluster coverage" /></a>
  <a href="https://codecov.io/gh/ThalesGroup/agilab?flags%5B0%5D=agi-core"><img src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/coverage-agi-core.svg" alt="agi-core coverage" /></a>
</p>

</details>

# AGILAB

AGILAB is an open-source platform for reproducible AI and ML workflows.

The core idea is simple: keep one app on one control path from setup to run to visible analysis instead of splitting the workflow across ad hoc scripts, environments, and notebooks.

## Start Here

| Goal | Route | Use when |
|---|---|---|
| See the UI now | [AGILAB demo](https://huggingface.co/spaces/jpmorard/agilab) | You want a browser-only look at the web UI before installing anything. |
| Prove it locally | [Quick start](https://thalesgroup.github.io/agilab/quick-start.html) | You want the real source-checkout path with the built-in `flight_project`. Target: pass the first proof in 10 minutes. |
| Use the API/notebook | [agi-core demo](https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_kaggle_first_run.ipynb) | You want the smaller `AgiEnv` / `AGI.run(...)` surface before the full UI. |

## Public Demos

<p>
  <a href="https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_kaggle_first_run.ipynb"><img src="https://img.shields.io/badge/agi--core-demo-1D4ED8?style=for-the-badge" alt="agi-core demo" /></a>
  <a href="https://huggingface.co/spaces/jpmorard/agilab"><img src="https://img.shields.io/badge/AGILAB-demo-0F766E?style=for-the-badge" alt="AGILAB demo" /></a>
</p>

- `AGILAB demo`: self-serve public Hugging Face Spaces demo
- `agi-core demo`: notebook-first runtime demo on Kaggle

Maintainers can validate the public demo KPI with:

```bash
uv --preview-features extra-build-dependencies run python tools/hf_space_smoke.py --json
```

## First Real Run

If you want the real product path, do this once before trying anything else:
use a source checkout, launch the web UI, select the built-in
`flight_project`, run it locally, and confirm a visible result in
`ANALYSIS`.

```bash
git clone https://github.com/ThalesGroup/agilab.git
cd agilab
./install.sh --install-apps
uv --preview-features extra-build-dependencies run streamlit run src/agilab/About_agilab.py
```

If you also want AGILAB to bootstrap local Ollama-backed models, rerun the
installer with the model families you want:

```bash
./install.sh --install-apps --install-local-models qwen,deepseek
```

Supported values are `mistral`, `qwen`, and `deepseek`.

Then in the UI:

1. `PROJECT` -> select `src/agilab/apps/builtin/flight_project`
2. `ORCHESTRATE` -> `INSTALL`, then `EXECUTE`
3. `ANALYSIS` -> open the default view

You are past the newcomer hurdle when:

- fresh output exists under `~/log/execute/flight/`
- the run ends on a visible result in `ANALYSIS`

If that first proof fails, run:

```bash
uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py
```

To track the adoption KPI directly, collect the same proof as JSON. The default
target is 10 minutes end to end:

```bash
uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py --json
```

Current adoption evidence: on April 24, 2026, the local source-checkout
first-proof smoke passed in `5.86s` against the `600s` target. That supports an
`Ease of adoption` score of `3.5 / 5`: the public demo works, the first routes
are explicit, and the local proof is measurable. It is not scored higher yet
because the same measurement still needs a fresh external machine.

Current research experimentation evidence: AGILAB now documents a complete
experiment loop across project templates, isolated `uv` environments,
`lab_steps.toml` history, supervisor notebook export, MLflow-tracked runs, and
analysis pages. That supports a `Research experimentation` score of `4.0 / 5`.
It is not scored higher yet because the generic evidence bundle, a first-class
reduce contract, and broader fresh-install reproducibility checks remain
roadmap work.

Current engineering prototyping evidence: AGILAB now documents how app
templates, isolated app/page environments, typed `app_args_form.py` settings,
`pipeline_view` files, reusable `lab_steps.toml` history, and analysis-page
templates turn an experiment into an app-shaped prototype. That supports an
`Engineering prototyping` score of `4.0 / 5`. It is not scored higher yet
because the first-proof wizard, generic evidence bundle, and first-class reduce
contract remain roadmap work.

Current production-readiness evidence: AGILAB is not positioned as a production
MLOps backbone, but it now documents a controlled pilot path across release
preflight tooling, CI/coverage workflows, service health gates, the
compatibility matrix, the release-decision page, and the security hardening checklist.
That supports a `Production readiness` score of `3.0 / 5`. It is not scored
higher because production model serving, feature stores, online monitoring,
drift detection, enterprise governance, and broad remote-topology certification
remain outside the shipped scope.

Maintainers can collect that evidence as JSON with:

```bash
uv --preview-features extra-build-dependencies run python tools/production_readiness_report.py
```

## Read Next

- [Quick start](https://thalesgroup.github.io/agilab/quick-start.html)
- [Demo chooser](https://thalesgroup.github.io/agilab/demos.html)
- [Notebook quickstart](https://thalesgroup.github.io/agilab/notebook-quickstart.html)
- [Newcomer troubleshooting](https://thalesgroup.github.io/agilab/newcomer-troubleshooting.html)
- [Documentation](https://thalesgroup.github.io/agilab)
- [Flight project guide](https://thalesgroup.github.io/agilab/flight-project.html)
- [Developer runbook](AGENTS.md)
