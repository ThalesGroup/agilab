from __future__ import annotations

import base64
import importlib.util
import io
import json
import sys
from pathlib import Path
from urllib.error import HTTPError

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "pypi_provenance_check.py"
sys.path.insert(0, str(REPO_ROOT / "tools"))


def _load_module():
    spec = importlib.util.spec_from_file_location("pypi_provenance_check", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _json_response(payload: dict) -> _Response:
    return _Response(json.dumps(payload).encode("utf-8"))


def _valid_provenance_payload(
    *,
    filename: str = "agilab-2026.7.31-py3-none-any.whl",
    sha256: str = "a" * 64,
    repository: str = "ThalesGroup/agilab",
    workflow: str = "pypi-publish.yaml",
) -> dict:
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": filename, "digest": {"sha256": sha256}}],
        "predicateType": "https://docs.pypi.org/attestations/publish/v1",
        "predicate": None,
    }
    return {
        "version": 1,
        "attestation_bundles": [
            {
                "publisher": {
                    "environment": "release",
                    "kind": "GitHub",
                    "repository": repository,
                    "workflow": workflow,
                },
                "attestations": [
                    {
                        "version": 1,
                        "envelope": {
                            "signature": "synthetic-signature",
                            "statement": base64.b64encode(
                                json.dumps(statement).encode("utf-8")
                            ).decode("ascii"),
                        },
                        "verification_material": {
                            "certificate": "synthetic-certificate",
                            "transparency_entries": [{"logIndex": "1"}],
                        },
                    }
                ],
            }
        ],
    }


def test_release_targets_use_publishable_package_versions() -> None:
    module = _load_module()

    targets = module.release_targets(
        repo_root=REPO_ROOT,
        package_names=["agi-apps", "agi-app-mission-decision", "agilab"],
    )

    assert [target.name for target in targets] == [
        "agi-app-mission-decision",
        "agi-apps",
        "agilab",
    ]
    assert all(target.version for target in targets)


def test_check_target_passes_when_each_distribution_has_attestation() -> None:
    module = _load_module()
    target = module.ReleaseTarget("agi-apps", "2026.05.14", "src/agilab/lib/agi-apps")
    wheel = "agi_apps-2026.5.14-py3-none-any.whl"
    sdist = "agi_apps-2026.5.14.tar.gz"
    wheel_sha256 = "a" * 64
    sdist_sha256 = "b" * 64

    def fake_urlopen(request, *, timeout):
        url = request.full_url
        if url.endswith("/pypi/agi-apps/json"):
            return _json_response(
                {
                    "releases": {
                        "2026.5.14": [
                            {"filename": wheel, "digests": {"sha256": wheel_sha256}},
                            {"filename": sdist, "digests": {"sha256": sdist_sha256}},
                        ]
                    }
                }
            )
        if wheel in url:
            return _json_response(
                _valid_provenance_payload(filename=wheel, sha256=wheel_sha256)
            )
        return _json_response(
            _valid_provenance_payload(filename=sdist, sha256=sdist_sha256)
        )

    check = module.check_target(target, urlopen=fake_urlopen)

    assert check["status"] == "pass"
    assert check["reason"] == "all_files_provenance_bound"
    assert {row["status"] for row in check["files"]} == {"pass"}
    assert {row["sha256"] for row in check["files"]} == {
        wheel_sha256,
        sdist_sha256,
    }


def test_attestation_validator_rejects_malformed_or_incomplete_payloads() -> None:
    module = _load_module()

    malformed_payloads = [
        None,
        {},
        {"version": 1, "attestation_bundles": [{}]},
        {
            "version": 1,
            "attestation_bundles": [
                {
                    "publisher": {
                        "environment": "release",
                        "kind": "GitHub",
                        "repository": "ThalesGroup/agilab",
                        "workflow": "pypi-publish.yaml",
                    },
                    "attestations": [{}],
                }
            ],
        },
        {"provenance": [{"arbitrary": True}]},
    ]
    for payload in malformed_payloads:
        assert (
            module._has_attestation(
                payload,
                expected_filename="agilab-2026.7.31-py3-none-any.whl",
                expected_sha256="a" * 64,
            )
            is False
        )
        assert module._attestation_validation_error(
            payload,
            expected_filename="agilab-2026.7.31-py3-none-any.whl",
            expected_sha256="a" * 64,
        )

    assert (
        module._has_attestation(
            _valid_provenance_payload(),
            expected_filename="agilab-2026.7.31-py3-none-any.whl",
            expected_sha256="a" * 64,
        )
        is True
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "publisher_kind",
        "publisher_repository",
        "publisher_workflow",
        "subject_filename",
        "subject_digest",
        "invalid_base64",
        "statement_type",
        "predicate_type",
    ],
)
def test_attestation_validator_binds_publisher_filename_and_digest(
    mutation: str,
) -> None:
    module = _load_module()
    filename = "agilab-2026.7.31-py3-none-any.whl"
    sha256 = "a" * 64
    payload = _valid_provenance_payload(filename=filename, sha256=sha256)
    bundle = payload["attestation_bundles"][0]
    envelope = bundle["attestations"][0]["envelope"]
    if mutation.startswith("publisher_"):
        field = mutation.removeprefix("publisher_")
        bundle["publisher"][field] = "wrong-value"
    elif mutation == "invalid_base64":
        envelope["statement"] = "not base64!"
    else:
        statement = json.loads(base64.b64decode(envelope["statement"]))
        if mutation == "subject_filename":
            statement["subject"][0]["name"] = "other.whl"
        elif mutation == "subject_digest":
            statement["subject"][0]["digest"]["sha256"] = "b" * 64
        elif mutation == "statement_type":
            statement["_type"] = "https://in-toto.io/Statement/v0.1"
        elif mutation == "predicate_type":
            statement["predicateType"] = "https://example.invalid/predicate"
        envelope["statement"] = base64.b64encode(
            json.dumps(statement).encode("utf-8")
        ).decode("ascii")

    error = module._attestation_validation_error(
        payload,
        expected_filename=filename,
        expected_sha256=sha256,
    )
    assert error is not None


