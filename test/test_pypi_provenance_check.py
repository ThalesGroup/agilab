from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from urllib.error import HTTPError


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

    def fake_urlopen(request, *, timeout):
        url = request.full_url
        if url.endswith("/pypi/agi-apps/json"):
            return _json_response(
                {
                    "releases": {
                        "2026.5.14": [
                            {"filename": "agi_apps-2026.5.14-py3-none-any.whl"},
                            {"filename": "agi_apps-2026.5.14.tar.gz"},
                        ]
                    }
                }
            )
        return _json_response({"attestation_bundles": [{"attestations": [{}]}]})

    check = module.check_target(target, urlopen=fake_urlopen)

    assert check["status"] == "pass"
    assert check["reason"] == "all_files_attested"
    assert {row["status"] for row in check["files"]} == {"pass"}


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
                            {"filename": "agi_apps-2026.5.14-py3-none-any.whl"},
                        ]
                    }
                }
            )
        raise HTTPError(url, 404, "not found", hdrs=None, fp=None)

    check = module.check_target(target, urlopen=fake_urlopen)

    assert check["status"] == "fail"
    assert check["reason"] == "missing_attestation"
    assert check["files"][0]["reason"] == "provenance_http_404"
