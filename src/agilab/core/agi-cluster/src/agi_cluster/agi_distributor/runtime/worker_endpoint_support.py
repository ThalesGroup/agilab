"""Canonical parsing for configured and Dask worker endpoints."""

from __future__ import annotations

import ipaddress
from typing import Any


def _normalize_host(host: str) -> str:
    value = host.strip()
    if not value:
        return ""
    try:
        return ipaddress.ip_address(value).compressed
    except ValueError:
        return value.lower()


def worker_host(worker: Any) -> str:
    """Return a normalized host without credentials, scheme, brackets, or port.

    Unbracketed IPv6 values are treated as raw host literals. IPv6 endpoints
    carrying a port must use the standard bracketed form (``[host]:port``), as
    an unbracketed IPv6 address ending in decimal text is inherently ambiguous.
    """

    value = str(worker or "").strip()
    if "://" in value:
        value = value.rsplit("://", 1)[-1]
    if "@" in value:
        value = value.rsplit("@", 1)[-1]
    if value.startswith("["):
        closing_bracket = value.find("]")
        if closing_bracket < 0:
            return ""
        return _normalize_host(value[1:closing_bracket])
    if value.count(":") == 1:
        value = value.split(":", 1)[0]
    return _normalize_host(value)


__all__ = ["worker_host"]
