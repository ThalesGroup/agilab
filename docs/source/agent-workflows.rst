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

For fast local feedback before a larger parity profile, use the repo-owned
genetic regression selector::

   ./dev regress

This runs ``tools/ga_regression_selector.py --staged --run``. It optimizes a
small pytest subset from the changed files and available JUnit timings. Treat it
as an accelerator for the first local loop, not as a replacement for the
required gates reported by ``impact_validate.py``.

Then follow the repo rules in:

- ``AGENT_CONVENTIONS.md`` for the short local-agent contract
- ``AGENTS.md`` for the full AGILAB runbook and validation rules

The main rule is simple: run the narrowest local proof first, then reproduce
the real AGILAB path before broader validation.

Agent run evidence
------------------

Use ``agilab agent-run`` when a coding-agent action should leave AGILAB
evidence instead of only a tool-specific log::

   agilab agent-run --agent codex --label "Review current diff" -- codex review

The command writes a redacted ``agilab.agent_run.v1`` manifest plus local
``stdout.txt`` and ``stderr.txt`` artifacts under
``~/log/agents/<agent>/<run-id>/``. Environment override values passed with
``--env KEY=VALUE`` are redacted from the manifest. Command arguments are
redacted by default and represented by an argv hash; pass
``--include-command-args`` only when the prompt/arguments are safe to store. The
stdout/stderr files stay local artifacts so tool output is not embedded in
public JSON by default.

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

Additional local aliases:

- ``gpt-oss-local`` -> ``ollama_chat/gpt-oss:20b``
- ``qwen3-local`` -> ``ollama_chat/qwen3:30b-a3b-instruct-2507-q4_K_M``
- ``qwen3-coder-local`` -> ``ollama_chat/qwen3-coder:30b-a3b-q4_K_M``
- ``ministral-local`` -> ``ollama_chat/ministral-3:14b-instruct-2512-q4_K_M``
- ``phi4-mini-local`` -> ``ollama_chat/phi4-mini:3.8b-q4_K_M``

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

Useful efficient local overrides include ``ollama/gpt-oss:20b``,
``ollama/qwen3-coder:30b-a3b-q4_K_M``,
``ollama/qwen3:30b-a3b-instruct-2507-q4_K_M``,
``ollama/ministral-3:14b-instruct-2512-q4_K_M``, and
``ollama/phi4-mini:3.8b-q4_K_M``.

Local model prerequisite
------------------------

Aider and OpenCode in this repo are prepared for local Ollama-backed models.
In practice this means:

- keep a local Ollama server running
- use the repo defaults or override them with the documented environment
  variables

The prepared local families are the same ones already documented elsewhere in
AGILAB: ``gpt-oss``, ``qwen``, ``deepseek``, ``qwen3``, ``qwen3-coder``,
``ministral``, and ``phi4-mini``. If a model is served through vLLM or another
OpenAI-compatible gateway instead of Ollama, configure the AGILAB assistant
with ``AGILAB_LLM_BASE_URL`` and ``AGILAB_LLM_MODEL``.

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
