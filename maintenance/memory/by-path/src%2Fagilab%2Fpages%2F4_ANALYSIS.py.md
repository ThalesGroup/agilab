---
schema: agilab.maintenance_memory.v1
source: src/agilab/pages/4_ANALYSIS.py
source_sha256: 1ccdd3805f9dd0a6a06d074ed5895895eee10154ad5cfb89042ba6bfda8e453f
title: ANALYSIS page AgiEnv singleton contract
verified_commit: d954f4868bc69ebc957f2b3cd0f428c2fda6d16f
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
