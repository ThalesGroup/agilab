---
schema: agilab.maintenance_memory.v1
source: src/agilab/pages/4_ANALYSIS.py
source_sha256: 7ff5680f3f0c4a4c49e421d1d5133c7dd5b23a26cd78d8a58f4801485854f065
title: ANALYSIS page AgiEnv singleton contract
verified_commit: c722f7a9603487715f8d13b6a1ce63d743cde3b9
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
