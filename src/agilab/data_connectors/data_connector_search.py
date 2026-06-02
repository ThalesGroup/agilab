# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Search-index connector helpers for ELK/OpenSearch/Hawk contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SearchIndexProvider:
    provider: str
    label: str
    runtime_dependency: str
    operation: str
    credential_hint: str
    aliases: tuple[str, ...] = ()


SEARCH_INDEX_PROVIDERS: dict[str, SearchIndexProvider] = {
    "opensearch": SearchIndexProvider(
        provider="opensearch",
        label="OpenSearch",
        runtime_dependency="python:urllib.request",
        operation="opensearch_index_head",
        credential_hint="OPENSEARCH_TOKEN or compatible bearer token",
        aliases=("aws_opensearch",),
    ),
    "elasticsearch": SearchIndexProvider(
        provider="elasticsearch",
        label="Elasticsearch / ELK",
        runtime_dependency="python:urllib.request",
        operation="elasticsearch_index_head",
        credential_hint="ELASTICSEARCH_TOKEN, ELK_TOKEN, or compatible bearer token",
        aliases=("elastic", "elk"),
    ),
    "hawk": SearchIndexProvider(
        provider="hawk",
        label="Hawk search cluster",
        runtime_dependency="python:urllib.request",
        operation="hawk_cluster_index_head",
        credential_hint="HAWK_TOKEN or compatible bearer token",
        aliases=("hawk_elk",),
    ),
}

SUPPORTED_SEARCH_INDEX_PROVIDERS = tuple(sorted(SEARCH_INDEX_PROVIDERS))
SEARCH_INDEX_PROVIDER_ALIASES = {
    alias: provider
    for provider, definition in SEARCH_INDEX_PROVIDERS.items()
    for alias in definition.aliases
}
ACCEPTED_SEARCH_INDEX_PROVIDERS = tuple(
    sorted((*SEARCH_INDEX_PROVIDERS, *SEARCH_INDEX_PROVIDER_ALIASES))
)


def canonical_search_index_provider(provider: str) -> str:
    provider_name = str(provider or "opensearch").strip().lower()
    return SEARCH_INDEX_PROVIDER_ALIASES.get(provider_name, provider_name)


def search_index_provider(provider: str) -> SearchIndexProvider | None:
    return SEARCH_INDEX_PROVIDERS.get(canonical_search_index_provider(provider))


def search_index_runtime_dependency(provider: str) -> str:
    definition = search_index_provider(provider)
    if definition is None:
        return f"provider_sdk:{provider or 'unspecified'}"
    return definition.runtime_dependency


def search_index_operation(provider: str) -> str:
    definition = search_index_provider(provider)
    if definition is None:
        return "search_index_head"
    return definition.operation


def search_endpoint(connector: Mapping[str, Any]) -> str:
    endpoint = str(
        connector.get("url", "")
        or connector.get("cluster_uri", "")
        or connector.get("endpoint", "")
        or ""
    ).strip()
    if endpoint and "://" not in endpoint:
        scheme = str(connector.get("scheme", "") or "https").strip() or "https"
        endpoint = f"{scheme}://{endpoint}"
    return endpoint.rstrip("/")


def search_index_target(connector: Mapping[str, Any]) -> str:
    endpoint = search_endpoint(connector)
    index = str(connector.get("index", "") or "").strip().lstrip("/")
    if endpoint and index:
        return f"{endpoint}/{index}"
    return endpoint or index
