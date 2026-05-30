Extension Contracts
===================

AGILAB is easier to maintain when every extension follows a small contract
instead of adding page-specific or app-specific glue. This page is the public
contract kit for new apps, page bundles, notebook bridges, proof evidence,
connectors, and shared-core changes.

The machine-readable source is
:download:`data/extension_contracts.toml <data/extension_contracts.toml>`.
Maintainers can inspect it through the maintenance dashboard:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/maintenance_dashboard.py --json
   ./dev maintenance

Contract shape
--------------

Every extension type declares:

- **metadata**: files, manifests, labels, or registration points that make the
  extension discoverable;
- **evidence**: reports, run manifests, hashes, UI robot output, or verifier
  results that prove the extension boundary;
- **guardrails**: tests or tools that fail before drift reaches release time;
- **maturity labels**: whether the surface is a live product path, local proof,
  contract proof, operator-triggered live check, or roadmap boundary.

The standard maturity labels are **Live product path**, **Local proof**,
**Contract proof**, **Operator-triggered live check**, and **Roadmap boundary**.

Extension types
---------------

.. list-table::
   :header-rows: 1
   :widths: 20 36 24 20

   * - Type
     - Maintenance rule
     - Primary guardrail
     - Typical evidence
   * - ``app``
     - Public apps must be installable, runnable, documented, and
       evidence-producing.
     - ``tools/app_contract_matrix.py``
     - ``run_manifest.json``, reducer summary, app artifacts.
   * - ``page_bundle``
     - Pages stay app-agnostic, dependency-isolated, and discoverable through
       provider/catalog metadata.
     - ``tools/app_contract_matrix.py``
     - UI robot, static render, apps-pages docs row.
   * - ``notebook_bridge``
     - Notebook import/export must preserve stage order, runtime hints, role
       metadata, and artifact references.
     - Notebook preflight and round-trip reports.
     - Import preview, ``lab_stages.toml``, supervisor notebook export.
   * - ``proof_evidence``
     - Evidence surfaces must have schemas, producer commands, verifier
       behavior, and explicit claim boundaries.
     - Evidence claims policy and release proof checks.
     - Plain JSON, ``.agipack``, verifier report, promotion dossier.
   * - ``connector``
     - Connectors reference data systems by ID and credential reference, not by
       embedded secrets or hidden local paths.
     - Connector facility, resolution, and adapter reports.
     - Local proof, contract proof, emulator proof, or live probe result.
   * - ``shared_core``
     - Shared runtime or installer changes need explicit blast-radius analysis
       and focused regression evidence before merge.
     - ``tools/impact_validate.py`` and shared-core typing.
     - Impact report, focused tests, docs when public behavior changes.

Adoption rule
-------------

Before adding a new feature, choose its extension type and maturity label. If a
feature does not fit any row, add or revise the contract first. This keeps
AGILAB maintainable as the number of apps, page bundles, connectors, and proof
surfaces grows.

Release rule
------------

Do not promote an extension as public-ready until its metadata, evidence,
docs, and guardrails are all present. For split packages, the package split and
release plan remain the source of truth for what is published.
