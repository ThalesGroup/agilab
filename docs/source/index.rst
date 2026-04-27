AGILab Documentation
=====================

If you are new to AGILab, choose one route first:

- **See the UI now**: open :doc:`agilab-demo` for the public Hugging Face Space.
- **Prove it locally**: follow :doc:`quick-start` with the built-in
  ``flight_project``. Target: pass the first proof in 10 minutes.
- **Use the API/notebook**: follow :doc:`notebook-quickstart` for the smaller
  ``AgiEnv`` / ``AGI.run(...)`` surface.

The fastest adoption ladder is browser preview, local first proof, evidence
manifest, then expansion into notebooks, package mode, private apps, or cluster
work.

If the local first proof fails, use :doc:`newcomer-troubleshooting` before
branching into cluster mode, private app repositories, or broader workflows.

For release-level evidence, inspect the `latest public GitHub release
<https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.27-3>`__.

This documentation then expands into architecture, service mode, API
references, and example projects.

.. toctree::
   :maxdepth: 2
   :caption: Start

   newcomer-guide
   quick-start
   newcomer-troubleshooting
   compatibility-matrix

.. toctree::
   :maxdepth: 2
   :caption: Use

   introduction
   features
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

   About AGILab <agilab-help>
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
   notebook-migration-skforecast-meteo
   mycode-project

   flight-project

.. toctree::
   :maxdepth: 2
   :caption: Reference

   agilab-github

.. toctree::
   :maxdepth: 2
   :caption: Roadmap

   roadmap/index

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
