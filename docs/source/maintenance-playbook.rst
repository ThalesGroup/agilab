Maintenance Playbook
====================

This playbook turns long-term AGILAB maintenance into a repeatable workflow.
It complements the roadmap: the roadmap says what to build next, while this
page says how to keep the workbench coherent as it grows.

Maintenance dashboard
---------------------

Run the dashboard before major merges, release candidates, or broad feature
work:

.. code-block:: bash

   ./dev maintenance
   uv --preview-features extra-build-dependencies run python tools/maintenance_dashboard.py --json

The dashboard is intentionally local-first. It reports:

- extension contract kit health;
- architecture decision records;
- docs mirror drift and mirror-stamp validity;
- built-in app, package, reducer, and public catalog contract health;
- package split integrity;
- skip-existing PyPI release-plan behavior;
- Evidence Core and proof-capsule documentation;
- maturity labels for live paths, local proofs, contract proofs, live checks,
  and roadmap boundaries;
- shared-core guardrails;
- generated artifact hygiene;
- TODO/FIXME hotspots;
- global coverage badge signal.

The dashboard does not replace targeted tests. It tells maintainers where drift
is likely before they choose the narrower validation command.

Maintenance sequence
--------------------

Use this order for non-trivial changes:

1. Classify the change as app, page bundle, notebook bridge, proof evidence,
   connector, shared core, docs, release, or packaging.
2. Run ``tools/impact_validate.py`` or ``./dev impact`` to identify required
   checks.
3. If the change adds or modifies an extension, update
   :doc:`extension-contracts` before adding more glue.
4. If the change changes an architectural rule, add or update an ADR under
   :doc:`adr/index`.
5. Run the narrow tests first.
6. Run ``./dev maintenance`` to catch docs, package, evidence, and guardrail
   drift.
7. Run release guards only when the change is release-facing.

Shared-core discipline
----------------------

Shared core includes runtime, installer, worker, cluster, and generic helpers.
Treat it differently from app-local code:

- require a blast-radius note before editing;
- prefer app-local fixes when the issue is app-local;
- run focused shared-core tests and typing when shared code changes;
- update docs when the public behavior changes;
- keep singleton, path, filesystem, and environment behavior deterministic.

Feature growth discipline
-------------------------

AGILAB should grow by contracts, not by one-off pages:

- new apps must be installable, runnable, documented, and evidence-producing;
- new page bundles must remain app-agnostic and dependency-isolated;
- new notebook routes must preserve import/export provenance;
- new proof reports must have schemas and explicit claim boundaries;
- new connectors must distinguish local proof, contract proof, emulator proof,
  and live checks;
- roadmap work must stay labeled as roadmap until implementation and release
  proof exist.

Release friction discipline
---------------------------

Split packages should not force unnecessary PyPI operations. The release plan
supports skip-existing behavior so packages whose wheel and source
distribution already exist can be omitted from build, upload, provenance, and
retention steps. Keep that behavior guarded because it avoids noisy cleanup and
reduces release risk.

Bottom line
-----------

Long-term maintenance depends on a small number of stable patterns:
extension contracts, Evidence Core, ADRs, shared-core gates, package split
truth, and local-first dashboards. Add features only when they fit those
patterns or when the pattern is deliberately updated first.
