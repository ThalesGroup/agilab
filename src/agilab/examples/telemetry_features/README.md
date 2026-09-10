# Telemetry Feature Evidence

## Example Class

**Read-only preview.** Computes features from synthetic local tables and writes
a new evidence directory. It does not install an app, deploy workers, or train a
model. Featuretools is optional and is isolated from AGILAB's core environment.

## Purpose

Turn a feature-engineering experiment into a saved recipe that can be reviewed
and replayed. This example adapts Featuretools' separation of feature definitions
from feature values to AGILAB's workflow and evidence conventions.

## What You Learn

- Describe related tables, information-availability timestamps, and history windows.
- Limit synthesis to three features: count, maximum latency, and mean latency.
- Save native Featuretools definitions and reuse them for calculation and replay.
- Inspect feature dependencies and verify input/output hashes independently.

## Install

Install [uv](https://docs.astral.sh/uv/getting-started/installation/). The script's
inline dependency metadata selects Python 3.12, Featuretools 1.31.0, pandas 2.3.3,
Woodwork 0.31.0, and setuptools 80.9.0. `uv run --script` prepares an isolated
environment on first use. Initial dependency setup needs network access; feature
generation itself uses no external data or services.

The setuptools pin supplies `pkg_resources`, which this Woodwork release imports.
Upstream deprecation warnings may appear. These pins belong only to this example;
they do not change AGILAB's runtime or build dependencies.

## Run

From the AGILAB source root:

```bash
uv run --script src/agilab/examples/telemetry_features/preview_telemetry_features.py --output-dir reports/telemetry-features
uv run --no-project python src/agilab/examples/telemetry_features/preview_telemetry_features.py --verify --output-dir reports/telemetry-features
uv run --script src/agilab/examples/telemetry_features/preview_telemetry_features.py --replay --output-dir reports/telemetry-features
```

The second command checks hashes using only the Python standard library. Replay
uses the saved definitions, inputs, and cutoff rules; it does not rerun synthesis.
Both checks print JSON and leave the bundle unchanged. Use a new output directory
for each generation; an existing directory is never intentionally overwritten.

The same files ship in the `agi-apps` wheel under
`agilab/examples/telemetry_features/`. Copy this directory to a working folder and
use the commands above with just `preview_telemetry_features.py` as the script path.
No source checkout or initialized `~/.agilab` workspace is needed.

## Expected Input

Two deterministic tables are generated locally: `assets.csv` contains `node-a`
and `node-b`; `samples.csv` contains their latency observations. There are no
labels, credentials, external downloads, or customer data in the fixture.

Defaults: cutoff `2026-01-01T00:10:00Z`, five minutes of history, and an excluded
cutoff boundary. The interval is `[00:05, 00:10)` in UTC. `available_at` records
when information became usable; `observed_at` is excluded from synthesis. A late
arrival observed at 00:06 but available at 00:11 is therefore excluded.

## Expected Output

```text
reports/telemetry-features/
  assets.csv
  samples.csv
  feature_plan.json
  feature_definitions.json
  feature_matrix.csv
  feature_lineage.json
  feature_lineage.md
  feature_manifest.json
```

The default matrix is:

| asset_id | COUNT(samples) | MAX(samples.latency_ms) | MEAN(samples.latency_ms) |
|---|---:|---:|---:|
| node-a | 3 | 30 | 20 |
| node-b | 3 | 60 | 40 |

`feature_manifest.json` uses `agilab.feature-evidence.v1`. It records the producer
source hash, runtime versions, run id, UTC creation time, relative artifact paths,
sizes, and SHA-256 hashes. Its generation status does not claim that later
verification or replay ran: those states start as `not_run`. Verification and
replay report their own results on stdout.

## Read The Script

`preview_telemetry_features.py` contains the complete example. `feature_plan()`
defines the typed tables and one-to-many relationship; `build_preview()` builds
and saves the recipe, then calculates from the saved definitions.
`verify_evidence()` checks the complete inventory and optionally recomputes the
matrix and lineage. Replay rejects runtime or producer changes.

`lab_stages.toml` exposes generation and replay as two ordered AGILAB workflow
stages. It is an executable local example, not a worker execution record. Run it
in an environment containing the packaged example and its optional dependencies;
the preview commands above do not execute the workflow through `AGI.run`.

## Change One Thing

Generate another bundle with a ten-minute history window:

```bash
uv run --script src/agilab/examples/telemetry_features/preview_telemetry_features.py --window-minutes 10 --output-dir reports/telemetry-features-10m
```

Compare the two matrices: the older observations now contribute. The plan and run
id also change. Start with this single parameter before adapting the input tables.

## Troubleshooting

- **Output already exists:** choose another directory; preserve previous evidence.
- **Missing Featuretools or pkg_resources:** use `uv run --script`, which reads the
  pins. Plain `python` intentionally does not install optional dependencies.
- **Hash mismatch:** an artifact is missing or changed. Recover the original
  bundle or generate a new run; verification does not repair evidence.
- **Runtime/source mismatch:** replay with the producer revision and exact Python
  and package versions in the manifest. Featuretools does not guarantee saved
  definition compatibility across releases.
- **Unexpected historical value:** inspect `available_at`, cutoff inclusion, and
  the lower window boundary before changing the aggregation.

## Validation And Production Boundary

Focused regression command from a development environment containing pytest and
the optional pins:

```bash
uv --preview-features extra-build-dependencies run python -m pytest -q -o addopts='' test/test_telemetry_feature_evidence.py
```

Tests cover known numerical results, future and late-arriving rows, window
boundaries, saved-definition replay, version drift, malformed inventories,
tampering, and verification without optional imports. In the default repository
test environment, numerical Featuretools tests skip when the optional dependency
is absent; run them in the pinned environment for integration evidence.

This bundle proves local artifact consistency and, when replay passes, identical
serialized feature values and lineage for the recorded environment. It is not a
signed attestation, a generic `run_manifest.json`, an accuracy benchmark, or a
guarantee against every form of target leakage. Use only bundles from a producer
you trust. Hashes cannot authenticate a manifest rewritten with its artifacts.
Real telemetry needs immutable availability records, target/identifier exclusion,
data-quality checks, and a representative performance evaluation. Distributed
execution and inference-service deployment are outside this example.

Inspiration: Featuretools' [saved definitions](https://docs.featuretools.com/en/stable/guides/deployment.html),
[time handling](https://docs.featuretools.com/en/stable/getting_started/handling_time.html),
and [feature synthesis and lineage](https://docs.featuretools.com/en/stable/getting_started/afe.html).
