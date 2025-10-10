AGILab Documentation
=====================

Welcome to AGILab
-----------------

AGILab lets teams go beyond notebooks by building runnable apps.

- Build from experiments to apps: turn notebook logic into packaged, runnable applications with standard inputs/outputs, controls, and visualizations.
- Unified app experience: a consistent UI layer makes apps easy to use, test, and maintain.
- App store + scale-out: apps are orchestrable on a cluster for scalability, enabling seamless distribution and repeatable runs.
- Cross‑app reuse with apps‑pages: share UI pages and development effort across apps to avoid duplication and speed iteration.
- Shared dataframes: exchange tabular data between apps to compose workflows without brittle file hand‑offs.
- Experiment at speed: track, compare, and reproduce algorithm variants with MLflow built into the flow.
- Assisted by Generative AI: seamless integration with OpenAI API (online), GPT‑OSS (local), and Mistral‑instruct (local) to assist iteration, debugging, and documentation.

You’ll find everything from quickstarts to API references, as well as example projects.

Audience profiles
-----------------

- **Managers** run packaged demos via the IDE entry points or demo commands to quickly evaluate AGILab flows (read‑only usage).
- **End users** clone the repository and customize existing apps (configs, workers, small UI tweaks) to fit their use case—no need to modify the core framework. ``uvx`` is for demos/quick checks only and not recommended for regular use.
- **Developers** extend the framework: create new apps, add apps‑pages (e.g., new views), workers, and deeper changes. Use PyCharm run configurations (or generate terminal wrappers with ``python3 tools/generate_runconfig_scripts.py``).

Shell wrappers for developers
----------------------------

Developers who prefer a terminal can mirror PyCharm run configurations by regenerating shell wrappers with::

   python3 tools/generate_runconfig_scripts.py

This emits executable scripts under ``tools/run_configs/<group>/`` (``agilab``, ``apps``, ``components``); each mirrors a PyCharm run configuration (working directory, environment variables, and ``uv`` invocation).

.. note::
   ``uvx -p 3.13 agilab`` is intended for demos or quick checks only; edits made inside the cached package are not persisted. For development work, clone the repo or use a dedicated virtual environment. For offline workflows pick one of the bundled providers:

   - Launch a GPT-OSS responses server with ``python -m gpt_oss.responses_api.serve --inference-backend stub --port 8000`` and switch the Experiment sidebar to *GPT-OSS (local)*.
   - Install ``universal-offline-ai-chatbot`` (Mistral-based) and point the Experiment sidebar to your PDF corpus to enable the *mistral:instruct (local)* provider.

   When GPT-OSS is installed and the endpoint targets ``localhost``, the sidebar auto-starts the stub server for you.

Assistant providers
-------------------

The Experiment page ships with three assistants:

- **OpenAI (online)** — default cloud models via your API key.
- **GPT-OSS (local)** — local responses API with stub, transformers, or custom backends.
- **Mistral-instruct (local)** — local Mistral assistant powered by ``universal-offline-ai-chatbot``; build a FAISS index from your PDFs.

.. admonition:: AGILab: from notebooks to apps

   MLOps toolchain with OpenAI API, GPT‑OSS, Mistral-instruct, and MLflow.

Roadmap
-------

The current delivery plan is summarised in the lightweight `roadmap page <roadmap.html>`_. It highlights the IDE-neutral tooling work, scripted run-config wrappers, dataset recovery automation, and the documentation milestones that are in progress.

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
