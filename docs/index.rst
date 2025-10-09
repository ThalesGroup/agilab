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

.. raw:: html

   <section class="agilab-teaser" style="margin: 2rem 0; overflow: visible;">
     <svg viewBox="0 0 920 300" width="100%" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="agilab-teaser-title" style="display:block;max-width:100%;height:auto;shape-rendering:geometricPrecision;text-rendering:optimizeLegibility;overflow:visible;">
       <title id="agilab-teaser-title">AGILab accelerates the path from notebooks to scalable apps and coordinated delivery</title>
       <defs>
         <linearGradient id="teaser-bg" x1="0%" y1="0%" x2="100%" y2="100%">
           <stop offset="0%" stop-color="#f0f7ff" />
           <stop offset="100%" stop-color="#edf8f5" />
         </linearGradient>
         <linearGradient id="teaser-arrow" x1="0%" y1="0%" x2="100%" y2="0%">
           <stop offset="0%" stop-color="#3f82ff" />
           <stop offset="100%" stop-color="#35c4a0" />
         </linearGradient>
         <style>
           .teaser-circle { fill: #fff; stroke: rgba(0,0,0,0.08); stroke-width: 2; }
           .teaser-title { font: 600 18px "Segoe UI", Roboto, sans-serif; fill: #111827; }
           .teaser-sub { font: 14px "Segoe UI", Roboto, sans-serif; fill: #4b5563; }
         </style>
         <filter id="teaser-circle-shadow" x="-50%" y="-50%" width="200%" height="200%">
           <feDropShadow dx="0" dy="4" stdDeviation="3" flood-color="#1f2937" flood-opacity="0.12"/>
         </filter>
       </defs>
       <rect x="0" y="0" width="920" height="300" rx="22" fill="url(#teaser-bg)" />
       <path d="M210 150 H710" stroke="url(#teaser-arrow)" stroke-width="12" stroke-linecap="round" stroke-dasharray="16 14" />

       <g transform="translate(110,150)">
         <circle r="70" class="teaser-circle" filter="url(#teaser-circle-shadow)" stroke="#000" stroke-opacity="0.08" />
         <path d="M-30 10 h60" stroke="#3f82ff" stroke-width="6" stroke-linecap="round" />
         <rect x="-30" y="-20" width="60" height="26" rx="6" fill="#dbeafe" />
         <rect x="-30" y="-50" width="60" height="20" rx="6" fill="#bfdbfe" />
         <text class="teaser-title" text-anchor="middle" y="110" font-family="Segoe UI, Roboto, sans-serif" font-size="18" font-weight="600" fill="#111827">Notebook</text>
         <text class="teaser-sub" text-anchor="middle" y="134" font-family="Segoe UI, Roboto, sans-serif" font-size="14" fill="#4b5563">→ App in minutes</text>
       </g>

       <g transform="translate(320,150)">
         <circle r="70" class="teaser-circle" filter="url(#teaser-circle-shadow)" stroke="#000" stroke-opacity="0.08" />
         <path d="M-32 6 h64" stroke="#22d3ee" stroke-width="6" stroke-linecap="round" />
         <path d="M-10 -15 L10 -15" stroke="#0ea5e9" stroke-width="6" stroke-linecap="round" />
         <path d="M-10 -35 L10 -35" stroke="#0ea5e9" stroke-width="6" stroke-linecap="round" />
         <text class="teaser-title" text-anchor="middle" y="110" font-family="Segoe UI, Roboto, sans-serif" font-size="18" font-weight="600" fill="#111827">Deploy at scale</text>
         <text class="teaser-sub" text-anchor="middle" y="134" font-family="Segoe UI, Roboto, sans-serif" font-size="14" fill="#4b5563">Streamlit · CLI · workers</text>
       </g>

       <g transform="translate(540,150)">
         <circle r="70" class="teaser-circle" filter="url(#teaser-circle-shadow)" stroke="#000" stroke-opacity="0.08" />
         <path d="M-28 -18 L0 18 L28 -18" fill="none" stroke="#22c55e" stroke-width="6" stroke-linecap="round" />
         <path d="M-40 24 h80" stroke="#86efac" stroke-width="8" stroke-linecap="round" />
         <text class="teaser-title" text-anchor="middle" y="110" font-family="Segoe UI, Roboto, sans-serif" font-size="18" font-weight="600" fill="#111827">Scale the team</text>
         <text class="teaser-sub" text-anchor="middle" y="134" font-family="Segoe UI, Roboto, sans-serif" font-size="14" fill="#4b5563">From solo to seamless collab</text>
       </g>

       <g transform="translate(760,150)">
         <circle r="70" class="teaser-circle" filter="url(#teaser-circle-shadow)" stroke="#000" stroke-opacity="0.08" />
         <path d="M-26 -20 h52 a20 20 0 0 1 0 40 h-52 a20 20 0 0 1 0 -40 z" fill="#e9d5ff" />
         <path d="M-18 -36 h36" stroke="#a855f7" stroke-width="6" stroke-linecap="round" />
         <path d="M-24 10 h48" stroke="#7c3aed" stroke-width="6" stroke-linecap="round" />
         <text class="teaser-title" text-anchor="middle" y="110" font-family="Segoe UI, Roboto, sans-serif" font-size="18" font-weight="600" fill="#111827">Standardize</text>
         <text class="teaser-sub" text-anchor="middle" y="134" font-family="Segoe UI, Roboto, sans-serif" font-size="14" fill="#4b5563">Data + algorithm ops unified</text>
     </g>
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
