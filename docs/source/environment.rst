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
     - ``$AGILAB_CHECKOUT/src/agilab/apps`` in source checkouts
     - Root directory containing app projects; used when selecting the active app.
       Replace ``$AGILAB_CHECKOUT`` with the checkout you are actually running;
       AGILAB does not require the source tree directory to be named ``agilab``.
   * - ``APP_DEFAULT``
     - ``flight_telemetry_project``
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
     - API key used by the WORKFLOW assistant when ``Mistral Medium 3.5 (online)``
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
   * - ``AGILAB_LLM_BASE_URL``
     - ``http://127.0.0.1:8000/v1``
     - OpenAI-compatible Chat Completions base URL used by the WORKFLOW assistant
       when ``vLLM / OpenAI-compatible (self-hosted)`` is selected. Point this at
       a vLLM, LM Studio, OpenRouter, or gateway endpoint.
   * - ``AGILAB_LLM_MODEL``
     - ``Qwen/Qwen2.5-Coder-7B-Instruct``
     - Model name passed to the OpenAI-compatible endpoint. For vLLM this should
       match the model served by ``vllm serve <model>``.
   * - ``AGILAB_LLM_API_KEY``
     - ``EMPTY``
     - Bearer token for the OpenAI-compatible endpoint. Local vLLM commonly
       accepts any value; gateways may require a real key.
   * - ``AGILAB_LLM_TEMPERATURE``
     - ``0.1``
     - Sampling temperature for the OpenAI-compatible assistant provider.
   * - ``AGILAB_LLM_MAX_TOKENS``
     - unset
     - Optional maximum number of generated tokens for the OpenAI-compatible
       assistant provider.
   * - ``AGILAB_LLM_TIMEOUT``
     - ``120``
     - Request timeout in seconds for the OpenAI-compatible assistant provider.
   * - ``LAB_LLM_PROVIDER``
     - ``openai``
     - WORKFLOW assistant provider. Local Ollama families use values such as
       ``ollama-gpt-oss``, ``ollama-qwen3-coder``, or ``ollama-phi4-mini``.
       ``--install-local-models`` sets this to the first requested family.
   * - ``UOAIC_OLLAMA_ENDPOINT``
     - ``http://127.0.0.1:11434``
     - Ollama endpoint used by the WORKFLOW local assistant controls.
   * - ``UOAIC_MODEL``
     - unset
     - Ollama model selected in WORKFLOW. The shell installers persist this
       when ``--install-local-models`` is used, for example ``gpt-oss:20b`` or
       ``qwen3-coder:30b-a3b-q4_K_M``.
   * - ``UOAIC_MODE``
     - ``ollama``
     - Local assistant mode. ``ollama`` uses direct local generation; ``rag``
       enables the Universal Offline AI Chatbot document RAG path.
   * - ``AGILAB_PIPELINE_RECIPE_MEMORY``
     - ``1``
     - Enables local WORKFLOW recipe-memory retrieval. When enabled, the code
       assistant mines validated ``lab_steps.toml`` entries, supervisor
       notebooks, and the local recipe-card store, then adds matching examples
       to the model-facing prompt. Saved lab questions remain unchanged.
   * - ``AGILAB_PIPELINE_RECIPE_MEMORY_PATH``
     - ``~/.agilab/pipeline_recipe_memory/cards.jsonl``
     - Local JSONL recipe-card store used for snippets that AGILAB validates
       during the dataframe auto-fix loop. The store is provider-neutral and can
       be reused with OpenAI, Mistral, OpenAI-compatible gateways, GPT-OSS, or
       Ollama-backed models.
   * - ``AGILAB_PIPELINE_RECIPE_MEMORY_ROOTS``
     - unset
     - Optional ``os.pathsep``-separated list of extra directories or files to
       mine for recipe cards. AGILAB already considers the selected
       ``lab_steps.toml``, active app, dataframe directory, and built-in app
       examples.
   * - ``AGILAB_PIPELINE_RECIPE_MEMORY_INCLUDE_CANDIDATES``
     - ``0``
     - Includes unvalidated candidate snippets in retrieval when set to a
       truthy value. Leave disabled for normal use so only validated or executed
       recipes influence generation.
   * - ``AGI_SHARE_DIR``
     - ``clustershare/<user>`` (resolved under ``$HOME`` if relative).
     - User-facing knob for the shared datasets/outputs root. Prefer the relative
       user-scoped form so mixed macOS/Linux/Windows nodes can resolve it under
       their own home directory. When cluster mode is enabled, this value is
       applied to ``AGI_CLUSTER_SHARE``; ORCHESTRATE and remote deployment
       re-root home-based absolute paths such as ``/Users/<user>/...`` or
       ``C:\Users\<user>\...`` to the portable suffix before writing worker
       settings. Operators can still override it with an explicit mounted path
       such as ``/mnt/agilab`` when the same mount point exists on every node.
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
     - Where MLflow tracking data is stored. The WORKFLOW page serves the local
       MLflow UI from this directory and records parent/stage run metadata and
       artefacts there.
   * - ``AGI_PAGES_DIR``
     - ``agilab/apps-pages``
     - Location of web page bundles loaded by the Analysis page.
   * - ``APPS_REPOSITORY``
     - unset
     - Optional pointer to the repository checkout containing apps or overrides.
       Treat it as an executable-code boundary. For shared/team installs, set
       ``AGILAB_STRICT_APPS_REPOSITORY=1`` or ``AGILAB_SHARED_MODE=1`` and
       populate ``AGILAB_APPS_REPOSITORY_ALLOWLIST`` with the reviewed checkout
       path. Strict mode refuses unallowlisted repositories and floating Git
       branches unless ``AGILAB_DEV_APPS_REPOSITORY=1`` is set for an explicit
       development install.
   * - ``AGILAB_UI_HOST``
     - ``127.0.0.1``
     - Host passed by the ``agilab`` CLI to Streamlit. Keep the default for
       local use. Binding to ``0.0.0.0`` or ``::`` is refused unless
       ``AGILAB_PUBLIC_BIND_OK=1`` and an auth/TLS indicator such as
       ``AGILAB_TLS_TERMINATED=1`` are both set.
   * - ``AGILAB_PUBLIC_BIND_OK``
     - unset
     - Explicit acknowledgement that the Streamlit UI may bind publicly. This
       flag is not sufficient alone; AGILAB also requires one of
       ``AGILAB_AUTH_REQUIRED``, ``AGILAB_PUBLIC_AUTH``,
       ``AGILAB_TLS_TERMINATED``, or ``STREAMLIT_AUTH_REQUIRED`` so accidental
       public exposure fails closed.
   * - ``AGILAB_GENERATED_CODE_SANDBOX``
     - unset
     - Required only for the advanced raw-Python WORKFLOW auto-fix path.
       Normal dataframe generation uses safe-action JSON contracts that AGILAB
       validates before converting them into deterministic pandas code.
       Supported acknowledgement values are ``process``, ``container``, or
       ``vm``. Leave unset unless generated-code execution is actually isolated
       from personal files, secrets, network, and unbounded CPU/RAM/time.
       For shared use, prefer ``container`` or ``vm``. If ``process`` is used,
       also enforce process resource/filesystem/network/secret limits and set
       ``AGILAB_GENERATED_CODE_PROCESS_LIMITS=1`` so the adoption gate can
       distinguish a bounded process runner from a same-process acknowledgement.
   * - ``AGILAB_GENERATED_CODE_PROCESS_LIMITS``
     - unset
     - Explicit evidence flag for process-mode generated-code execution. Set to
       ``1`` only when the operator has enforced CPU/RAM/time, filesystem,
       network, and secret boundaries around the generated-code process.
   * - ``AGILAB_APPS_REPOSITORY_ALLOWLIST``
     - unset
     - Comma-, semicolon-, or newline-separated list of exact reviewed
       ``APPS_REPOSITORY`` origin URLs accepted by
       ``agilab security-check --profile shared``.
   * - ``AGILAB_APPS_REPOSITORY_ALLOWLIST_FILE``
     - unset
     - Optional newline-separated allowlist file for reviewed external apps
       repository origins. ``#`` comments and blank lines are ignored.
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

- The default ``AGI_CLUSTER_SHARE`` root is user-scoped.
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

Prefer OS keyrings, enterprise vaults, or short-lived environment variables for
secrets such as ``OPENAI_API_KEY``, ``MISTRAL_API_KEY``,
``AGILAB_LLM_API_KEY``, and ``CLUSTER_CREDENTIALS``. ``$HOME/.agilab/.env`` is
a local plaintext developer convenience, not a shared secret manager. Avoid
passing secrets on the command line because shell history and process listings
can expose them.
