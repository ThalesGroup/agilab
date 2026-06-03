---
schema: agilab.maintenance_memory.v1
source: src/agilab/lib/agi-app-pytorch-playground/src/agi_app_pytorch_playground/project/pytorch_playground_project/src/pytorch_playground/playground_ui.py
source_sha256: 3937e5a33aa5003e5e4b0894845d7bd7276c1732a15c181e49fd24a1de95ae1f
title: PyTorch Playground package mirror parity
verified_commit: 7f25170446277e5a6fc1fc816a0ff7b1d5466e74
---

# PyTorch Playground package mirror parity

This file is the packaged `agi-app-pytorch-playground` payload mirror of the
built-in PyTorch Playground source. Do not edit it as an independent UI fork.

Hidden invariant: visible app behavior, reuse handoff labels, and generated
snippet rendering must stay aligned with
`src/agilab/apps/builtin/pytorch_playground_project/src/pytorch_playground/playground_ui.py`.

Regression expectation: `test/test_pytorch_playground_app.py` must pass because
it compares the built-in source payload and packaged project payload. If the
source app changes first, mirror the same change here before closing the task.
