AGILab Documentation
====================

*Build repeatable AI workflows—spec first, code next.*

AGILab couples Spec-Driven execution with experiment-to-production tooling so data
teams can move beyond notebooks. This documentation mirrors the Spec Kit structure:
start with a shared understanding, move through guided workflows, and finish with
references that keep humans and agents aligned.

What is AGILab?
---------------

AGILab turns iterative experiments into runnable applications. It provides:

* **Specification-driven flows** – apps define their inputs, controls, and outputs up
  front, allowing agents and humans to reason about behaviour before implementation.
* **Consistent UI surfaces** – Streamlit pages (Edit, Execute, Experiment, Explore)
  give every app a shared look and feel, reducing onboarding time.
* **Cluster orchestration** – packaged workers scale across schedulers with automated
  UV/Python bootstrapping, capacity balancing, and log streaming.
* **Integrated copilots** – OpenAI, GPT-OSS, and Mistral-instruct assistants guide
  exploration, editing, and debugging without leaving the workflow.

Why AGILab?
-----------

*Progress over prototypes.* Whether you are extending an app or introducing a new
worker, AGILab keeps teams focused on business scenarios, not plumbing.

* **Notebook to app, on rails** – convert exploratory code into reproducible apps with
  guardrails for configuration, data exchange, and testing.
* **Scale without surprises** – unify local execution and distributed runs with the
  same CLI/PyCharm entry points.
* **Shared components** – reuse pages, workers, and datasets across projects; no more
  copy/paste forks.
* **AI-augmented iteration** – built-in assistants accelerate hypothesis testing while
  keeping the final say with your team.

Workflow at a glance
--------------------

1. **Plan** – capture requirements in specs, update run configs, and regenerate CLI
   wrappers (`AGENTS.md` details the full agent playbook).
2. **Build** – implement or modify apps, workers, and pages using the PyCharm runs or
   shell wrappers generated from `.idea/runConfigurations`.
3. **Validate & Ship** – run installs, distribute workloads, and publish packages with
   a single set of commands mirrored across IDEs and terminals.

.. tip::
   Regenerate CLI wrappers with ``uv run python tools/generate_runconfig_scripts.py``
   whenever a run configuration changes. This keeps human workflows and automation in
   sync.

Assistant providers
-------------------

AGILab ships three assistants that align with Spec Kit’s multi-agent philosophy:

* **OpenAI (online)** – default cloud models via your API key.
* **GPT-OSS (local)** – local responses API with stub, transformers, or custom backends.
* **Mistral-instruct (local)** – powered by ``universal-offline-ai-chatbot``; build a
  FAISS index from your PDFs for offline work.

.. note::
   ``uvx -p 3.13 agilab`` is designed for demos and quick checks. For development,
   clone the repository or operate inside a dedicated virtual environment so changes
   persist outside the cached package.

Audience profiles
-----------------

* **Managers** – run packaged demos via IDE entries or generated CLI scripts to assess
  app behaviour.
* **Practitioners & end users** – customize shipping apps (configs, workers, UI tweaks)
  without touching the core framework; rely on `uv` workflows and the agent runbook.
* **Framework developers** – extend AGILab itself: add new apps, pages, workers, or
  cluster capabilities while maintaining Spec-driven documentation.

Roadmap
-------

A condensed delivery plan lives on the `roadmap page <roadmap.html>`_. It tracks
IDE-neutral tooling, automation for dataset recovery, documentation milestones, and
cluster feature work.

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   quick-start
   introduction
   introduction2
   introduction3
   features

.. toctree::
   :maxdepth: 2
   :caption: Core Topics

   cluster
   cluster-help
   agilab
   framework-api
    
   environment
   faq
   directory-structure
   install-usecase
   troubleshooting
   license

.. toctree::
   :maxdepth: 2
   :caption: Pages

   edit-help
   execute-help
   experiment-help
   explore-help
   apps-pages

.. toctree::
   :maxdepth: 2
   :caption: Apps Examples

   mycode-project
   flight-project
   example-app-project
   example-app-project
   example-app-project
   example-app-project

.. toctree::
   :maxdepth: 2
   :caption: Hosting Sites

   agilab-github

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
