---
schema: agilab.maintenance_memory.v1
source: src/agilab/pages/4_ANALYSIS.py
source_sha256: 6d6e23a019d30ea316b75a16a7573c5bd3120049613fe95a64cdaae739e0f922
title: ANALYSIS page AgiEnv singleton contract
verified_commit: e36ef7ed89d97b8422223d7fff2cb92527086f50
---

# ANALYSIS page AgiEnv singleton contract

Hidden invariant: ANALYSIS can be opened before the main navigation bootstrap
has created `st.session_state["env"]`. It must therefore initialize the runtime
through `AgiEnv.for_app(...)`, not by direct `AgiEnv(...)` construction. Direct
construction can leave a process-global singleton initialized with an app-specific
signature and later make `_ensure_navigation_environment()` fail when it tries to
bootstrap the generic navigation environment.

When ANALYSIS creates the environment, it must also set
`st.session_state["first_run"] = False`. Otherwise a later navigation page can
treat the warm session as cold and re-enter bootstrap.

Regression expectation: tests should cover built-in project shorthand, default
project selection, `AgiEnv.for_app(...)` usage, and the `first_run` state update.
For browser-visible changes, run the matching UI robot scenario in addition to
helper tests.

2026-07-07 re-verification: centralizing Streamlit page configuration removed
the inline view `st.set_page_config` monkeypatch in this file, but preserved
`_initialize_analysis_env(...)` using `AgiEnv.for_app(...)` and setting
`st.session_state["first_run"] = False`.
