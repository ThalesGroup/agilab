# view_release_decision

Reusable Streamlit analysis page for baseline-vs-candidate promotion decisions.

Primary use:

- compare two exported metric bundles
- gate promotion on first-proof `run_manifest.json`
- import external run-manifest evidence with `--manifest` / `--manifest-dir`
- attach SHA-256, size, mtime, provenance tag, and optional sidecar signature metadata to imported manifests
- apply explicit artifact and KPI gates
- export `promotion_decision.json`
- maintain a per-artifact-root `manifest_index.json`
- compare current evidence against prior indexed releases
- compare full evidence bundles across runs

Default search root:

- `~/export/<app_target>`

For `meteo_forecast_project`, the page defaults to:

- metrics glob: `**/forecast_metrics.json`
- required artifact patterns:
  - `forecast_metrics.json`
  - `forecast_predictions.csv`

The page also defaults to `~/log/execute/flight/run_manifest.json` for the
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
