# Free-threading compatibility probe

From the AGILAB source checkout, run:

```bash
uv --preview-features extra-build-dependencies run --no-sync python tools/free_threading_probe.py \
  --python 3.14t --output reports/free-threading/probe.json
```

The command builds wheels for `agilab`, `agi-env`, `agi-node`, `agi-cluster`,
and `agi-core`, using the existing release package inventory. It creates a
temporary environment with uv and installs those exact wheels and their
dependencies. It runs outside the source checkout with isolated Python imports
and a temporary user home. The normal installer is not invoked or changed.

Dependency installation requires binary wheels. A dependency without a wheel
for the selected interpreter/platform produces `dependencies_failed`; this is
an installation boundary, not a failed AGILAB worker test. The probe does not
attempt potentially long native dependency builds. `--timeout` bounds each
subprocess separately and defaults to 600 seconds. uv may download a requested
interpreter and cache build/install dependencies.

Once installed, the probe records the GIL state before and after importing
the framework and representative dependencies. It never forces `PYTHON_GIL=0`,
because doing so could conceal an extension's automatic GIL activation.
Imports must come from the temporary environment. If these checks pass, an
in-memory `PolarsWorker` exercises the real mono and thread-pool execution
paths on two chunks containing duplicate and out-of-order inputs. Both paths
must match independently specified values, order, and worker labels.

The JSON report uses schema `agilab.free_threading_probe.v1` and records:

- UTC creation time, producer, interpreter selector, and replay command;
- build/install/runtime steps with passed, failed, or skipped states;
- filenames, sizes, and SHA-256 identities of the tested wheels;
- installed versions and per-import GIL state when runtime checks execute;
- worker output identity and elapsed seconds when worker checks execute.

Exit code 0 means this bounded probe passed; 1 means it failed. The report is
local-only and may contain local paths in diagnostic text. Temporary wheels
and environments are removed, explicitly recorded as `retained: false` for
the wheel identities. Re-run the command to refresh the report; dependencies
are resolved afresh, so it is not an exact dependency-lock replay.

A passing result does not establish general thread safety, shared singleton
safety, UI/SSH/cluster compatibility, Cython extension compatibility, or a
performance improvement. Timings are observations without a speed threshold.
The `1 - Unstable` PyPI classifiers and normal installer restrictions remain
separate from the report. Do not promote a support level based on metadata
validation alone.

The design adopts pylopdf's [installed-artifact and GIL checks](https://github.com/yhay81/pylopdf/blob/main/tests/test_free_threaded.py)
and whenever's [explicit semantic distinctions](https://github.com/ariebovenberg/whenever/blob/main/docs/design.md):
creation timestamps are UTC instants; elapsed measurements use a monotonic
clock. Regression tests enforce those distinctions and compare results across
execution paths. These practices do not require either library as a dependency.

Run the focused regressions with:

```bash
uv --preview-features extra-build-dependencies run --no-sync python -m pytest \
  --import-mode=importlib -q -o addopts= test/test_free_threading_probe.py
```
