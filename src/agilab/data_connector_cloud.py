# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Cloud-provider helpers for AGILAB object-storage connector contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ObjectStorageProvider:
    provider: str
    label: str
    uri_scheme: str
    runtime_dependency: str
    credential_hint: str
    aliases: tuple[str, ...] = ()


OBJECT_STORAGE_PROVIDERS: dict[str, ObjectStorageProvider] = {
    "s3": ObjectStorageProvider(
        provider="s3",
        label="AWS S3 / S3-compatible object storage",
        uri_scheme="s3",
        runtime_dependency="package:boto3",
        credential_hint=(
            "AWS_PROFILE, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, "
            "AWS_SESSION_TOKEN, or AWS_WEB_IDENTITY_TOKEN_FILE"
        ),
        aliases=("aws_s3", "amazon_s3", "s3_compatible"),
    ),
    "azure_blob": ObjectStorageProvider(
        provider="azure_blob",
        label="Azure Blob Storage",
        uri_scheme="azure_blob",
        runtime_dependency="package:azure-storage-blob",
        credential_hint="AZURE_STORAGE_CONNECTION_STRING or Azure identity environment",
    ),
    "gcs": ObjectStorageProvider(
        provider="gcs",
        label="Google Cloud Storage",
        uri_scheme="gs",
        runtime_dependency="package:google-cloud-storage",
        credential_hint="GOOGLE_APPLICATION_CREDENTIALS or application default credentials",
    ),
}

SUPPORTED_OBJECT_STORAGE_PROVIDERS = tuple(sorted(OBJECT_STORAGE_PROVIDERS))
OBJECT_STORAGE_PROVIDER_ALIASES = {
    alias: provider
    for provider, definition in OBJECT_STORAGE_PROVIDERS.items()
    for alias in definition.aliases
}
ACCEPTED_OBJECT_STORAGE_PROVIDERS = tuple(
    sorted((*OBJECT_STORAGE_PROVIDERS, *OBJECT_STORAGE_PROVIDER_ALIASES))
)


def canonical_object_storage_provider(provider: str) -> str:
    provider_name = str(provider or "").strip().lower()
    return OBJECT_STORAGE_PROVIDER_ALIASES.get(provider_name, provider_name)


def object_storage_provider(provider: str) -> ObjectStorageProvider | None:
    return OBJECT_STORAGE_PROVIDERS.get(canonical_object_storage_provider(provider))


def object_storage_runtime_dependency(provider: str) -> str:
    definition = object_storage_provider(provider)
    if definition is None:
        return f"provider_sdk:{provider or 'unspecified'}"
    return definition.runtime_dependency


def object_storage_target(connector: Mapping[str, Any]) -> str:
    provider_name = str(connector.get("provider", "") or "")
    definition = object_storage_provider(provider_name)
    scheme = definition.uri_scheme if definition is not None else provider_name
    bucket = str(
        connector.get("bucket", "")
        or connector.get("container", "")
        or ""
    )
    prefix = str(connector.get("prefix", "") or "").lstrip("/")
    if definition is not None and definition.provider == "azure_blob":
        account = str(
            connector.get("account", "")
            or connector.get("storage_account", "")
            or ""
        )
        base = f"{scheme}://{account}/{bucket}" if account else f"{scheme}://{bucket}"
    else:
        base = f"{scheme}://{bucket}"
    return f"{base}/{prefix}" if prefix else base
