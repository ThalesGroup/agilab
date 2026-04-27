.. _modules-index:

Module Reference
================

This chapter is the entry point for the public AGILab Python surfaces. It links
to the canonical package pages instead of mirroring their autodoc blocks in a
second parallel tree.

- ``agi_core`` currently exposes a deliberately thin top-level Python surface, so
  its architecture page is the authoritative reference.
- ``agi_env``, ``agi_gui``, ``agi_node``, ``agi-distributor``, and ``agilab``
  below are the canonical API pages for the main framework packages and entry
  points.

Canonical pages
---------------

- :doc:`agi-core-architecture` for the shared framework architecture and the
  role of ``agi_core``.
- :doc:`agi-env` for ``AgiEnv`` and the environment/configuration helpers.
- :doc:`agi-gui` for the Streamlit page helper package under
  ``src/agilab/lib/agi-gui``.
- :doc:`agi-node` for ``BaseWorker`` and the concrete worker implementations.
- :doc:`agi-distributor` for the orchestration layer implemented under
  ``agi_cluster.agi_distributor``.
- :doc:`agilab` for the top-level package entry points, including ``lab_run``.