@pytest.mark.parametrize("sha256", [None, "not-a-sha256"])
def test_release_files_reject_missing_or_malformed_pypi_digest(sha256: str | None) -> None:
    module = _load_module()
    payload = {
        "releases": {
            "1.0": [
                {
                    "filename": "agilab-1.0-py3-none-any.whl",
                    "digests": {"sha256": sha256},
                }
            ]
        }
    }

    actual_version, release_files, error = module._release_files(payload, "1.0")

    assert actual_version == "1.0"
    assert release_files == []
    assert error and "digests.sha256 is invalid" in error


def test_check_target_rejects_incomplete_attestation_bundle() -> None:
    module = _load_module()
    target = module.ReleaseTarget("agi-apps", "2026.05.14", "src/agilab/lib/agi-apps")

    def fake_urlopen(request, *, timeout):
        if request.full_url.endswith("/pypi/agi-apps/json"):
            return _json_response(
                {
                    "releases": {
                        "2026.5.14": [
                            {
                                "filename": "agi_apps-2026.5.14-py3-none-any.whl",
                                "digests": {"sha256": "a" * 64},
                            },
                        ]
                    }
                }
            )
        return _json_response({"version": 1, "attestation_bundles": [{}]})

    check = module.check_target(target, urlopen=fake_urlopen)

    assert check["status"] == "fail"
    assert check["files"][0]["reason"] == "provenance_invalid"
    assert "publisher is incomplete" in check["files"][0]["validation_error"]


def test_check_target_fails_when_provenance_endpoint_is_missing() -> None:
    module = _load_module()
    target = module.ReleaseTarget("agi-apps", "2026.05.14", "src/agilab/lib/agi-apps")

    def fake_urlopen(request, *, timeout):
        url = request.full_url
        if url.endswith("/pypi/agi-apps/json"):
            return _json_response(
                {
                    "releases": {
                        "2026.5.14": [
                            {
                                "filename": "agi_apps-2026.5.14-py3-none-any.whl",
                                "digests": {"sha256": "a" * 64},
                            },
                        ]
                    }
                }
            )
        raise HTTPError(url, 404, "not found", hdrs=None, fp=None)

    check = module.check_target(target, urlopen=fake_urlopen)

    assert check["status"] == "fail"
    assert check["reason"] == "provenance_invalid"
    assert check["files"][0]["reason"] == "provenance_http_404"


def test_check_target_with_retries_waits_for_pypi_release_visibility() -> None:
    module = _load_module()
    target = module.ReleaseTarget("agilab", "2026.05.15", ".")
    calls = {"json": 0}

    def fake_urlopen(request, *, timeout):
        url = request.full_url
        if url.endswith("/pypi/agilab/json"):
            calls["json"] += 1
            if calls["json"] == 1:
                return _json_response({"releases": {}})
            return _json_response(
                {
                    "releases": {
                        "2026.5.15": [
                            {
                                "filename": "agilab-2026.5.15-py3-none-any.whl",
                                "digests": {"sha256": "a" * 64},
                            },
                        ]
                    }
                }
            )
        return _json_response(
            _valid_provenance_payload(
                filename="agilab-2026.5.15-py3-none-any.whl",
                sha256="a" * 64,
            )
        )

    check = module.check_target_with_retries(
        target,
        attempts=2,
        retry_delay=0,
        sleep=lambda _seconds: None,
        urlopen=fake_urlopen,
    )

    assert check["status"] == "pass"
    assert check["attempt"] == 2
    assert check["previous_failures"] == [
        {"attempt": 1, "reason": "release_missing", "status": "fail"}
    ]


def test_check_target_with_retries_waits_for_pypi_json_404_after_upload() -> None:
    module = _load_module()
    target = module.ReleaseTarget("agi-apps", "2026.05.15", "src/agilab/lib/agi-apps")
    calls = {"json": 0}

    def fake_urlopen(request, *, timeout):
        url = request.full_url
        if url.endswith("/pypi/agi-apps/json"):
            calls["json"] += 1
            if calls["json"] == 1:
                raise HTTPError(url, 404, "not found", hdrs=None, fp=None)
            return _json_response(
                {
                    "releases": {
                        "2026.5.15": [
                            {
                                "filename": "agi_apps-2026.5.15-py3-none-any.whl",
                                "digests": {"sha256": "a" * 64},
                            },
                        ]
                    }
                }
            )
        return _json_response(
            _valid_provenance_payload(
                filename="agi_apps-2026.5.15-py3-none-any.whl",
                sha256="a" * 64,
            )
        )

    check = module.check_target_with_retries(
        target,
        attempts=2,
        retry_delay=0,
        sleep=lambda _seconds: None,
        urlopen=fake_urlopen,
    )

    assert check["status"] == "pass"
    assert check["attempt"] == 2
    assert check["previous_failures"] == [
        {"attempt": 1, "reason": "pypi_json_http_404", "status": "fail"}
    ]
