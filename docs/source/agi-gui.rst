agi-gui API
===========

``agi_gui`` provides the Streamlit-facing page helper package for AGILAB. It
lives under ``src/agilab/lib/agi-gui`` so UI dependencies stay separate from
the core runtime packages used by worker-only environments.

Use ``agi-gui`` when building or running AGILAB pages, page bundles, or
local web UI sessions. Use ``agi-env`` directly for headless worker/runtime
contexts that do not render Streamlit UI.

Reference
---------

.. automodule:: agi_gui
   :members:
   :show-inheritance:
