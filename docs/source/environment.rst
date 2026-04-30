Environment Variables
=====================

AGILab reads its configuration from environment variables. You can set them globally in
``$HOME/.agilab/.env`` or per-session before launching the web interface / AGI installers. The table below
summarises the supported keys.

.. list-table:: Runtime configuration
   :header-rows: 1

   * - Variable
     - Default
     - Purpose
   * - ``APPS_PATH``
     - ``~/agilab/src/agilab/apps``
     - Root directory containing app projects; used when selecting the active app.
   * - ``APP_DEFAULT``
     - ``flight_project``
     - App loaded when no explicit project is provided.
   * - ``AGI_PYTHON_VERSION``
     - ``3.13``
     - Default Python version passed to ``uv`` for the manager environment and as the fallback worker version when no host-specific override is set.
   * - ``<worker-host>_PYTHON_VERSION``
     - unset
     - Optional worker-specific Python version override written per host (for example ``127.0.0.1_PYTHON_VERSION=3.13``). Use this when workers must run a different Python version than the manager side.
   * - ``AGI_PYTHON_FREE_THREADED``
     - ``0``
     - Enables free-threaded Python if both the environment and worker declare support. Either the
       string ``"1"`` or a truthy value activates it.
   * - ``TABLE_MAX_ROWS``
     - ``1000``
     - Maximum number of rows shown in web data previews.
   * - ``TABLE_SAMPLING``
     - ``20``
     - Sample size used when previewing large tables.
   * - ``CLUSTER_CREDENTIALS``
     - Current OS user
     - Username/password pair (``user:pass``) used by cluster automation scripts. In portable cluster setups, set this explicitly to the real login user on the worker machines. Do not assume ``agi`` unless the remote account is actually named ``agi``.
   * - ``OPENAI_API_KEY``
     - unset
     - API key surfaced to features that rely on OpenAI endpoints.
   * - ``MISTRAL_API_KEY``
     - unset
     - API key used by the PIPELINE assistant when ``Mistral Medium 3.5 (online)``
       is selected.
   * - ``MISTRAL_MODEL``
     - ``mistral-medium-3.5``
     - Mistral chat model used by the online Mistral assistant provider.
   * - ``MISTRAL_REASONING_EFFORT``
     - ``high``
     - Reasoning mode passed to Mistral chat completions. Supported values are
       ``high`` and ``none``.
   * - ``MISTRAL_TEMPERATURE``
     - ``0.7`` for ``high``, ``0.1`` for ``none``
     - Sampling temperature for the online Mistral assistant provider.
   * - ``MISTRAL_BASE_URL``
     - ``https://api.mistral.ai/v1``
     - Optional Mistral-compatible API base URL, for example when routing through
       a gateway.
   * - ``AGI_SHARE_DIR``
     - ``clustershare/<user>`` (resolved under ``$HOME`` if relative).
     - User-facing knob for the shared datasets/outputs root. When cluster mode is enabled, this value is applied to ``AGI_CLUSTER_SHARE`` and must resolve to a mounted, writable shared path on every node. The implicit default is user-scoped so datasets and cluster-visible outputs stay isolated per workspace. Operators can still override it with an explicit mounted path.
   * - ``AGILAB_SHARE_USER``
     - ``USER`` / ``USERNAME`` / ``user``
     - Optional override for the ``<user>`` segment used by the implicit ``clustershare/<user>`` default. The value is sanitised before it is used in a filesystem path.
   * - ``AGI_LOCAL_SHARE``
     - ``$HOME/localshare``
     - Local datasets/outputs root used when cluster mode is disabled. In cluster mode, AGILab no longer falls back to this path if the shared mount is missing.
   * - ``AGI_SCHEDULER_IP``
     - ``127.0.0.1``
     - Default scheduler host for distributed runs.
   * - ``AGI_LOG_DIR``
     - ``~/log``
     - Parent directory for install logs (``install_logs``), worker logs, and general telemetry.
   * - ``AGI_EXPORT_DIR``
     - ``~/export``
     - Target directory for exported artefacts.
   * - ``MLFLOW_TRACKING_DIR``
     - ``~/.mlflow``
     - Where MLflow tracking data is stored. The PIPELINE page serves the local
       MLflow UI from this directory and records parent/step run metadata and
       artefacts there.
   * - ``AGI_PAGES_DIR``
     - ``agilab/apps-pages``
     - Location of web page bundles loaded by the Analysis page.
   * - ``APPS_REPOSITORY``
     - unset
     - Optional pointer to the repository checkout containing apps or overrides.
   * - ``INSTALL_TYPE``
     - ``1``
     - Controls the installation mode passed to ``AgiEnv``/installers (1 = developer workflow).

Additional host specific keys are supported for worker provisioning (for example
``127.0.0.1_CMD_PREFIX`` or ``127.0.0.1_PYTHON_VERSION``). These are written automatically into
``$HOME/.agilab/.env`` when you run installers and can be adjusted manually when one worker host
needs a different Python version or command prefix.

Remember to restart the web interface session after changing ``$HOME/.agilab/.env`` so ``AgiEnv`` picks
up the new values.

Cluster isolation note
----------------------

For cluster-enabled use cases, treat the share directory as part of the user's
workspace contract, not as a generic team dropbox.

- The default ``AGI_SHARE_DIR`` / ``AGI_CLUSTER_SHARE`` root is user-scoped.
- If you override it, keep one root per user.
- Each user should also use their own real worker login account or explicit
  ``user@host`` targets when connecting to the cluster.
- Do not point multiple users at the same writable cluster-share directory.
- Keep per-user datasets, worker installation files, and cluster-visible outputs
  isolated from other users.

Generated snippets and operator logs are a separate concern: they live under
``AGI_LOG_DIR`` (by default ``~/log``), not under the cluster share.

This avoids accidental reuse or overwrite of another operator's intermediate
files and keeps cluster troubleshooting tied to one workspace at a time.

Security note
-------------

Prefer environment variables or ``$HOME/.agilab/.env`` for secrets such as
``OPENAI_API_KEY``, ``MISTRAL_API_KEY``, and ``CLUSTER_CREDENTIALS``. Avoid passing them on the
command line because shell history and process listings can expose them.
