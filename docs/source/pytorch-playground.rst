PyTorch Playground
==================

``pytorch_playground_project`` is AGILAB's PyTorch-native visual learning app.
It keeps the immediate decision-boundary feedback people expect from classic
neural-network playgrounds, then adds the engineering pieces those playgrounds
usually do not own: replayable configuration, deterministic evidence, exported
artifacts, and code handoff.

Positioning
-----------

TensorFlow Playground remains the reference for a pure browser-first beginner
lesson. AGILAB's PyTorch Playground is stronger when the lesson must become a
reproducible PyTorch experiment that can be replayed, inspected, archived, and
handed to another engineer.

Use it when you need:

- live play/pause boundary learning and a deterministic ``Train / refresh``
  evidence path in the same UI, with ``Run instant demo`` as the one-click
  boundary-first route;
- a boundary-first panel that uses a WebGL-first ``agi-web`` island with
  Canvas2D fallback for fluid decision-surface interaction, local epoch
  scrubbing, play/pause replay, and hover probability readouts, plus a
  confidence HUD, clickable replay timeline, keyboard scrubbing, and glowing
  uncertainty contour while keeping Plotly detail tabs for evidence inspection;
- preset lessons for circles, XOR feature engineering, spiral capacity, and a
  gaussian sanity check;
- boundary snapshots, training curves, hidden-neuron activation maps, network
  diagnostics, and optional 3D loss terrain;
- a shareable replay token, evidence ZIP, manifest, and generated plain
  PyTorch or PyTorch Lightning scripts.

What It Adds Over A Classic Playground
--------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 28 34 38

   * - Capability
     - Classic browser playground
     - AGILAB PyTorch Playground
   * - Teaching feedback
     - Immediate visual boundary changes
     - Immediate visual boundary changes plus bounded live play/pause ticks
   * - Framework handoff
     - Mostly educational visualization
     - Real PyTorch configuration and generated PyTorch/Lightning code
   * - Replay
     - Manual knob recreation
     - URL replay token and persisted ORCHESTRATE arguments
   * - Evidence
     - Screenshot or manual notes
     - Manifest, CSV artifacts, boundary snapshots, model diagnostics, and ZIP
   * - Engineering route
     - Browser-only lesson
     - Local Streamlit, hosted Hugging Face surface, and AGILAB app execution

One-Minute Demo Route
---------------------

.. code-block:: bash

   agilab app surface pytorch_playground_project --list
   agilab app surface pytorch_playground_project --ui streamlit

Then:

1. Keep ``Instant wow: clean circles`` and press ``Run instant demo``.
2. Scrub or play the boundary replay, hover the surface, then try the XOR
   lesson card.
3. Switch ``Training mode`` to ``Live play/pause`` and use ``Step`` or
   ``Play`` to watch the boundary form.
4. Remove then restore ``x1_x2`` in ``Features`` to show why nonlinear features
   matter.
5. Download the evidence pack and copy the replay token from ``Evidence pack``.

Hosted Route
------------

Use the hosted surface when you want the browser-first demo:

Public Space page: https://huggingface.co/spaces/jpmorard/agilab

.. code-block:: bash

   agilab app surface pytorch_playground_project --ui hf

The shortcut is equivalent:

.. code-block:: bash

   agilab pytorch-playground --backend hf

Scope
-----

This app is an educational and engineering-prototype playground. It is not a
model registry, serving stack, or production trainer. Its value is that the
visual lesson can become a reproducible AGILAB app run with inspectable
artifacts.

See also:

- :doc:`public-app-catalog` for the app package status.
- :doc:`apps-pages` for the app-owned UI surface contract.
- :doc:`quick-start` for the local first-proof route.
