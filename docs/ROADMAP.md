## AGILAB Roadmap

Delivery status reconciled on 2026-11-14 against source checkpoint
`f1710f981b57a079c48fdac6898e4c9dc8f9e505`. The published root release remains
[`2026.11.02`](https://github.com/ThalesGroup/agilab/releases/tag/v2026.11.02)
(PyPI `2026.11.2`), from source commit
`d13af54e2d41fbf70bae7cddf0fb270388dceaaf`. Its UI profile pins
`agi-apps`, `agi-pages`, `agi-gui` and `agi-web` at `2026.11.02`;
builtin app packages retain their own version constraints. Source availability,
package publication and qualification of a particular environment are separate.

The source checkpoint adds [installed SDK origin and local worker-root fixes](https://github.com/ThalesGroup/agilab/pull/1237),
[durable metadata and local observability adapters](https://github.com/ThalesGroup/agilab/pull/1236),
and [offline map rendering and saved-data restoration](https://github.com/ThalesGroup/agilab/pull/1238).
[App-owned evaluation, serving handoffs and optional Sigstore verification](https://github.com/ThalesGroup/agilab/pull/1240)
are also available in merged source. These additions are absent from the
November 2 packages. Public documentation
is independently maintained in this checkout's `docs/source`; its deployment
has a separate lifecycle.

| Area | Available baseline or bounded qualification | Remaining acceptance |
| --- | --- | --- |
| Notebook | Editable export, fresh-kernel execution and reimport; deployed local worker runs now qualified in the two cohorts below | More apps and larger scientific inputs, current candidate SDK qualification on Linux, and two-host execution |
| Multi-app DAG | Two-app artifact handoff, retry, partial rerun, durable state and WORKFLOW controls | More apps, larger graphs, placement and operator usability |
| Connectors | Catalog, resolution, probe plans, explicit health actions, adapter contracts and connector-aware views | Prepared live endpoints, identity/access policy, network behavior, quotas and latency |
| Audience bridges | Actual local R, Quarto, read-only MCP stdio, MLflow SQLite, DuckDB, Airflow and Dagster tool execution | Hosted services, additional platforms and deeper community-native integration |
| Operator workbench | Published seven-profile MVP; the published Linux cohort completed one reviewed worker deployment and one scientific run, with two rerenders causing no extra operations | Overall environment health, richer discovery/actions, hosted behavior, cluster scenarios and smaller-machine responsiveness |
| Analytical views | Current source browser cohort passed offline maps, provider selection, 24 unique directed allocation links and saved-data cold starts in both 3D views | Complete wheel-only deployment, additional browsers/hardware and measured scaling |
| Model promotion and attestation | Source app-owned evaluation, evidence-bound promotion/serving handoff verification and an opt-in Sigstore adapter | Prepared serving deployments and a positive real user-capsule/SLSA attestation; official fixtures qualify the adapter only |
| Evidence and observability | Source SQLite run/artifact/validation queries, durable JSONL agent events and opt-in loopback OpenTelemetry/OpenLineage adapters with qualified local optional-dependency composition | External collector deployment, remote runtime acceptance, broader runtime correlation and richer scientific metadata |

### What the qualification covers

| Cohort | Observed result | Boundary |
| --- | --- | --- |
| Installed candidate SDK on macOS ARM, Python 3.13.14 | Normal packaged clone and worker deployment, local mode 0, editable notebook export, actual installed notebook CLI execution, native verification and four-stage reimport | Three candidate SDK wheels from the reviewed source; other components are November 2 packages. Host-local qualification, not a new PyPI release or two-host run |
| Published packages on Linux ARM, Python 3.13.18 | Local mode 0, fresh-kernel notebook execution and verification, four-stage authorship/reimport, and actual workbench deployment/run | Both notebook cohorts used 10 synthetic rows for two aircraft. Semantic and byte equality were checked within each cohort's own run; Linux overall health still reports the absent MLflow dependency |
| Current candidate SDK on Linux | Normal fresh-environment clone, export and reimport | Full scientific run pending capacity and tracking-backend prerequisites |
| Premounted native filesystem share on macOS | Official share-consumer scheduler-read and mounted-writeback checks passed over WebDAV through an existing strict SSH tunnel | Two-host SDK compute, degraded-network and team-operation qualification remain open |
| Current analytical source on macOS ARM with Chromium 159 and software rendering | Four browser gates passed; both 3D cold starts retained a 19,208-row saved dataset, and the offline iframe protection remained effective | Candidate runtime plus exact source page providers, not a complete wheel-only or hardware-performance qualification |

The browser cohort retains the 120,000-point heatmap limit, 600 points per
trajectory and 1,200 points per selected node. These bounded runs establish
neither scientific throughput nor optimization gains. Additional workload,
platform, security and production acceptance criteria remain open.

Local [R summary integrity](https://github.com/ThalesGroup/agilab/pull/1233),
[source-linked repository exploration](https://github.com/ThalesGroup/agilab/pull/1234)
and [compatible environment reuse](https://github.com/ThalesGroup/agilab/pull/1235)
also have bounded source evidence. Repository exploration remains local;
environment reuse keeps preparation explicit and preserves the donor's
installed applications. Hosted knowledge services and wider deployment reuse
still require their own qualification.

The nine [GitHub roadmap themes](https://github.com/ThalesGroup/agilab/issues?q=is%3Aissue%20is%3Aopen%20label%3Aroadmap)
remain open for their broader acceptance criteria. A completed local cohort
does not close a theme. The older workbench browser proof covered navigation,
review/cancellation and switching; the newer Linux cohort adds actual scientific
execution without establishing hosted or cluster behavior.

Recommended near-term order:

1. Preserve release trust: keep package scope, release proof, docs deployment,
   badges and hosted evidence tied to their actual published revisions.
2. Extend the qualified notebook and workbench routes to additional apps,
   larger inputs and the current Linux SDK candidate; close environment-health
   prerequisites separately.
3. Extend the qualified premounted share-consumer path to actual two-host SDK
   compute; qualify degraded-network and team-operation behavior separately.
4. Qualify external telemetry collectors and prepared service endpoints; retain
   the qualified local optional composition and explicit identity, network and
   deployment boundaries.
5. Deepen the qualified audience bridges and scale the existing DAG, analysis
   and evidence contracts.

Supporting roadmap documents:

- [Audience bridges](./source/roadmap/audience-bridges.md): local tool results,
  adoption priorities and remaining service/platform qualification.
- [UX improvement roadmap](./UX_ROADMAP.md): health, action feedback,
  responsiveness and workflow usability.
- [Detailed future work](./source/roadmap/agilab-future-work.md): delivered
  contracts, remaining acceptance criteria and GitHub theme links.
- [Release proof](./source/release-proof.rst): published artifacts and the
  precise boundary of their qualification.

Longer-horizon items:

- Migrate to uv 1.x after a stable 1.x release exists; this is a conditional
  migration, not a failed current action.
- Broaden run diff and counterfactual analysis beyond evidence-only comparisons.
- Measure realtime analytical and geospatial scaling on declared workloads and
  hardware before making performance claims.
- Extend local source-linked exploration into a controlled knowledge service
  while retaining versioned documentation as the source of truth.
- Extend compatible environment reuse to more worker and page deployments
  without weakening environment identity or isolation.
