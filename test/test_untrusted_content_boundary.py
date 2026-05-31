from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agilab import untrusted_content_boundary


def test_untrusted_content_boundary_hashes_payload_and_writes_manifest(tmp_path: Path):
    payload = b'{"cells": []}'
    manifest_path = tmp_path / "source.ipynb.untrusted-content.json"

    written = untrusted_content_boundary.write_untrusted_content_manifest(
        manifest_path,
        payload,
        source_kind="uploaded_notebook",
        source_name="source.ipynb",
        mime_type="application/x-ipynb+json",
    )

    assert written == manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == untrusted_content_boundary.UNTRUSTED_CONTENT_BOUNDARY_SCHEMA
    assert manifest["source"]["kind"] == "uploaded_notebook"
    assert manifest["trust"]["review_required"] is True
    assert manifest["content"]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert "Untrusted content boundary" in untrusted_content_boundary.untrusted_content_notice(manifest)


def test_external_source_boundary_marks_repository_as_untrusted(tmp_path: Path):
    apps_repo = tmp_path / "apps-repo"
    apps_repo.mkdir()

    boundary = untrusted_content_boundary.build_external_source_boundary(
        apps_repo,
        source_kind="external_app_repository",
        source_name="APPS_REPOSITORY",
    )

    assert boundary["schema"] == untrusted_content_boundary.UNTRUSTED_CONTENT_BOUNDARY_SCHEMA
    assert boundary["source"]["kind"] == "external_app_repository"
    assert boundary["trust"]["status"] == "untrusted"
    assert boundary["trust"]["review_required"] is True
    assert boundary["metadata"]["exists"] is True
    assert boundary["metadata"]["is_dir"] is True
    assert boundary["content"]["sha256_scope"] == "resolved_path"
