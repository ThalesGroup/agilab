---
name: agilab-example-maturity
description: Improve or review AGILAB packaged examples for external-beta maturity. Use when working on src/agilab/examples, example install/run scripts, example READMEs, app installer example seeding, or tests that enforce example quality, pedagogy, public API usage, deterministic first-run behavior, and newcomer-safe adaptation.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-01
---

# AGILAB Example Maturity

## Goal

Raise AGILAB packaged examples from internal smoke snippets to external-beta
examples: readable, deterministic, copy/paste safe, aligned with docs, and
protected by tests.

Use this with `plan-before-code` for non-trivial edits, with `agilab-testing`
when validation scope is unclear, and with `repo-skill-maintenance` when this
skill itself changes.

## Inspect First

Before editing, inspect:

- `src/agilab/examples/README.md`
- `src/agilab/examples/*/README.md`
- `src/agilab/examples/*/AGI_*.py`
- `src/agilab/apps/builtin/*_project/` when packaged built-in app assets are touched
- `src/agilab/apps/templates/*_template/` when starter templates are touched
- `src/agilab/apps/install.py`, especially `_seed_example_scripts`
- `test/test_app_installer_packaging.py`
- `pyproject.toml` package-data only if adding/removing packaged example files

Check the current dirty tree before touching files. Do not revert unrelated
release, connector, docs, badge, or user edits.

When the request mentions missing app files, run a source-asset audit before
assuming the file is absent. Check both tracked files and ignored/untracked
source-like files:

```bash
git status --short --ignored --untracked-files=all src/agilab/apps/builtin src/agilab/apps/templates
git ls-files 'src/agilab/apps/**' | sort
find src/agilab/apps/builtin src/agilab/apps/templates -maxdepth 4 -type f \
  \( -name 'README.md' -o -name 'pyproject.toml' -o -name 'app_args_form.py' \
     -o -name 'app_settings.toml' -o -name 'pre_prompt.json' \
     -o -name 'lab_steps.toml' -o -name 'pipeline_view.dot' \
     -o -name 'notebook_export.toml' -o -name 'notebook_import_views.toml' \) -print | sort
```

If `git check-ignore` shows a source asset is hidden by `.gitignore`, fix the
ignore rule and add a regression test so `git add -A` would see the file next
time. Do not treat generated directories (`.venv`, `__pycache__`, build output,
local `.egg-info`) or generated Cython/C files as missing source assets.

## Quality Bar

Treat an example as mature only if all of these are true:

- It explains the purpose before showing mechanics.
- It uses the current `AGI.run(app_env, request=RunRequest(...))` API.
- It avoids private AGI internals such as `AGI._RUN_MASK`.
- It avoids magic mode literals like `mode=13` or `modes_enabled=15`.
- It uses `asyncio.run(main())` unless there is a documented reason not to.
- It gives a friendly error when `~/.local/share/agilab/.agilab-path` is missing.
- It is deterministic and local-first: localhost scheduler, one worker, public inputs.
- It names expected input and output paths in the matching README.
- It gives one safe "change one thing" adaptation step.
- It contains no orphan scratch snippets, undefined variables, hidden private-app paths, or examples that only work in a developer checkout.

For packaged built-in apps and templates, also require:

- root `README.md` and `pyproject.toml`
- `src/app_args_form.py`, `src/app_settings.toml`, and `src/pre_prompt.json`
- any app-declared notebook manifests such as `notebook_export.toml` or
  `notebook_import_views.toml`
- conceptual pipeline files such as `lab_steps.toml` or `pipeline_view.dot` when
  the app documents or UI references them
- package-data patterns in `pyproject.toml` for every file class expected in the
  wheel, and no stale exclude pattern that removes a runtime/UI seed file

External/private apps under `src/agilab/apps/<name>_project` are not public
package assets unless explicitly added to the public distribution. If a local
stub exists but the complete app is in `APPS_REPOSITORY`, report that distinction
instead of packaging private code.

## Implementation Rules

Keep the examples self-contained unless the installer is updated to copy any
shared helper alongside every installed example. Remember `_seed_example_scripts`
copies `AGI_*.py` files into `~/log/execute/<app>/`.

Prefer public, explicit mode constants:

```python
LOCAL_RUN_MODES = AGI.PYTHON_MODE | AGI.CYTHON_MODE | AGI.DASK_MODE
PYTHON_ONLY_MODE = AGI.PYTHON_MODE
```

Use a small local bootstrap helper in each script when no copied shared helper is
available:

```python
def agilab_apps_path() -> Path:
    marker = Path.home() / ".local/share/agilab/.agilab-path"
    if not marker.is_file():
        raise SystemExit(
            "AGILAB is not initialized. Run the AGILAB installer or "
            "`agilab first-proof --json` before this example."
        )
    return Path(marker.read_text(encoding="utf-8").strip()) / "apps"
```

Delete or rename scratch snippets that are not runnable standalone examples.
If a fragment is intentionally for a notebook or pipeline editor, document it as
such and prevent the installer from seeding it as a normal run script.

## Test Contracts

Strengthen `test/test_app_installer_packaging.py` when changing examples. Useful
contracts include:

- every packaged example script compiles
- install/run scripts can be imported with a fake home
- every README has `Purpose`, `What You Learn`, `Install`, `Run`,
  `Expected Input`, `Expected Output`, `Read The Script`, `Change One Thing`,
  and `Troubleshooting`
- no example uses `AGI._` private internals
- no example uses legacy `AGI.run(..., mode=...)`
- no example uses `asyncio.get_event_loop().run_until_complete`
- no copied `AGI_*.py` file contains undefined scratch-only symbols such as a
  top-level `df`
- every packaged built-in app/template has the required project assets listed
  above
- source-like packaged app files are either tracked or visible to Git as
  untracked files, never hidden by broad ignore rules
- package-data includes newly added example/app file classes, and
  exclude-package-data does not remove files the UI or installer expects

## Validation

Run the narrow validations first:

```bash
uv --preview-features extra-build-dependencies run python -m py_compile $(find src/agilab/examples -name '*.py' -print)
uv --preview-features extra-build-dependencies run pytest -q -o addopts='' test/test_app_installer_packaging.py
uv --preview-features extra-build-dependencies run python tools/impact_validate.py --files <changed-files>
git diff --check
```

When app assets, notebook migration examples, manifests, or package-data change,
add a wheel-level proof:

```bash
rm -rf build src/agilab.egg-info
uv --preview-features extra-build-dependencies build --wheel
uv --preview-features extra-build-dependencies run python - <<'PY'
from pathlib import Path
from zipfile import ZipFile

wheel = sorted(Path("dist").glob("agilab-*.whl"))[-1]
required = [
    "agilab/apps/builtin/<app>_project/README.md",
    "agilab/apps/builtin/<app>_project/src/pre_prompt.json",
]
with ZipFile(wheel) as zf:
    names = set(zf.namelist())
missing = [name for name in required if name not in names]
print(wheel)
print("missing", missing)
raise SystemExit(1 if missing else 0)
PY
```

Replace the placeholder `required` list with the exact assets changed in the
task. This catches the common failure where files exist locally but are hidden
from Git or excluded from the wheel.

If `impact_validate.py` asks for broader validation, follow it. If the coverage
badge guard is blocked by unrelated stale XML or unrelated dirty files, report
that explicitly instead of hiding it.

## Close-Out

Report:

- which examples were changed
- which packaged app/template assets were added, unhidden, or included in the wheel
- which maturity risks were removed
- which tests passed
- whether a clean wheel was inspected when packaging changed
- any remaining gap, especially if examples were not actually executed end to end
