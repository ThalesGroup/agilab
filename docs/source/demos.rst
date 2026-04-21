Demos
=====

.. toctree::
   :hidden:

   demo_capture_script

Use this page as the public entry point for AGILAB demos you can review before
installing anything.

Start Here
----------

If you want a pre-install UI demo, use this page first.

You do not need to install AGILAB to open these decks.

If you are new to AGILAB, start with the `flight_project` first-proof deck:

- :download:`AGILAB first proof slideshow <AGILAB_Flight_First_Proof_Slides.pptx>`

If you want the full four-page tour, use the `UAV Relay Queue` deck:

- :download:`AGILAB full tour slideshow <AGILAB_UAV_Full_Tour_Slides.pptx>`

Which Demo To Watch
-------------------

- ``flight_project``: best first local proof of the AGILAB workflow
  (``PROJECT -> ORCHESTRATE -> ANALYSIS``).
- ``UAV Relay Queue`` (install id ``uav_relay_queue_project``): best public
  full-tour demo when you want the main four-page story
  (``PROJECT -> ORCHESTRATE -> PIPELINE -> ANALYSIS``) ending on queue evidence.

Core Tour
---------

.. figure:: _static/page-shots/core-pages-overview.png
   :alt: Overview screenshot montage of the PROJECT, ORCHESTRATE, PIPELINE, and ANALYSIS Streamlit pages.
   :align: center
   :class: diagram-panel diagram-wide

   The stable four-page flow used as the reference story for the main AGILAB intro.

What The Reels Show
-------------------

The two public demos have different scopes:

``flight_project`` is the newcomer proof:

- ``PROJECT`` selects one built-in app and keeps its context visible.
- ``ORCHESTRATE`` packages and runs the local path.
- Fresh output files under ``~/log/execute/flight/`` make the first proof visible.
- ``ANALYSIS`` ends on a visible result instead of raw infrastructure logs.

``UAV Relay Queue`` is the full four-page public tour:

- ``PROJECT`` selects the app and routing scenario.
- ``ORCHESTRATE`` runs the queue experiment through one packaged path.
- ``PIPELINE`` keeps the experiment replayable as explicit steps and artifacts.
- ``ANALYSIS`` ends on queue and topology evidence.

The difference is the role:

- ``flight_project`` is the safest first proof.
- ``UAV Relay Queue`` is the strongest README/social/demo tour.
- The compatibility matrix records those two paths separately, because they do
  not carry the same proof level.

See Also
--------

- :doc:`agilab-help` for the core page tour.
- :doc:`apps-pages` for the page bundles used from ``ANALYSIS``.
- :download:`AGILAB first proof slideshow <AGILAB_Flight_First_Proof_Slides.pptx>`
- :download:`AGILAB full tour slideshow <AGILAB_UAV_Full_Tour_Slides.pptx>`
- `Video tutorial and slideshow guide in the repository <https://github.com/ThalesGroup/agilab/blob/main/docs/source/demo_capture_script.md>`_
