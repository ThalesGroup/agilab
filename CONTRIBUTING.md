## Team organization
- Jean-Pierre MORARD author
- Jules AMADEI contributor
- Martin VALLS contributor
- Romain LOUVET contributor
- Théo PLANTEFOL contributor
- Julien BESTARD contributor
- Remy CHEN contributor

### Roles
Content developper
Core developper

## How to become a contributor
Send a request at focus@thalesgroup.com containing [CONTRIBUTOR] in its title

### Contributor License Agreements
All contributions must adhere to the BSD-3 license.

### Contributing Code
Please declare in an `IP.md` file any intellectual property used in your code before pushing it to the project's Git repository.

## Pull Request Checklist
Include a license check report using [checklicense](https://pypi.org/project/licensecheck/).

### License
Only non-contaminating licenses (i.e., licenses that do not impose additional restrictions on the project) are allowed.

### Coding Style
We recommend following the Google Python Style Guide and using [Black](https://pypi.org/project/black/) for code formatting.

### Testing
Please include a minimal test suite using [pytest](https://docs.pytest.org/).

#### Running Sanity Check
Include a description of a use case that demonstrates the functionality of your contribution.

#### Running Unit Tests
Ensure that all unit tests are run as part of the regression testing process.

### Issues Management
For issue management, please contact [focus@thalesgroup.com](mailto:focus@thalesgroup.com) and include “[MANAGEMENT]” in the subject line.

## Repository Hygiene
- Do not commit virtual environments or build artifacts:
  - Ignored: `.venv/`, `dist/`, `build/`, `docs/html/`, `docs/build/`, `*.pyc`, `.pytest_cache/`.
  - Recreate envs locally with `uv venv && uv sync` (or `python -m venv .venv && pip install -e .`).
- Documentation
  - Docs are built and published by CI to GitHub Pages from `docs/` (or from `src/agilab/resources/help/` fallback).
  - Do not commit `docs/html/`; edit sources under `docs/` instead.
- Large files and datasets
  - Do not commit datasets, generated binaries, archives, or SQLite databases.
  - Store data externally (artifact storage, buckets) or use Git LFS with explicit patterns.
- History rewrites
  - This repo may periodically rewrite history to remove large artifacts. Rebase or re-clone if you see non-fast-forward updates.
