## AGILAB Roadmap

- [UX improvement roadmap](./UX_ROADMAP.md): concrete backlog for environment health, action feedback, settings provenance, heavy-page responsiveness, and intent-first workflow pages.
- Migrate to uv 1.0 once available.
- Rework documentation published on GitHub.
- Add run diff / counterfactual analysis to compare baseline and candidate runs
  across inputs, topology, decisions, artefacts, and KPI deltas.
- Add realtime analytical and geospatial views with Plotly.js/WebGL first,
  deck.gl for dense map/network overlays, and Three.js only for specialized 3D
  mission views.
- Promote current distributed work-plan execution into a first-class
  map/reduce contract with explicit reducers, merge semantics, and aggregation
  artefacts.
- Add an internal DeepWiki/Open-style repository knowledge layer for codebase
  exploration and onboarding, while keeping versioned docs as the source of
  truth.
- Explore shared virtualenv reuse for workers and apps-pages via symlink +
  dependency-hash checks: reuse when Python version and lock/deps match; on
  mismatch or failure, create a fresh env and repoint the symlink to reduce
  redundant venvs without sacrificing isolation.
