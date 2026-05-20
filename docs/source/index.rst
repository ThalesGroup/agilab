AGILab Documentation
=====================

AGILAB turns experimental AI/ML notebooks and scripts into executable,
portable, evidence-backed applications that can run locally or on distributed
workers. Workflows stay portable: export them back to runnable ``agi-core``
notebooks, keep reproducibility evidence, and hand off tracking evidence to
MLflow when that integration is enabled. The notebook export is an ``agi-core``
runtime handoff: you can continue to run the saved project and stage contract
with only the stable core runtime, without depending on the AGILAB UI or
distributed worker layer.

If you are new to AGILab, choose one route first:

- **See the UI now**: open :doc:`agilab-demo` for the public Hugging Face Space.
- **Prove it locally**: follow :doc:`quick-start` with the built-in
  ``flight_telemetry_project`` or start from a notebook through PROJECT.
  Default target: pass the flight first proof in 10 minutes.
- **Use the API/notebook**: follow :doc:`notebook-quickstart` for the smaller
  ``AgiEnv`` / ``AGI.run(...)`` surface.

The fastest adoption ladder is browser preview, one local first-proof lane,
evidence manifest, then expansion into package mode, external apps, or cluster
work.

If the local first proof fails, use :doc:`newcomer-troubleshooting` before
branching into cluster mode, external app repositories, or broader workflows.

For release-level evidence, use :doc:`release-proof`; it points to the
`latest public GitHub release
<https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.18>`__,
package proof, CI guardrails, and hosted demo status.

This documentation then expands into architecture, service mode, API
references, and example projects.

.. toctree::
   :maxdepth: 2
   :caption: Start

   Newcomer guide <newcomer-guide>
   Local first proof <quick-start>
   Release proof <release-proof>
   Evidence claims policy <evidence-claims-policy>
   Evidence taxonomy <evidence-taxonomy>
   First-failure recovery <newcomer-troubleshooting>
   Compatibility matrix <compatibility-matrix>

.. toctree::
   :maxdepth: 2
   :caption: Product

   Product overview <introduction>
   Capabilities <features>
   Data connectors <data-connectors>
   Proof capsule <proof-capsule>
   Public web demo <agilab-demo>
   Advanced proof pack <advanced-proof-pack>

.. toctree::
   :maxdepth: 2
   :caption: Notebooks and API

   Notebook quickstart with agi-core <notebook-quickstart>
   Advanced notebook routes <notebook-advanced>
   Python API reference <agilab>
   Framework API <framework-api>

.. toctree::
   :maxdepth: 2
   :caption: Build

   Architecture in 5 minutes <architecture-five-minutes>
   Product architecture <architecture>
   AGI Core architecture <agi-core-architecture>
   MLOps positioning <agilab-mlops-positioning>
   Learning workflows <learning-workflows>
   Project file structure <directory-structure>
   Agent workflows <agent-workflows>
   Contributor guide <contributor-guide>

.. toctree::
   :maxdepth: 2
   :caption: Web UI pages

   Landing page <agilab-help>
   PROJECT page <edit-help>
   ORCHESTRATE page <execute-help>
   WORKFLOW page <experiment-help>
   ANALYSIS page <explore-help>
   Page bundles <apps-pages>

.. toctree::
   :maxdepth: 2
   :caption: Operations

   Cluster setup <cluster>
   Distributed workers <distributed-workers>
   SSH keys for workers <key-generation>
   Service mode <service-mode>
   Service install paths <service_mode_and_paths>
   Service health schema <service-health-schema>
   Environment variables <environment>
   Troubleshooting <troubleshooting>
   FAQ <faq>

.. toctree::
   :maxdepth: 2
   :caption: Examples

   Demo chooser <demos>
   Execution playground <execution-playground>
   Industrial optimization examples <industrial-optimization-examples>
   Notebook migration example <notebook-migration-skforecast-meteo>
   MyCode project <mycode-project>
   Flight telemetry project <flight-telemetry-project>

.. toctree::
   :maxdepth: 2
   :caption: Reference

   Project and packages <agilab-github>
   Security and adoption <security-adoption>
   Package publishing policy <package-publishing-policy>
   Framework submodule contract <framework-submodule-contract>
   Module reference <modules>
   Strategic potential <strategic-potential>
   Licenses <license>

.. toctree::
   :maxdepth: 2
   :caption: Roadmap

   Roadmap <roadmap/index>

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
