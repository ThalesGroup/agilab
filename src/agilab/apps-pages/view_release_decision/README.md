# view_release_decision

Reusable Streamlit analysis page for baseline-vs-candidate promotion decisions.

Primary use:

- compare two exported metric bundles
- resolve artifact, log, export, and first-proof paths through the shared connector path registry
- gate promotion on first-proof `run_manifest.json`
- import external run-manifest evidence with `--manifest` / `--manifest-dir`
- import CI artifact harvest evidence from `ci_artifact_harvest.json`
- attach SHA-256, size, mtime, provenance tag, and optional sidecar signature metadata to imported manifests
- apply explicit artifact and KPI gates
- export `promotion_decision.json`
- maintain a per-artifact-root `manifest_index.json`
- compare current evidence against prior indexed releases
- compare full evidence bundles across runs

Default search root:

- `~/export/<app_target>`

The page resolves that root through the shared AGILAB connector path registry.
The same registry also records the export root, log root, app artifact root,
app execute-log root, first-proof log root, first-proof manifest, and page-bundle
root when available. Those connector rows are shown in the page and exported in
`promotion_decision.json` as `connector_registry_paths` plus
`connector_registry_summary`, so downstream tools can reason about portable
artifact and log paths instead of reconstructing local path glue.

For `weather_forecast_project`, the page defaults to:

- metrics glob: `**/forecast_metrics.json`
- required artifact patterns:
  - `forecast_metrics.json`
  - `forecast_predictions.csv`

The page also defaults to `~/log/execute/flight_telemetry/run_manifest.json` for the
first-proof gate. Promotion is blocked unless that manifest has `status: pass`,
uses the `source-checkout-first-proof` path id, passes all recorded validations,
and completes within its target seconds.

Paste compatibility-report style import args into **Imported run manifest
evidence** when the first-proof manifest comes from another machine or evidence
directory, for example:

```bash
--manifest /path/to/run_manifest.json --manifest-dir /path/to/evidence
```

Imported manifests are shown with source path, provenance, path id, manifest
status, timing, validation statuses, evidence status, and attachment metadata.
Each import is provenance-tagged with SHA-256, byte size, and UTC modified time.
If a sidecar signature exists next to the manifest as `.sig`, `.minisig`, or
`.asc`, the page records its path and SHA-256 and marks the attachment as
signed. A passing imported `source-checkout-first-proof` manifest can satisfy
the first-proof gate, and the same import summary is written to
`promotion_decision.json`.

Paste CI artifact harvest evidence into **CI artifact harvest evidence** when
external-machine evidence has already been collected as a
`ci_artifact_harvest.json` report, for example:

```bash
--ci-artifact-harvest /path/to/ci_artifact_harvest.json
```

The page shows the harvested attachment kind, payload status, SHA-256
verification status, source machine, workflow, CI run id, and release status.
A provided harvest blocks promotion if it is invalid, incomplete, or contains
checksum mismatches. The harvest summary and rows are exported in
`promotion_decision.json` as `ci_artifact_harvest_summary` and
`ci_artifact_harvest_evidence`.

Export also updates `<artifact_root>/manifest_index.json`. The index groups
imported run manifests by candidate bundle, so later release decisions can keep
durable evidence history instead of relying only on pasted import arguments.
The page also shows a cross-release manifest comparison that flags better,
stale, missing-current, failed, and newly validated evidence relative to prior
indexed candidate bundles, including whether attachment hashes match prior
evidence.
The exported decision also includes a cross-run evidence bundle comparison that
summarizes selected manifest, KPI, required artifact, and reduce-artifact
evidence against the selected baseline and prior indexed releases.

This is the first app-layer MVP for AGILAB's promotion / release decision workflow.
