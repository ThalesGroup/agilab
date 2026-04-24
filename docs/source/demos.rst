Demos
=====

.. toctree::
   :hidden:

   demo_capture_script

Use this page to choose a public AGILAB demo route. It is a router, not a
quick-start guide.

Choose a demo
-------------

.. image:: https://img.shields.io/badge/agi--core-demo-1D4ED8?style=for-the-badge
   :target: https://thalesgroup.github.io/agilab/notebook-quickstart.html
   :alt: agi-core demo

.. image:: https://img.shields.io/badge/AGILAB-demo-0F766E?style=for-the-badge
   :target: https://huggingface.co/spaces/jpmorard/agilab
   :alt: AGILAB demo

What each route is for
----------------------

- **AGILAB demo**: self-serve public Hugging Face Spaces route for the AGILAB
  web UI. It opens the lightweight built-in ``flight_project`` path by default,
  so use it as the public first proof for project selection, execution, and
  analysis.
- **agi-core demo**: notebook-first runtime path. Use this if you want the
  smaller ``AgiEnv`` / ``AGI.run(...)`` surface before the web UI.
- **Quick start**: the safest truthful first proof of the full product path.
  Use :doc:`quick-start` if you want the recommended local run instead of a
  public demo.

Demo naming
-----------

Keep the two public AGILAB demo lanes separate:

- ``flight_project`` is the default hosted/newcomer demo. It is a lightweight
  data-generation path used to prove the UI and local execution flow quickly.
- ``uav_relay_queue_project`` is the UAV Relay Queue RL demo. It is the
  advanced full-tour scenario for ``PROJECT -> ORCHESTRATE -> PIPELINE ->
  ANALYSIS`` and should not be described as the default hosted app.

See also
--------

- :doc:`quick-start`
- :doc:`notebook-quickstart`
- :doc:`newcomer-guide`
- :doc:`compatibility-matrix`
