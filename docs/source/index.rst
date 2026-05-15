AGILab Documentation
=====================

AGILAB's core value is controlled AI/ML experimentation without lock-in:
build workflows in the UI or API, keep reproducibility evidence, and export
the work back to runnable notebooks when you need to reuse it outside AGILAB.

If you are new to AGILab, choose one route first:

- **See the UI now**: open :doc:`agilab-demo` for the public Hugging Face Space.
- **Prove it locally**: follow :doc:`quick-start` with the built-in
  ``flight_telemetry_project`` or start from your own notebook through the
  ABOUT wizard. Default target: pass the flight first proof in 10 minutes.
- **Use the API/notebook**: follow :doc:`notebook-quickstart` for the smaller
  ``AgiEnv`` / ``AGI.run(...)`` surface.

The fastest adoption ladder is browser preview, one local first-proof lane,
evidence manifest, then expansion into package mode, external apps, or cluster
work.

If the local first proof fails, use :doc:`newcomer-troubleshooting` before
branching into cluster mode, external app repositories, or broader workflows.

For release-level evidence, use :doc:`release-proof`; it points to the
`latest public GitHub release
<https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.14>`__,
package proof, CI guardrails, and hosted demo status.

This documentation then expands into architecture, service mode, API
references, and example projects.

.. toctree::
   :maxdepth: 2
   :caption: Start

   newcomer-guide
   quick-start
   release-proof
   newcomer-troubleshooting
   contributor-guide
   architecture-five-minutes
   compatibility-matrix

.. toctree::
   :maxdepth: 2
   :caption: Use

   introduction
   features
   data-connectors
   AGILAB Demo <agilab-demo>
   Advanced Proof Pack <advanced-proof-pack>
   notebook-quickstart
   notebook-advanced
   agilab

.. toctree::
   :maxdepth: 2
   :caption: Build

   architecture
   agi-core-architecture
   agilab-mlops-positioning
   learning-workflows
   framework-api
   framework-submodule-contract
   cluster
   modules
   environment
   agent-workflows
   faq
   directory-structure
   troubleshooting
   license

.. toctree::
   :maxdepth: 2
   :caption: Pages

   Main Page <agilab-help>
   edit-help
   execute-help
   experiment-help
   explore-help

.. toctree::
   :maxdepth: 2
   :caption: Service and Operations

   service-mode
   Service install paths <service_mode_and_paths>
   service-health-schema

.. toctree::
   :maxdepth: 2
   :caption: Examples

   demos
   execution-playground
   industrial-optimization-examples
   notebook-migration-skforecast-meteo
   mycode-project

   flight-telemetry-project

.. toctree::
   :maxdepth: 2
   :caption: Reference

   agilab-github
   package-publishing-policy
   beta-readiness
   strategic-potential

.. toctree::
   :maxdepth: 2
   :caption: Roadmap

   roadmap/index

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
