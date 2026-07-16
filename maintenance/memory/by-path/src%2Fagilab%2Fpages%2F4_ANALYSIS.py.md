---
schema: agilab.maintenance_memory.v1
source: src/agilab/pages/4_ANALYSIS.py
source_sha256: 3675f370822e6d6ff7f15fd6bdf1965a921517ff54200c9c4106492c8f12fc18
title: ANALYSIS page session environment and sidecar ownership contract
verified_commit: cf8058b53e5f5decd974038103f1eaf2f39c8a9d
---

# ANALYSIS page session environment and sidecar ownership contract

Hidden invariant: ANALYSIS can be opened before the main navigation bootstrap
has created `st.session_state["env"]`. It must therefore initialize the runtime
through `AgiEnv.session_for_app(...)`, never `AgiEnv.for_app(...)`, direct
`AgiEnv(...)` construction, or a borrowed `AgiEnv.current()` singleton. Each
Streamlit session owns an independently mutable environment, while the legacy
process singleton remains available to CLI callers only.

When ANALYSIS creates the environment, it must also set
`st.session_state["first_run"] = False`. Otherwise a later navigation page can
treat the warm session as cold and re-enter bootstrap.

Local notebook and view servers must be launched or reused only through the
signed process-level sidecar registry. A listening port alone is not ownership
proof: reuse requires the registered PID/start identity, stable command digest,
and listener ownership by that process tree. Hosted inline views are the one
compatibility exception; they must acquire the nonblocking process-state lease
before changing `sys.argv`, `sys.path`, or `sys.modules`, restore all three in a
`finally` block, and fail fast when another session owns the lease.

Environment preparation subprocesses are another process-owned boundary. The
page must retain the exact launch token, process-group identity, launch time,
and owner until cleanup proves both that the parent was reaped and that no
owned group or token-matched descendant remains. A wrapper exit is not cleanup
proof. TERM/KILL and waits must stay bounded, and an inaccessible recent
same-user process candidate or an unreaped parent must fail closed before the
preparation guard is released.

Regression expectation: cover built-in/default project selection,
`AgiEnv.session_for_app(...)`, `first_run=False`, cross-session inline-render
exclusion and global restoration, sidecar single-launch reuse, stale PID/port
collision rejection, a fast-exiting preparation wrapper with a surviving child,
an unreaped parent after bounded kill/wait, inaccessible owned-process evidence,
and one matching ANALYSIS browser robot scenario.

2026-07-16 re-verification: concurrent-access hardening replaced singleton
borrowing with session environments, added verified sidecar ownership, and
contained hosted inline process globals behind a fail-fast lease.

2026-07-17 re-verification: preparation ownership now survives wrapper exit,
uses bounded process-group/tree termination, and releases the cross-session
guard only after parent and descendant absence are both proven.
