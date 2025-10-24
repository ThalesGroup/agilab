"""
Compatibility shim for legacy imports in tests and scripts.

Older code uses `from managers import AGI`. The AGI class now lives in
`agi_cluster.agi_distributor.agi_distributor`. Import and re-export it here so
those imports continue to work without modifying callers.
"""
try:
    from agi_cluster.agi_distributor.agi_distributor import AGI  # type: ignore
except Exception as exc:  # pragma: no cover - defensive
    raise ImportError(
        "Failed to import AGI from agi_cluster.agi_distributor.agi_distributor."
    ) from exc

