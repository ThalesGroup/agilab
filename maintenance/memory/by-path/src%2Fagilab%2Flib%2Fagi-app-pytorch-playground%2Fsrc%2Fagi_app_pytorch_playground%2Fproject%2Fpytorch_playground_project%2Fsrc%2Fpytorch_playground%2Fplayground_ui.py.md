---
schema: agilab.maintenance_memory.v1
source: src/agilab/lib/agi-app-pytorch-playground/src/agi_app_pytorch_playground/project/pytorch_playground_project/src/pytorch_playground/playground_ui.py
source_sha256: f10a935eb4262d1c7a3064ec548f137b24d9708e052bf89e9d7344cee2a80b3c
title: PyTorch Playground package mirror parity
verified_commit: 14288641078471bf3f29b7cec8c67ede4939e539
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
