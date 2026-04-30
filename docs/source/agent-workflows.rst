Agent Workflows
===============

This page is for developers and contributors working inside the AGILAB
repository. It is not the newcomer path.

If you are new to AGILAB, stay on :doc:`quick-start` first. Use this page only
when you intentionally want a CLI coding-agent workflow against the repository
itself.

What "repo-ready" means
-----------------------

The repository already ships the configuration, wrappers, and conventions
needed to work with these agent paths against the same repo contract:

- Codex
- Claude
- Aider
- OpenCode

That does not mean the four tools behave identically. It means the repo now
contains a prepared entry path for each of them instead of relying on ad hoc
local setup.

Shared repo contract
--------------------

Before a non-trivial change, start with::

   uv --preview-features extra-build-dependencies run python tools/impact_validate.py --staged

Then follow the repo rules in:

- ``AGENT_CONVENTIONS.md`` for the short local-agent contract
- ``AGENTS.md`` for the full AGILAB runbook and validation rules

The main rule is simple: run the narrowest local proof first, then reproduce
the real AGILAB path before broader validation.

Supported agent paths
---------------------

Codex and Claude
^^^^^^^^^^^^^^^^

- Repo-managed skills live under ``.codex/skills`` and ``.claude/skills``.
- ``AGENTS.md`` remains the source of truth for repo policy, validation, and
  launch rules.

Aider
^^^^^

Use the wrapper from the repository root::

   ./tools/aider_workflow.sh chat

For a one-off task::

   ./tools/aider_workflow.sh exec "Refactor only ... keeping behavior unchanged"

What the repo already provides:

- ``.aider.conf.yml`` for repo-local defaults
- ``tools/aider_workflow.sh`` for the standard entry path
- ``tools/aider_workflow.md`` for usage details

Default local model path:

- ``qwen-local`` -> ``ollama_chat/qwen2.5-coder:latest``

OpenCode
^^^^^^^^

Use the wrapper from the repository root::

   ./tools/opencode_workflow.sh chat

For a one-off task::

   ./tools/opencode_workflow.sh exec "Add a regression test for ..."

What the repo already provides:

- ``opencode.json`` for project configuration
- ``.opencode/agents/`` for project-scoped agents
- ``tools/opencode_workflow.sh`` for the standard entry path
- ``tools/opencode_workflow.md`` for usage details

Default local model path:

- ``ollama/qwen2.5-coder:latest``

Local model prerequisite
------------------------

Aider and OpenCode in this repo are prepared for local Ollama-backed models.
In practice this means:

- keep a local Ollama server running
- use the repo defaults or override them with the documented environment
  variables

The prepared local families are the same ones already documented elsewhere in
AGILAB: ``qwen`` and ``deepseek``.

Where to read the repo-local files
----------------------------------

The public docs page gives the high-level entry points. The operational details
stay in the repository itself:

- `AGENTS.md <https://github.com/ThalesGroup/agilab/blob/main/AGENTS.md>`_
- `AGENT_CONVENTIONS.md <https://github.com/ThalesGroup/agilab/blob/main/AGENT_CONVENTIONS.md>`_
- `tools/agent_workflows.md <https://github.com/ThalesGroup/agilab/blob/main/tools/agent_workflows.md>`_
- `docs/CLI_FIRST_WORKFLOW.md <https://github.com/ThalesGroup/agilab/blob/main/docs/CLI_FIRST_WORKFLOW.md>`_
- `tools/aider_workflow.md <https://github.com/ThalesGroup/agilab/blob/main/tools/aider_workflow.md>`_
- `tools/opencode_workflow.md <https://github.com/ThalesGroup/agilab/blob/main/tools/opencode_workflow.md>`_

When not to use this page
-------------------------

- If you are doing your first real AGILAB run, use :doc:`quick-start`.
- If you want the notebook-first runtime path, use :doc:`notebook-quickstart`.
- If you want a public demo route instead of repo work, use :doc:`demos`.
