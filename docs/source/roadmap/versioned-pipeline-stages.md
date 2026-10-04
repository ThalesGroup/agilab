# Versioned pipeline stage templates

WORKFLOW supports explicit `template` and `raw_python` stages. A template
stores its reviewed parameters and registry identity; Python remains a readable
rendered artifact. Custom Python retains its source exactly.

This lifecycle is implemented in the source checkout. Publication and hosted
deployment evidence are tracked separately in the release proof.

## Create and inspect a template

Open **Versioned stage templates** in WORKFLOW. The typed registry provides
input configuration, execution configuration, evidence paths, and a named app
action using `RunRequest` and `StageRequest`. Template IDs identify generic
orchestration shapes. The target app and action are parameters.

Persisted fields are:

- `kind = "template"`
- `template_id`, `template_version`, and `template_fingerprint`
- `template_payload` with schema `agilab.pipeline_stage_payload.v1`
- `payload_fingerprint`
- `C`, when cached, as the inspectable rendered Python artifact

The payload's `parameters` table accepts only the current template's named
parameters and TOML-compatible Python literals. Unknown names, objects, `None`,
and non-finite numbers are rejected.

Use the registry helpers rather than hand-writing fingerprints:

```python
from agilab.pipeline.pipeline_stage_templates import (
    DEFAULT_PIPELINE_STAGE_TEMPLATE_REGISTRY,
    refresh_pipeline_stage_template,
)

stage = DEFAULT_PIPELINE_STAGE_TEMPLATE_REGISTRY.saved_stage(
    "pipeline.agi_run.single_action"
)
payload = stage["template_payload"]
payload["parameters"].update(
    app="example_project",
    apps_path="/path/to/apps",
    action="reference_allocator",
    args={"time_horizon": 16},
)
stage = refresh_pipeline_stage_template(stage, payload=payload)
# Persist under the app module key in lab_stages.toml.
```

A valid template can render without cached `C`. Saving through the supported
helpers keeps the rendered code and structured payload aligned.

## Detect and resolve drift

The registry fingerprint covers identity, version, runtime, payload schema and
renderer code. Drift is visible when the saved version or renderer changes, the
template is missing, the payload is malformed or changed without review, or
cached Python differs from the payload.

Loading never repairs saved Python. Static validation reports
`stage-template-drift`; execution and both plain and supervisor notebook
exports reject stale structured stages before using their code.

The user can choose:

- **Apply template parameters** to apply reviewed literal parameters.
- **Refresh from template** to render with the current registered contract.
- **Keep as custom Python** to retain the exact source as `raw_python`.

Refresh preserves stage identity, dependencies, outputs, app metadata, runtime
environment and user descriptions. Keeping custom Python removes template
ownership and preserves the previous metadata in `template_origin`. Deliberate
edits in the normal editor, HISTORY or an imported notebook also relinquish
template ownership. Registry or schema drift alone never implies such an edit.

## Convert an existing lab explicitly

**Preview legacy stage conversion** displays recognized template IDs and the
proposed kinds without changing the source. **Apply reviewed stage conversion**
recomputes that plan and refuses a changed target or source hash. It saves an
adjacent backup of the exact original TOML and replaces the lab atomically.

Only exact, current registered generated shapes become templates. Unknown,
modified, obsolete or app-owned snippets remain exact `raw_python`. Arbitrary
Python and old ORCHESTRATE snippets are not automatically rewritten.

Existing labs remain usable under their existing runtime prerequisites. A
future compatibility-retirement policy requires evidence that active labs have
been converted; it is separate from this implementation.

## Notebook roundtrip and ownership

Supervisor exports preserve structured metadata in `agilab.stage_cell` and
include it in stage fingerprints. Import restores that metadata before
reconciling the editable Python source. An intentional notebook code edit
becomes custom Python; unchanged structured stages retain their template
identity and drift checks.

See the native React and notebook guide for source recovery, reviewed cell edits
and explicit setup-cell conversion. Mixed runtimes retain their supervisor and
external-runtime boundaries.

## Validation boundary

Focused regression tests exercise TOML persistence, actual save/run/export
entrypoints, payload and registry drift, backup and concurrent-edit protection,
legacy builtin labs and native Python UI controls. Notebook execution evidence
uses fresh Python kernels. These checks do not certify cloud workers, foreign
kernels, private data or a public deployment.
