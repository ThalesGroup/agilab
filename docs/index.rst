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
   ``uvx -p 3.13 agilab`` is perfect for demos or quick checks, but edits made inside the cached package are not persisted. For development work, clone the repo or use a dedicated virtual environment.

.. raw:: html

   <section class="agilab-teaser" style="margin: 2rem 0; padding: 2rem; border-radius: 18px; background: linear-gradient(135deg, #eef2ff 0%, #ecfdf5 100%); box-shadow: 0 18px 48px rgba(15, 23, 42, 0.08);">
     <div style="display: flex; flex-wrap: wrap; gap: 1.5rem; align-items: stretch;">
       <div style="flex: 1 1 260px; min-width: 240px;">
         <h2 style="margin: 0 0 0.6rem; font-size: 1.75rem; color: #111827;">From idea to deployed flow in minutes</h2>
         <p style="margin: 0; color: #334155;">AGILab packages notebooks as reproducible apps, bundles private assets, and ships ready-to-run workers.</p>
       </div>
       <div style="flex: 1 1 220px; min-width: 220px; display: flex; flex-direction: column; gap: 1rem;">
         <div style="background: rgba(59, 130, 246, 0.12); border-radius: 14px; padding: 1rem 1.2rem;">
           <h3 style="margin: 0 0 0.4rem; font-size: 1.1rem; color: #1d4ed8;">End users</h3>
           <ul style="margin: 0; padding-left: 1.1rem; color: #1e293b;">
             <li>Install with <code>uvx</code> or the generated shell wrappers.</li>
             <li>Launch curated flows with bundled data checkpoints.</li>
           </ul>
         </div>
         <div style="background: rgba(16, 185, 129, 0.15); border-radius: 14px; padding: 1rem 1.2rem;">
           <h3 style="margin: 0 0 0.4rem; font-size: 1.1rem; color: #047857;">Developers</h3>
           <ul style="margin: 0; padding-left: 1.1rem; color: #14532d;">
             <li>Clone the repo, regenerate run configs, adapt workers.</li>
             <li>Package private datasets with the shared installer.</li>
           </ul>
         </div>
       </div>
       <div style="flex: 1 1 220px; min-width: 220px; display: flex; flex-direction: column; gap: 1rem;">
         <div style="background: rgba(251, 191, 36, 0.18); border-radius: 14px; padding: 1rem 1.2rem;">
           <h3 style="margin: 0 0 0.4rem; font-size: 1.1rem; color: #b45309;">Ops &amp; support</h3>
           <ul style="margin: 0; padding-left: 1.1rem; color: #78350f;">
             <li>Use consistent run-command wrappers for troubleshooting.</li>
             <li>Restore datasets and verify installations with automated tests.</li>
           </ul>
         </div>
         <div style="background: rgba(99, 102, 241, 0.14); border-radius: 14px; padding: 1rem 1.2rem;">
           <h3 style="margin: 0 0 0.4rem; font-size: 1.1rem; color: #312e81;">Highlights</h3>
           <ul style="margin: 0; padding-left: 1.1rem; color: #312e81;">
             <li>IDE optional &mdash; CLI-first workflow.</li>
             <li>Shared build scripts across apps and components.</li>
           </ul>
         </div>
       </div>
     </div>
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
