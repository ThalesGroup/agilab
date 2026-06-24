Contributor Guide
=================

This page is for people changing AGILAB itself. If you only want to try the
product, start with :doc:`quick-start` instead.

Contributor goal
----------------

A good first pull request shows three things:

1. You can reproduce the public first proof.
2. Your pull request has one clear scope.
3. The validation you ran matches that scope.

Baseline setup
--------------

Run this once from a clean source checkout:

.. code-block:: bash

   git clone https://github.com/ThalesGroup/agilab.git
   cd agilab
   git config core.hooksPath .githooks
   uv --preview-features extra-build-dependencies sync --group dev
   uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py

If the proof fails, do not branch into clusters, private app repositories, or
large refactors yet. Use :doc:`newcomer-troubleshooting` first, or open a
GitHub issue with ``[CONTRIBUTOR]`` in the title and include the command plus
the first failing log lines.

Choose one lane
---------------

Before editing, pick the closest lane:

.. list-table::
   :header-rows: 1

   * - Lane
     - Good first scope
     - First validation
   * - Docs only
     - README, CONTRIBUTING, docs text, screenshots, links
     - ``git diff --check`` plus docs mirror checks if ``docs/source`` changes
   * - App or example
     - Built-in app, example README, app args, analysis view
     - Targeted app/page ``pytest`` or the app smoke test
   * - UI helper
     - Streamlit page state, sidebar/header, workflow/orchestrate helper
     - Targeted root ``pytest`` for the touched helper
   * - Workflow or release tooling
     - GitHub workflows, badges, release proof, package policy
     - Matching ``tools/workflow_parity.py --profile <name>``
   * - Shared core
     - ``src/agilab/core/*``, installer/build/deploy, generic runtime helpers
     - Ask for maintainer approval first, then run the focused core regression plan

Prefer docs, app-local, or UI-helper changes for a first pull request. Shared
core has the highest blast radius because it can affect installation, worker
packaging, cluster execution, and packaged public examples.

Validation map
--------------

Use the smallest command that proves your change:

.. list-table::
   :header-rows: 1

   * - Change type
     - Preferred local check
   * - Root docs only
     - ``git diff --check``
   * - Sphinx docs source
     - ``uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py --verify-stamp`` after maintainer sync
   * - Workflow parity
     - ``uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile <name>``
   * - Skill catalog
     - ``uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile skills``
   * - Badge or coverage tooling
     - ``uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile badges``
   * - Shared-core typing
     - ``uv --preview-features extra-build-dependencies run --with mypy python tools/shared_core_strict_typing.py``

Run broader test suites only when the touched area needs them. Do not trigger
GitHub Actions when the same failure can be reproduced locally.

Documentation quality bar
-------------------------

Treat public docs as product surface. Before opening a docs pull request,
check:

- **One reader, one next action**: name the intended reader, then make the next
  command, page, or proof artifact obvious. Avoid pages that explain many
  routes without telling the reader which route to start with.
- **Executable commands**: use copy-pasteable commands with the current
  ``uv --preview-features extra-build-dependencies`` entrypoints. If a command
  is source-checkout-only, packaged-only, or maintainer-only, label it that way.
- **Evidence over claims**: link claims about readiness, release status, demos,
  or reproducibility to the relevant manifest, release proof, robot evidence,
  or compatibility page. Do not describe roadmap work as shipped behavior.
- **Public boundary**: keep public docs free of private app names, internal
  competitive positioning, local-only paths, and unsupported production-safety
  claims. When AGILAB needs MLflow, Kubeflow, Airflow, SageMaker, or an internal
  platform for production responsibilities, say so directly.
- **Source/mirror parity**: contributors can edit public docs in their pull
  request. Maintainers keep the canonical ``../thales_agilab/docs/source`` tree
  and this repository's ``docs/source`` mirror aligned, verify the mirror stamp,
  and build the page when layout or links matter. Never hand-edit
  ``docs/html``.
- **Screenshots and diagrams**: update source screenshots, SVG diagrams,
  captions, alt text, and references together. Inspect the rendered page so old
  UI labels or clipped diagram text cannot survive a source-only edit.
- **Generated files**: if a docs change alters public commands, pages, schemas,
  apps, or evidence artifacts, note it in the pull request so maintainers can
  refresh generated files.

Pull request evidence
---------------------

Use one short evidence block in every pull request:

.. code-block:: text

   Scope:
   Validation:
   Risk area: docs | app | UI | workflow | shared core | security | dependency
   Touched areas: public docs | dependencies | security | release tooling | generated files | shared core | none
   Generated artifacts updated: yes/no

If none of the touched areas apply, write ``none``. Those areas need more
careful review than an app-local or docs-only change.

Review expectations
-------------------

- Pull requests need maintainer review before merge.
- Shared core, release tooling, security-sensitive, dependency, and packaging
  changes require review from an owner of that area.
- ``main``, release tags, and publication workflows are maintainer-owned.
- By submitting a pull request, you certify the Developer Certificate of Origin
  1.1 for your contribution. A separate CLA is not required for normal
  BSD-3-Clause contributions unless maintainers explicitly request one for a
  specific corporate or large-code contribution.

Reference
---------

The complete repository policy is in the root ``CONTRIBUTING.md`` file. Agent
and IDE runbooks live in ``AGENTS.md`` and :doc:`agent-workflows`.
