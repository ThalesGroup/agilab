Data Connectors
===============

AGILAB data connectors are a lightweight contract for external data systems.
They let an app or evidence report reference a named data source without
hard-coding local paths, credentials, or provider-specific client details in
the app code.

The current public contract is intentionally conservative:

- connector definitions live in plain-text TOML catalogs
- credentials are referenced through environment variables, never embedded
- public evidence validates contracts without opening external networks
- live probes stay operator-triggered and optional
- legacy raw paths can remain available while apps migrate to connector IDs

This is not a second experiment tracker, model registry, or storage UI. It is
the data-access contract around AGILAB workflows.

Catalog Shape
-------------

The public sample catalog is:

- :download:`data_connectors_sample.toml <data/data_connectors_sample.toml>`
- :download:`cloud_emulator_connectors_sample.toml <data/cloud_emulator_connectors_sample.toml>`

Each connector is a ``[[connectors]]`` TOML entry with a stable ``id``, a
``kind``, a human label, and kind-specific fields.

Supported public kinds are:

.. list-table::
   :header-rows: 1
   :widths: 24 36 40

   * - Kind
     - Typical target
     - Contract boundary
   * - ``sql``
     - read-only warehouse or local SQLite proof
     - validates URI, driver, and ``query_mode = "read_only"``
   * - ``opensearch``
     - OpenSearch / ELK index
     - validates URL, index, and credential reference
   * - ``object_storage``
     - artifact prefixes in cloud object storage
     - validates provider, bucket/container, prefix, and credential reference

Object Storage Providers
------------------------

Object-storage connectors currently support these providers:

.. list-table::
   :header-rows: 1
   :widths: 20 28 26 26

   * - Provider
     - Target URI shape
     - Runtime dependency
     - Credential hint
   * - ``s3``
     - ``s3://bucket/prefix``
     - ``boto3``
     - ``AWS_PROFILE`` or AWS access-key/session environment
   * - ``azure_blob``
     - ``azure_blob://account/container/prefix``
     - ``azure-storage-blob``
     - ``AZURE_STORAGE_CONNECTION_STRING`` or Azure identity environment
   * - ``gcs``
     - ``gs://bucket/prefix``
     - ``google-cloud-storage``
     - ``GOOGLE_APPLICATION_CREDENTIALS`` or application-default credentials

The ``s3`` provider also accepts the aliases ``aws_s3``, ``amazon_s3``, and
``s3_compatible``. The runtime dependency column describes what an operator
environment needs for live probes; those packages are not required for the
default public contract-validation evidence.

Account-Free Cloud Emulator Validation
--------------------------------------

Use the ``cloud-emulators`` profile when you need AWS/Azure/GCP connector
confidence without owning cloud accounts:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/data_connector_cloud_emulator_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile cloud-emulators

The profile validates the sample emulator catalog against the same connector
facility and runtime-adapter contracts used by real cloud targets. It covers:

.. list-table::
   :header-rows: 1
   :widths: 22 26 26 26

   * - Cloud target
     - Account-free emulator
     - Local endpoint
     - What is proven
   * - AWS S3 / S3-compatible storage
     - MinIO
     - ``http://127.0.0.1:9000``
     - provider aliasing, bucket/prefix target shape, ``boto3`` dependency
   * - Azure Blob Storage
     - Azurite
     - ``http://127.0.0.1:10000/devstoreaccount1``
     - account/container target shape, ``azure-storage-blob`` dependency
   * - Google Cloud Storage
     - fake-gcs-server
     - ``http://127.0.0.1:4443``
     - ``gs://`` target shape, ``google-cloud-storage`` dependency
   * - Search-index wiring
     - local OpenSearch or Elasticsearch
     - ``http://127.0.0.1:9200``
     - URL/index contract and explicit credential boundary

This gives **API-contract and emulator-compatible validation** only. It does
not prove real IAM, cloud firewall rules, private endpoints, regional behavior,
quota, or billing. Those remain opt-in live smoke checks in a real operator
environment with real credentials.

Credential Rule
---------------

Remote connectors must use ``auth_ref = "env:NAME"``. The value points to an
environment variable name, not to the credential itself.

Examples:

.. code-block:: toml

   auth_ref = "env:AWS_PROFILE"
   auth_ref = "env:AZURE_STORAGE_CONNECTION_STRING"
   auth_ref = "env:GOOGLE_APPLICATION_CREDENTIALS"

The reports deliberately avoid materializing credential values. If a connector
contains a raw secret-like value, the facility report marks the catalog invalid.

Evidence Reports
----------------

The public checks are contract-first:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/data_connector_facility_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/data_connector_resolution_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/data_connector_health_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/data_connector_health_actions_report.py --compact
   uv --preview-features extra-build-dependencies run python tools/data_connector_runtime_adapters_report.py --compact

Use the live endpoint smoke only when you intentionally want to prove the
operator-triggered execution path. The default public mode remains network-free.

How To Read The Boundary
------------------------

- ``facility`` proves the catalog is structurally valid.
- ``resolution`` proves app/page settings can refer to connector IDs while
  preserving legacy fallback paths.
- ``health`` plans status probes but does not execute them by default.
- ``health_actions`` exposes explicit operator-triggered probe actions.
- ``runtime_adapters`` maps each connector to the dependency and operation a
  runtime would need when an operator opts in.

This keeps the first adoption path simple: a new user can run AGILAB without
cloud credentials, while an operator can still see exactly which connector,
dependency, and environment variable will be needed before enabling live access.
