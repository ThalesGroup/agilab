<p>
  <a href="https://pypi.org/project/agilab/"><img src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/pypi-version-agilab.svg" alt="PyPI version" /></a>
  <a href="https://opensource.org/licenses/BSD-3-Clause"><img src="https://img.shields.io/badge/License-BSD%203--Clause-blue.svg" alt="License: BSD 3-Clause" /></a>
  <a href="https://thalesgroup.github.io/agilab"><img src="https://img.shields.io/badge/Documentation-online-brightgreen.svg" alt="Documentation" /></a>
  <a href="https://thalesgroup.github.io/agilab/demos.html"><img src="https://img.shields.io/badge/Demos-public-0F766E" alt="Public demos" /></a>
  <a href="https://github.com/ThalesGroup/agilab"><img src="https://img.shields.io/github/stars/ThalesGroup/agilab.svg" alt="GitHub stars" /></a>
</p>

# AGILAB

AGILAB is an open-source platform for reproducible AI and ML workflows.

The core idea is simple: keep one app on one control path from setup to visible evidence instead of splitting the workflow across ad hoc scripts, environments, and analysis glue.

## Try It Before Installing

- [Public demo entry points](https://thalesgroup.github.io/agilab/demos.html)

## Start Here

If this is your first visit, use one path only:

- source checkout
- web UI
- built-in `flight_project`
- local run
- visible result in `ANALYSIS`

```bash
git clone https://github.com/ThalesGroup/agilab.git
cd agilab
./install.sh --install-apps --test-apps
uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py
uv --preview-features extra-build-dependencies run streamlit run src/agilab/About_agilab.py
```

Then in the UI:

1. `PROJECT` -> select `src/agilab/apps/builtin/flight_project`
2. `ORCHESTRATE` -> `INSTALL`, then `EXECUTE`
3. `ANALYSIS` -> open the default view

You are past the newcomer hurdle when:

- fresh output exists under `~/log/execute/flight/`
- the run ends on a visible result in `ANALYSIS`

If that first proof fails, use:

- [Newcomer troubleshooting](https://thalesgroup.github.io/agilab/newcomer-troubleshooting.html)

## Other Ways To Try AGILAB

- [agi-core demo](https://thalesgroup.github.io/agilab/notebook-quickstart.html)
- [AGILAB demo](https://thalesgroup.github.io/agilab/quick-start.html#hosted-agilab-demo)
- [Published package route](https://thalesgroup.github.io/agilab/quick-start.html#alternative-install-routes)

## Why Use It

- Run the same app through local execution, distributed workers, or service mode.
- Keep environments, logs, outputs, and analysis tied to the same app context.
- Make replayable workflow steps explicit instead of burying them in shell history.

## Read Next

- [Documentation](https://thalesgroup.github.io/agilab)
- [Quick start](https://thalesgroup.github.io/agilab/quick-start.html)
- [Compatibility matrix](https://thalesgroup.github.io/agilab/compatibility-matrix.html)
- [Flight project guide](https://thalesgroup.github.io/agilab/flight-project.html)
- [Developer runbook](AGENTS.md)
