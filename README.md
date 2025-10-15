[![PyPI version](https://img.shields.io/pypi/v/agilab.svg?color=informational)](https://pypi.org/project/agilab)
[![Supported Python Versions](https://img.shields.io/pypi/pyversions/agilab.svg)](https://pypi.org/project/agilab/)
[![License: BSD 3-Clause](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![pypi_dl](https://img.shields.io/pypi/dm/agilab)]()
[![CI](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml/badge.svg)](https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/ThalesGroup/agilab/branch/main/graph/badge.svg)](https://codecov.io/gh/ThalesGroup/agilab)
[![GitHub stars](https://img.shields.io/github/stars/ThalesGroup/agilab.svg)](https://github.com/ThalesGroup/agilab)
[![black](https://img.shields.io/badge/code%20style-black-000000.svg)]()
[![docs](https://img.shields.io/badge/docs-online-brightgreen.svg)](https://thalesgroup.github.io/agilab)
[![ORCID](https://img.shields.io/badge/ORCID-0009--0003--5375--368X-A6CE39?logo=orcid)](https://orcid.org/0009-0003-5375-368X)


# AGILAB Open Source Project

AGILAB [BSD license](https://github.com/ThalesGroup/agilab/blob/main/LICENSE) is an MLOps toolchain for engineering, powered by the OpenAI API, local GPT-OSS, local Mistral-Instruct, and MLflow. It helps you move from notebooks to production with CLI tooling, optional IDE run configurations, and packaged workers. IDE integrations remain available for teams that rely on them, but they are no longer required.

Docs publishing
- The static site is committed under `docs/html` and deployed by GitHub Pages directly (no Sphinx build in CI).
- Preferred path: run `docs/gen_docs.sh`. It builds Sphinx if a config exists; otherwise it syncs `src/agilab/resources/help/` into `docs/html` and ensures an `index.html` is present.
- CI will deploy the committed `docs/html`; if it’s empty, the workflow falls back to copying from `src/agilab/resources/help/`.
See [documentation](https://thalesgroup.github.io/agilab).

See also: CHANGELOG.md for recent changes.

## Audience profiles

- **Manager** launch `uvx agilab`; no repository checkout or IDE is required.
- **End users** create a uv workspace and launch `uv run agilab` ; no repository checkout or IDE is required.
- **Developers** clone this repository and launch install.sh; an Pycharm IDE is strongly recommended. 
see below for more details 

## Install and Execution for end users

Quick run (no setup):

```bash
uvx -p 3.13 agilab
```

> **Note**
> This `uvx` invocation is meant for demos or smoke tests. Any changes you make inside the cached package will be overwritten on the next run. For development, clone the repository or use a virtual environment.

### Offline assistant (GPT-OSS)

Prefer to stay offline? Start a local GPT-OSS responses server and switch the “Assistant engine” selector (in the Experiment page sidebar) to *GPT-OSS (local)*:

```bash
python -m pip install "agilab[offline]"
python -m pip install transformers torch accelerate  # installs the local backends used by GPT-OSS
python -m gpt_oss.responses_api.serve --inference-backend transformers --checkpoint gpt2 --port 8000
```

Update the endpoint field if you expose the server on a different port. The sidebar now lets you pick the GPT-OSS backend (stub, transformers, ollama, …), checkpoint, and extra launch flags; the app persists the values in `env.envars`. The default *stub* backend is only a connectivity check and returns canned responses—switch to `transformers` (or another real backend) to receive model-generated code.
When GPT-OSS is installed and the endpoint targets ``localhost``, the sidebar automatically launches a local server the first time you switch to *GPT-OSS (local)* using the configured backend.

Managed workspace (project folder):

```bash
mkdir agi-space && cd agi-space
uv init --bare --no-workspace
uv add agilab
uv run agilab
```

### CLI wrappers for run configurations

Every IDE run configuration now has a matching shell script under `tools/run_configs/`. Regenerate them at any time with:

```bash
python3 tools/generate_runconfig_scripts.py
```

The generator groups scripts under `tools/run_configs/<group>/` (`agilab`, `apps`, `components`). Each wrapper exports the same environment variables, switches to the correct working directory, and executes the underlying `uv` command—no IDE required.

## Install for developers

<details open> 
<summary>
    <strong> Linux and MacOs </strong>
</summary>

```bash
git clone https://github.com/ThalesGroup/agilab
cd agilab
./install.sh --openai-api-key "sk-your-api-key" --cluster-ssh-credentials "username[:password]"
```
</details>

<details> 
<summary>
    <strong>Windows</strong>
</summary>

```powershell
git clone https://github.com/ThalesGroup/agilab
cd agilabpush it
powershell.exe -ExecutionPolicy Bypass -File .\install.ps1 --openai-api-key "sk-your-api-key"
```
</details>

## AGILab Execution

### Linux and MacOS and Windows:

```bash
cd agilab/src/agilab
uv run agilab
```

## Credits

- Portions of `src/agilab/apps-pages/view_barycentric/src/view_barycentric/view_barycentric.py`
  are adapted from Jean-Luc Parouty’s “barviz / barviz-mod” project (MIT License).
  See `NOTICE` and `LICENSES/LICENSE-MIT-barviz-mod` for details.

## Notes for developers

- AgiEnv is a singleton. Use instance attributes (`env.apps_dir`, `env.logger`, etc.).
  Class attribute reads (e.g., `AgiEnv.apps_dir`) proxy to the singleton when initialised;
  methods/properties are not shadowed. A few helpers are pre‑init safe
  (`AgiEnv.set_env_var`, `AgiEnv.read_agilab_path`, `AgiEnv._build_env`, `AgiEnv.log_info`).

- Environment flags (replaces legacy `install_type`):
  - `env.is_source_env`: true when running from a source checkout.
  - `env.is_worker_env`: true in worker-only contexts (e.g., `wenv/*_worker`).
  - `env.is_local_worker`: helper flag for home‑scoped worker layouts.

- App constructors (templates + flight_project) ignore unknown kwargs when constructing
  their Pydantic `Args` models. This preserves strict validation while making constructors
  resilient to incidental extras. Configure verbosity via `AgiEnv(verbose=…)` or logging,
  not via app `Args`.
