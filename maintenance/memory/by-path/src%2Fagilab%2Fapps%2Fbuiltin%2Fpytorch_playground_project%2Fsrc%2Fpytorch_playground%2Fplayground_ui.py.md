---
schema: agilab.maintenance_memory.v1
source: src/agilab/apps/builtin/pytorch_playground_project/src/pytorch_playground/playground_ui.py
source_sha256: f10a935eb4262d1c7a3064ec548f137b24d9708e052bf89e9d7344cee2a80b3c
title: PyTorch Playground reuse handoff visibility
verified_commit: 14288641078471bf3f29b7cec8c67ede4939e539
---

# PyTorch Playground reuse handoff visibility

Hidden invariant: PyTorch Playground exports two reuse paths, plain PyTorch and
PyTorch Lightning. They must stay visible as two distinct handoff options in the
Evidence export area, and the evidence ZIP must keep both
`reuse/train_plain_pytorch.py` and `reuse/train_pytorch_lightning.py`.

Avoid hiding the two framework handoffs behind a single ambiguous snippet area.
The generic ORCHESTRATE run snippet is not the framework reuse code; the app UI
must make that distinction obvious to a new user.

When this source changes, keep the packaged PyPI payload mirror under
`src/agilab/lib/agi-app-pytorch-playground/.../playground_ui.py` aligned and run
`test/test_pytorch_playground_app.py`, which checks both UI snippets and source /
package payload parity.
