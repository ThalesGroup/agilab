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
   ``uvx -p 3.13 agilab`` is perfect for demos or quick checks, but edits made inside the cached package are not persisted. For development work, clone the repo or use a dedicated virtual environment. To stay offline, start a GPT-OSS responses server with ``python -m gpt_oss.responses_api.serve --inference-backend stub --port 8000`` and switch the Experiment sidebar to *GPT-OSS (local)*. When the package is installed and the endpoint targets ``localhost``, the sidebar auto-starts the stub server for you.

.. raw:: html

   <section class="agilab-teaser" style="margin: 2rem 0;">
     <svg viewBox="0 0 960 260" width="100%" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="agilab-architecture-title" style="display:block;max-width:100%;height:auto;shape-rendering:geometricPrecision;text-rendering:optimizeLegibility;overflow:visible;">
       <title id="agilab-architecture-title">AGILab app architecture: manager venv, Streamlit pages venv, worker venvs for cluster deployment</title>
       <defs>
         <linearGradient id="teaser-bg" x1="0%" y1="0%" x2="100%" y2="100%">
           <stop offset="0%" stop-color="#eef2ff" />
           <stop offset="100%" stop-color="#ecfdf4" />
         </linearGradient>
         <linearGradient id="manager-grad" x1="0%" y1="0%" x2="100%" y2="100%">
           <stop offset="0%" stop-color="#bfdbfe" />
           <stop offset="100%" stop-color="#93c5fd" />
         </linearGradient>
         <linearGradient id="pages-grad" x1="0%" y1="0%" x2="100%" y2="100%">
           <stop offset="0%" stop-color="#c7f9cc" />
           <stop offset="100%" stop-color="#6ee7b7" />
         </linearGradient>
         <linearGradient id="workers-grad" x1="0%" y1="0%" x2="100%" y2="100%">
           <stop offset="0%" stop-color="#ede9fe" />
           <stop offset="100%" stop-color="#a78bfa" />
         </linearGradient>
         <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
           <polygon points="0 0, 10 3.5, 0 7" fill="#1f2937" />
         </marker>
         <style>
           text { font-family: "Segoe UI", Roboto, sans-serif; fill: #0f172a; }
           .title { font-weight: 600; font-size: 18px; }
           .subtitle { font-size: 13px; fill: #334155; }
         </style>
       </defs>
       <rect x="0" y="0" width="960" height="260" rx="26" fill="url(#teaser-bg)" />

       <!-- Manager venv -->
       <g transform="translate(80,70)">
         <rect x="0" y="0" width="240" height="150" rx="18" fill="url(#manager-grad)" opacity="0.95" />
         <rect x="18" y="54" width="204" height="72" rx="12" fill="#e0edfb" />
         <text class="title" x="120" y="32" text-anchor="middle">App manager <tspan fill="#0f766e">venv</tspan></text>
         <text class="subtitle" x="120" y="58" text-anchor="middle">Args settings, forms, install.py</text>
         <text class="subtitle" x="40" y="94">• Pydantic args model</text>
         <text class="subtitle" x="40" y="116">• `app_settings.toml` binding</text>
         <text class="subtitle" x="40" y="138">• Packages curated templates</text>
       </g>

       <!-- Streamlit pages -->
       <g transform="translate(360,70)">
         <rect x="0" y="0" width="240" height="150" rx="18" fill="url(#pages-grad)" opacity="0.95" />
         <rect x="18" y="54" width="204" height="72" rx="12" fill="#d9fde9" />
         <text class="title" x="120" y="32" text-anchor="middle">Pages (Streamlit) <tspan fill="#0f766e">venv</tspan></text>
         <text class="subtitle" x="120" y="58" text-anchor="middle">Data viz + controls per page</text>
         <text class="subtitle" x="40" y="94">• `apps-pages/` bundle</text>
         <text class="subtitle" x="40" y="116">• Independent requirements</text>
         <text class="subtitle" x="40" y="138">• Publishes dashboards/UI</text>
       </g>

       <!-- Workers -->
       <g transform="translate(640,60)">
         <rect x="0" y="0" width="250" height="170" rx="18" fill="url(#workers-grad)" opacity="0.95" />
         <text class="title" x="125" y="32" text-anchor="middle">Workers fleet <tspan fill="#0f766e">venvs</tspan></text>
         <text class="subtitle" x="125" y="58" text-anchor="middle">Packaged for cluster deployment</text>
         <g transform="translate(25,78)">
           <rect x="0" y="0" width="70" height="52" rx="10" fill="#ede9fe" stroke="#8b5cf6" stroke-width="1.6" />
           <text class="subtitle" x="35" y="24" text-anchor="middle">pandas</text>
           <text class="subtitle" x="35" y="42" text-anchor="middle">worker</text>
         </g>
         <g transform="translate(95,78)">
           <rect x="0" y="0" width="70" height="52" rx="10" fill="#ede9fe" stroke="#8b5cf6" stroke-width="1.6" />
           <text class="subtitle" x="35" y="24" text-anchor="middle">polars</text>
           <text class="subtitle" x="35" y="42" text-anchor="middle">worker</text>
         </g>
         <g transform="translate(165,78)">
           <rect x="0" y="0" width="70" height="52" rx="10" fill="#ede9fe" stroke="#8b5cf6" stroke-width="1.6" />
           <text class="subtitle" x="35" y="24" text-anchor="middle">dag</text>
           <text class="subtitle" x="35" y="42" text-anchor="middle">worker</text>
         </g>
         <text class="subtitle" x="125" y="148" text-anchor="middle">Deployed via `agi_node.agi_dispatcher.build`</text>
       </g>

       <!-- Arrows -->
       <line x1="320" y1="145" x2="360" y2="145" stroke="#1f2937" stroke-width="2.5" marker-end="url(#arrowhead)" />
       <text class="subtitle" x="340" y="134" text-anchor="middle">Install</text>

       <line x1="600" y1="145" x2="640" y2="145" stroke="#1f2937" stroke-width="2.5" marker-end="url(#arrowhead)" />
       <text class="subtitle" x="620" y="134" text-anchor="middle">Distribute</text>
     </svg>
   </section>

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
