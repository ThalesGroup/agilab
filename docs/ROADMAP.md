## AGILAB Roadmap

Current code baseline already includes the first proof, run manifest,
proof-pack/evidence capsule commands, release-decision evidence, compatibility
matrix automation, connector discovery/reporting, notebook import/export
contracts, and the first global-DAG/operator evidence paths.

Recommended near-term order:

1. Keep release trust aligned: PyPI, GitHub release proof, Hugging Face, docs
   mirror, badges, and release-proof evidence must point at the same shipped
   state.
2. Harden first-run UX and notebook parity: keep the local first proof,
   notebook import, notebook export, and analysis handoff predictable before
   broadening adoption paths.
3. Finish diagnostics, security, and team-readiness hardening: classified
   install/run/share/service failures, explicit security boundaries, and
   cluster/share validation.
4. Make evidence and connector output easier to consume outside the UI:
   proof-pack, release-decision, run-diff, connector provenance, and artifact
   evidence should remain portable and reviewable.
5. Stabilize the extension contracts across apps, pages, notebooks,
   connectors, reducers, evidence reports, and package splits.
6. Productize global DAG, intent-first operator mode, observability, and MLOps
   handoff on top of the stable baseline.

Supporting roadmap documents:

- [UX improvement roadmap](./UX_ROADMAP.md): environment health, action
  feedback, settings provenance, heavy-page responsiveness, and intent-first
  workflow pages.

Longer-horizon items:

- Migrate to uv 1.0 once available.
- Continue tightening the public documentation flow on GitHub.
- Productize run diff / counterfactual analysis beyond the current
  evidence-only contract, including broader baseline/candidate comparisons
  across inputs, topology, decisions, artefacts, and KPI deltas.
- Harden realtime analytical and geospatial views with Plotly.js/WebGL first,
  deck.gl for dense map/network overlays, and Three.js only for specialized 3D
  mission views.
- Connect the current static repository-knowledge report to an internal
  DeepWiki/Open-style exploration layer while keeping versioned docs as the
  source of truth.
- Explore shared virtualenv reuse for workers and apps-pages via symlink +
  dependency-hash checks: reuse when Python version and lock/deps match; on
  mismatch or failure, create a fresh env and repoint the symlink to reduce
  redundant venvs without sacrificing isolation.
