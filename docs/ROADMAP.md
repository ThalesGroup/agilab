## AGILAB Roadmap

Status reviewed on 2026-10-11. The published root release is
[`2026.10.11`](https://github.com/ThalesGroup/agilab/releases/tag/v2026.10.11);
source changes and public publication remain separate checkpoints.

The baseline already includes the native React interface, Python view host,
first proof, run manifest, proof-pack/evidence capsule commands, release-decision
evidence, compatibility matrix automation, connector discovery/reporting,
notebook import/export, audience bridge MVPs, and two-app DAG operator controls.
Concrete worker loading remains dynamic through `agi-core`; import guards protect
that boundary.

| Area | Baseline and source status | Remaining qualification or product work |
| --- | --- | --- |
| Notebook | Editable GUI-to-notebook export and fresh-kernel round trips, including the 1,000-row macOS proof | Real Linux validation on a less powerful machine, larger inputs, and additional app scenarios |
| Multi-app DAG | Two-app artifact handoff, retry, partial rerun, durable state and WORKFLOW controls | Broader app coverage, placement and operator usability at larger graph sizes |
| Connectors | Catalog, resolution, probe plans, explicit health actions, adapter contracts and connector-aware views | Real endpoint IAM, network, quota and latency qualification in prepared environments |
| Audience bridges | Quarto, read-only MCP, Hugging Face, MLflow, VS Code, DuckDB, Airflow and Dagster command MVPs | Tool-specific execution and deployment qualification with the optional tools installed |
| Operator workbench | Qualified source MVP: seven profiles, an allowlisted palette and four snapshot panes; desktop/mobile navigation, reviewed switching and per-project layout evidence | Publication, actual palette install/scientific-run qualification, richer discovery/actions, cluster scenarios and smaller-machine measurements |

The nine [GitHub roadmap themes](https://github.com/ThalesGroup/agilab/issues?q=is%3Aissue%20is%3Aopen%20label%3Aroadmap)
and the central discussion thread are a voting and tracking index. An open theme
does not mean its delivered baseline is missing. Keep each theme's remaining
acceptance criteria aligned with this table and the detailed roadmap below.

The new workbench is not included in the published `agilab 2026.10.11` package
or the current hosted demonstration. Its install/run queue contract has backend
test evidence; the browser proof exercised navigation, review/cancellation and
project switching without installing or running scientific workloads.

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
5. Qualify and deepen the shipped audience bridges in leverage order: Quarto/R
   report export, read-only MCP evidence access, Hugging Face Docker Space export,
   MLflow handoff, VS Code/devcontainer onboarding, DuckDB/SQL, and Airflow/Dagster
   handoff. Do not treat a generated artifact as proof of a deployed service.
6. Stabilize the extension contracts across apps, pages, notebooks,
   connectors, reducers, evidence reports, and package splits.
7. Productize multi-app DAG, intent-first operator mode, observability, and MLOps
   handoff on top of the stable baseline.

Supporting roadmap documents:

- [Audience bridges](./source/roadmap/audience-bridges.md): Quarto/R,
  MCP, Hugging Face, MLflow, VS Code, DuckDB/SQL, and Airflow/Dagster bridge
  priority and boundaries.
- [UX improvement roadmap](./UX_ROADMAP.md): environment health, action
  feedback, settings provenance, heavy-page responsiveness, and intent-first
  workflow pages.
- [Detailed future work](./source/roadmap/agilab-future-work.md): delivered
  contracts, remaining acceptance criteria and GitHub theme links.
- [Release proof](./source/release-proof.rst): the published version and the
  precise boundary of its qualification.

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
