"""Classified package-layout marker for the cluster distributor CLI.

Direct runtime execution delegates to the worker dispatcher CLI. The legacy
``agi_cluster.agi_distributor.cli`` shim executes the worker CLI source in the
legacy module namespace to preserve existing monkeypatch seams.
"""

from __future__ import annotations

import runpy

if __name__ == "__main__":
    runpy.run_module("agi_node.agi_dispatcher.cli", run_name="__main__")
