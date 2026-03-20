# Connector Integration Change Request

Date: 2026-03-20

## Purpose

This note captures the proposed change discussed for AGILab: replace repeated raw path settings in `app_settings.toml` with references to reusable connector definition files.

The goal is to make path-heavy page defaults more:

- reusable across pages
- portable across machines
- easier to validate
- easier to evolve without duplicating path logic in many app settings files

This note is intended to be reloaded later as the implementation brief if we decide to proceed.

## Current Problem

Today, pages such as `view_maps_network` rely on raw path-related settings in `app_settings.toml`, for example:

- base directory choices
- relative dataset paths
- file globs
- cloud-map paths
- allocation/baseline artefact paths

This creates several problems:

- the same path logic is repeated in multiple places
- settings are more machine-specific than they should be
- path groups that logically belong together are split across separate keys
- GUI pages must interpret many low-level path keys directly
- changes are harder to propagate consistently across apps/pages

## Proposed Direction

Introduce a new runtime class named `Connector` and persist connector definitions in separate declarative files.

`app_settings.toml` should reference those connector files instead of embedding all path details inline.

The design should be:

- declarative
- git-friendly
- human-readable
- backward compatible

It should **not** persist serialized Python objects.

## Proposed Connector Model

Recommended first version of the runtime object:

```python
class Connector:
    id: str
    kind: str
    label: str | None
    description: str | None
    base: str
    subpath: str | None
    globs: list[str]
    preferred_file_ext: str | None
    metadata: dict[str, Any]
```

Recommended meanings:

- `id`: stable connector identifier
- `kind`: logical role such as `dataset`, `trajectory`, `allocation`, `baseline`, `heatmap`
- `label`: GUI-friendly display name
- `description`: optional explanation
- `base`: one of `AGI_SHARE_DIR`, `AGILAB_EXPORT`, `Custom`
- `subpath`: relative path under the chosen base
- `globs`: file-discovery patterns
- `preferred_file_ext`: optional default file type such as `csv` or `parquet`
- `metadata`: extension point for page-specific hints

## Connector File Format

Connector files should be TOML, not Python persistence.

Example:

```toml
id = "flight_dataframe"
kind = "dataset"
label = "Flight dataframe"
description = "Default built-in flight dataframe exports."
base = "AGI_SHARE_DIR"
subpath = "flight/dataframe"
globs = ["*.parquet", "*.csv"]
preferred_file_ext = "parquet"

[metadata]
map_page_default = true
network_page_default = true
```

## File Location

Recommended initial location:

- relative to the app settings directory
- for example:
  - `src/app_settings.toml`
  - `src/connectors/flight_dataframe.toml`

Recommended rule:

- connector references in `app_settings.toml` are resolved relative to the directory containing `app_settings.toml`
- absolute paths may be allowed but should be discouraged

This keeps the app self-contained and packaging-friendly.

## `app_settings.toml` Changes

Instead of raw path groups like:

- `dataset_base_choice`
- `dataset_subpath`
- `default_traj_globs`
- `cloudmap_sat_path`
- `cloudmap_ivdl_path`

use references such as:

```toml
[pages.view_maps_network]
dataset_connector = "connectors/flight_dataframe.toml"
trajectory_connector = "connectors/flight_trajectory.toml"
allocation_connector = "connectors/routing_allocations.toml"
baseline_connector = "connectors/baseline_allocations.toml"
heatmap_connector = "connectors/cloudmaps.toml"
```

## Resolution Rules

Recommended precedence:

1. explicit query parameters
2. current session-state widget values
3. explicit page-level overrides in `app_settings.toml`
4. connector references in `app_settings.toml`
5. legacy raw path keys
6. code-level defaults

This keeps user interaction unchanged while allowing gradual migration.

## Backward Compatibility

This change should be introduced without breaking existing apps.

Required compatibility policy:

- keep legacy raw path keys working during phase 1
- allow pages to resolve either:
  - connector-based settings
  - or legacy inline path settings
- log a warning only when both are set and conflict

Recommended conflict rule:

- explicit connector reference wins over legacy inline defaults

## Impact on Apps-Pages

### `view_maps_network`

Primary beneficiary of the change.

Expected impact:

- replace repeated dataset/allocation/heatmap path settings with connector references
- resolve connectors into page defaults before widget creation
- keep existing widgets initially
- later optionally expose a connector selector/preset dropdown in the UI

### `view_maps`

Likely second beneficiary.

Expected impact:

- dataset discovery can be driven by a dataset connector rather than ad hoc path defaults

### Other apps-pages

Potential future adopters:

- `view_barycentric`
- `view_autoencoder_latenspace`
- other pages that currently depend on path-like defaults

## Impact on `PROJECT`

Impact: medium.

Reason:

- `PROJECT` currently exposes raw `app_settings.toml`
- once connector references are introduced, users will see indirection instead of concrete paths

Required GUI support in `PROJECT`:

- a read-only resolved preview of connector references
- a way to open the referenced connector file from `app_settings.toml`
- ideally, a dedicated `CONNECTORS` panel or tab in addition to `APP-SETTINGS`

Without this, debugging becomes harder.

## Impact on `PIPELINE`

Impact: low in phase 1.

Reason:

- `PIPELINE` mainly uses `lab_steps.toml`
- its current `app_settings.toml` usage is mostly about cluster/args settings, not page-specific path presets

Therefore:

- no immediate connector UI is required in `PIPELINE`
- no forced step-model change is required in phase 1

Possible phase 2 enhancement:

- allow steps to reference named connectors such as:
  - `input_connector`
  - `output_connector`

This should be optional and deferred.

## Recommended Implementation Plan

### Phase 1: Core Connector Infrastructure

Implement:

- `Connector` class
- TOML loader/parser
- connector reference resolver
- validation logic

Suggested code placement:

- `agi_env` or a small shared utility layer used by apps-pages

Deliverables:

- runtime `Connector` model
- `load_connector(path, app_settings_dir)`
- `resolve_connector_ref(ref, app_settings_dir)`

### Phase 2: Page Resolution Support

Integrate connector resolution into:

- `view_maps_network`
- optionally `view_maps`

Deliverables:

- connector-aware default resolution
- backward-compatible handling of legacy path settings

### Phase 3: GUI Support in `PROJECT`

Add:

- connector file discovery
- connector preview
- open/edit navigation from settings to connector files

Optional:

- a structured form editor for connectors

### Phase 4: Optional `PIPELINE` Integration

Only if needed later:

- step-level connector references
- connector-aware execution helpers

## Validation Requirements

Implementation should include tests for:

- connector file parsing
- invalid connector schema detection
- relative-path resolution from `app_settings.toml`
- precedence rules between connector refs and legacy raw keys
- `view_maps_network` using connector-based defaults
- `PROJECT` showing connector references cleanly

## Acceptance Criteria

The change is complete when:

- connectors can replace path groups in `app_settings.toml`
- existing apps still work without migration
- `view_maps_network` can load defaults from connector files
- `PROJECT` makes connector indirection understandable
- `PIPELINE` remains unaffected in phase 1
- connector definitions remain plain-text and git-friendly

## Final Recommendation

Proceed if the intent is:

- reusable logical data/artefact presets across pages and apps

Do not proceed if the intent is:

- storing serialized Python objects as persistent connector state

Best first target:

- implement connector support for apps-pages resolution
- keep GUI change minimal at first
- make `PROJECT` connector-aware early
- leave `PIPELINE` unchanged in phase 1
