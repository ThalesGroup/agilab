---
schema: agilab.maintenance_memory.v1
source: src/agilab/apps/builtin/pytorch_playground_project/src/pytorch_playground/playground_ui.py
source_sha256: 3937e5a33aa5003e5e4b0894845d7bd7276c1732a15c181e49fd24a1de95ae1f
title: PyTorch Playground reuse handoff visibility
verified_commit: 7f25170446277e5a6fc1fc816a0ff7b1d5466e74
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
