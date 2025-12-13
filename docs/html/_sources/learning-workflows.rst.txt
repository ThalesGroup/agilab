Learning Workflows
==================

Some AGILab apps include learning components (for example supervised models,
reinforcement learning, or graph neural networks). This page describes how to
separate **training** from **inference**, and how **continuous learning** and
**federated learning** can be implemented with AGILab’s orchestration and
artifact conventions.

Training vs inference
---------------------

**Training** updates model parameters (and may produce new checkpoints).
**Inference** consumes a fixed checkpoint to produce decisions, allocations, or
predictions.

Reinforcement learning (example)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In reinforcement learning, a policy :math:`\pi_\theta(a \mid s)` is trained to
maximize expected discounted return:

.. math::

   J(\theta) = \mathbb{E}\left[\sum_{t=0}^{T-1} \gamma^t r_t\right]

where :math:`\gamma \in (0,1]` is a discount factor and :math:`r_t` is the
reward at step :math:`t`.

Optimization / ILP baseline (example)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A deterministic baseline can be expressed as an integer linear program (ILP):

.. math::

   \min_{x} \; c^\top x \quad \text{s.t.} \quad Ax \le b, \; x \in \{0,1\}^n

This kind of solver is useful as:

- a baseline for evaluation (compare against learned policies), and/or
- a **teacher** that produces high-quality labels to improve learning.

Continuous learning (optional)
------------------------------

Continuous learning means periodically updating a model after deployment, using
new data or feedback. AGILab does not enable this implicitly, but it provides
the building blocks to implement it explicitly:

- reproducible run orchestration (`AGI.run`, `AGI.install`, `AGI.get_distrib`)
- stable artifact paths (datasets, logs, checkpoints) via `AgiEnv` and share
  directory conventions
- per-step experiment capture via `lab_steps.toml`

One common pattern is “solver-as-teacher”:

1. Run inference with a policy checkpoint to produce decisions.
2. In parallel (or on sampled episodes), run an optimizer to compute a strong
   reference solution :math:`a_t^*` or a target value :math:`V^*(s_t)`.
3. Update the policy using behavior cloning / advantage shaping / reward
   augmentation, depending on the algorithm.

Graph neural networks (message passing)
---------------------------------------

Many decision problems are naturally represented as graphs with node features
:math:`x_v`, edge features :math:`e_{uv}`, and adjacency defined by the current
topology. A message-passing GNN updates node embeddings as:

.. math::

   m_v^{(k)} = \sum_{u \in \mathcal{N}(v)} \psi\left(h_v^{(k)}, h_u^{(k)}, e_{uv}\right),
   \qquad
   h_v^{(k+1)} = \phi\left(h_v^{(k)}, m_v^{(k)}\right)

Because aggregation is permutation-invariant, the same network can generalize
across different graph sizes and topologies (topology-agnostic policies), while
still learning node- and edge-level properties.

Federated learning (optional)
-----------------------------

Federated learning trains models across multiple sites without centralizing
raw data. A common aggregation is FedAvg:

.. math::

   \theta_{t+1} = \sum_{k=1}^{K} \frac{n_k}{\sum_j n_j} \, \theta_{t+1}^{(k)}

where :math:`\theta_{t+1}^{(k)}` is the model trained on site :math:`k` and
:math:`n_k` is the number of samples used there.

In AGILab terms, this can be implemented by orchestrating:

- per-site training runs that export checkpoints to a shared location, and
- an aggregation step that combines checkpoints into a new global model, then
  redeploys it for inference.

AGILab’s environment resolution and worker distribution make it straightforward
to run these steps locally or on SSH clusters, as long as sites agree on a
checkpoint format and aggregation protocol.
