AGILab Documentation
=====================

Welcome to the AGILab framework documentation.
You’ll find everything from quickstarts to API references, as well as example projects.

Audience profiles
-----------------

- **End users** install and launch packaged apps with ``uvx`` or the generated shell wrappers under ``tools/run_configs/``—no repository checkout or IDE required.
- **Developers** clone the repository, regenerate run configurations (``python3 tools/generate_runconfig_scripts.py``), and extend apps or the core framework.

Shell wrappers for run configs
------------------------------

If you want to run the IDE workflows from a terminal, regenerate the shell wrappers with::

   python3 tools/generate_runconfig_scripts.py

The command emits executable scripts under ``tools/run_configs/<group>/`` (``agilab``, ``apps``, ``components``); each one mirrors a PyCharm run configuration (working directory, environment variables, and ``uv`` invocation).

.. note::
   ``uvx -p 3.13 agilab`` is perfect for demos or quick checks, but edits made inside the cached package are not persisted. For development work, clone the repo or use a dedicated virtual environment. For offline workflows pick one of the bundled providers:

   - Launch a GPT-OSS responses server with ``python -m gpt_oss.responses_api.serve --inference-backend stub --port 8000`` and switch the Experiment sidebar to *GPT-OSS (local)*.
   - Install ``universal-offline-ai-chatbot`` (Mistral-based) and point the Experiment sidebar to your PDF corpus to enable the *mistral:instruct (local)* provider.

   When GPT-OSS is installed and the endpoint targets ``localhost``, the sidebar auto-starts the stub server for you.

Assistant providers
-------------------

The Experiment page ships with three assistants:

- **OpenAI (online)** — default cloud models via your API key.
- **GPT-OSS (offline)** — local responses API with stub, transformers, or custom backends.
- **mistral:instruct (local)** — local Mistral assistant powered by ``universal-offline-ai-chatbot``; build a FAISS index from your PDFs.

.. admonition:: AGILab: from notebooks to apps

   MLOps toolchain with OpenAI API, GPT‑OSS, mistral:instruct, and MLflow.

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
