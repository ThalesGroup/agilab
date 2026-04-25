## AGILAB Roadmap

Recommended near-term order:

1. Run manifest + evidence bundle
2. Promotion / release decision workflow
3. First-proof wizard in product
4. Compatibility matrix automation
5. Connector registry hardening
6. Reduce contract adoption for distributed aggregation
7. Intent-first operator mode

Supporting roadmap documents:

- [UX improvement roadmap](./UX_ROADMAP.md): environment health, action
  feedback, settings provenance, heavy-page responsiveness, and intent-first
  workflow pages.

Longer-horizon items:

- Migrate to uv 1.0 once available.
- Rework documentation published on GitHub.
- Add run diff / counterfactual analysis to compare baseline and candidate runs
  across inputs, topology, decisions, artefacts, and KPI deltas.
- Add realtime analytical and geospatial views with Plotly.js/WebGL first,
  deck.gl for dense map/network overlays, and Three.js only for specialized 3D
  mission views.
- Add an internal DeepWiki/Open-style repository knowledge layer for codebase
  exploration and onboarding, while keeping versioned docs as the source of
  truth.
- Explore shared virtualenv reuse for workers and apps-pages via symlink +
  dependency-hash checks: reuse when Python version and lock/deps match; on
  mismatch or failure, create a fresh env and repoint the symlink to reduce
  redundant venvs without sacrificing isolation.
