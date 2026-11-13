from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "shared_go_gate.py"
SPEC = importlib.util.spec_from_file_location("agilab_shared_go_gate", TOOL_PATH)
assert SPEC and SPEC.loader
shared_go_gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = shared_go_gate
SPEC.loader.exec_module(shared_go_gate)
NOW = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
MISSING = object()


def _write_json(path: Path, payload: object, *, now: datetime = NOW) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    os.utime(path, (now.timestamp(), now.timestamp()))


def _security_report(*, profile: str = "shared", now: datetime = NOW) -> dict:
    checks = [
        {
            "id": name,
            "label": name.replace("_", " ").title(),
            "status": "pass",
            "summary": "Isolated test evidence.",
            "remediation": "",
            "details": {},
        }
        for name in (
            "apps_repository",
            "persisted_secrets",
            "cluster_share",
            "ui_exposure",
            "generated_code_execution",
            "optional_profiles",
            "supply_chain_artifacts",
        )
    ]
    return {
        "schema": "agilab.security_check.v1",
        "schema_version": 1,
        "kind": "agilab.security_check",
        "status": "pass",
        "generated_at": now.isoformat(),
        "summary": {
            "profile": profile,
            "check_count": len(checks),
            "warnings": 0,
            "failures": 0,
            "advisory": True,
            "env_file": "isolated/.env",
        },
        "checks": checks,
    }


def _audit_payload() -> dict:
    return {"dependencies": [{"name": "demo-package", "version": "1.0", "vulns": []}]}


def _sbom_payload() -> dict:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "components": [
            {
                "type": "library",
                "name": "demo-package",
                "version": "1.0",
                "purl": "pkg:pypi/demo-package@1.0",
            }
        ],
    }


def _write_evidence(
    root: Path, *, profile: str = "shared", now: datetime = NOW
) -> tuple[Path, Path]:
    security = root / "security-check.json"
    supply_chain = root / "supply-chain"
    _write_json(security, _security_report(profile=profile, now=now), now=now)
    profile_dir = supply_chain / "base"
    _write_json(profile_dir / "pip-audit.json", _audit_payload(), now=now)
    _write_json(profile_dir / "sbom-cyclonedx.json", _sbom_payload(), now=now)
    for name in ("requirements.txt", "requirements-audit.txt"):
        path = profile_dir / name
        path.write_text("demo-package==1.0\n", encoding="utf-8")
        os.utime(path, (now.timestamp(), now.timestamp()))
    return security, supply_chain


def _gate(security: Path, supply_chain: Path, **kwargs) -> dict:
    return shared_go_gate.build_gate(
        security_check_json=security,
        supply_chain_dir=supply_chain,
        install_profiles=("base",),
        now=NOW,
        **kwargs,
    )


@pytest.mark.parametrize("profile", ["shared", "cluster", "public-ui"])
def test_shared_go_gate_passes_with_clean_security_and_fresh_profile_artifacts(
    tmp_path: Path, profile: str
):
    security, supply_chain = _write_evidence(tmp_path, profile=profile)
    gate = _gate(security, supply_chain)
    assert gate["schema"] == shared_go_gate.SCHEMA
    assert gate["decision"] == "go"
    assert gate["checks"]["security_check"]["status"] == "pass"
    assert gate["checks"]["supply_chain"]["profiles"]["base"]["status"] == "pass"


def test_invalid_local_report_and_empty_artifacts_cannot_go(
    tmp_path: Path, monkeypatch
):
    security, supply_chain = _write_evidence(tmp_path)
    _write_json(
        security,
        {
            "status": "pass",
            "summary": {"profile": "local", "warnings": 0, "failures": 0},
        },
    )
    _write_json(supply_chain / "base" / "pip-audit.json", {})
    _write_json(supply_chain / "base" / "sbom-cyclonedx.json", {})
    gate = _gate(security, supply_chain)
    assert gate["decision"] == "blocked"
    assert gate["summary"]["failed_checks"] == ["security_check", "supply_chain"]

    monkeypatch.setattr(shared_go_gate, "_utc_now", lambda: NOW)
    assert (
        shared_go_gate.main(
            [
                "--security-check-json",
                str(security),
                "--supply-chain-dir",
                str(supply_chain),
                "--output",
                str(tmp_path / "blocked-shared-go.json"),
                "--strict",
            ]
        )
        == 1
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", MISSING),
        ("schema", "unrelated.v1"),
        ("schema_version", MISSING),
        ("schema_version", True),
        ("schema_version", 2),
        ("kind", MISSING),
        ("kind", "unrelated"),
        ("status", MISSING),
        ("status", "warn"),
        ("status", "fail"),
        ("generated_at", MISSING),
        ("generated_at", None),
        ("generated_at", "invalid"),
        ("generated_at", NOW.replace(tzinfo=None).isoformat()),
        ("generated_at", (NOW - timedelta(days=31)).isoformat()),
        ("generated_at", (NOW + timedelta(seconds=1)).isoformat()),
        ("summary", MISSING),
        ("summary", []),
        ("summary.profile", "local"),
        ("summary.profile", "unknown"),
        ("summary.profile", MISSING),
        ("summary.check_count", MISSING),
        ("summary.check_count", 0),
        ("summary.check_count", 6),
        ("summary.check_count", 8),
        ("summary.check_count", True),
        ("summary.check_count", "7"),
        ("summary.warnings", MISSING),
        ("summary.warnings", 1),
        ("summary.warnings", False),
        ("summary.failures", MISSING),
        ("summary.failures", 1),
        ("summary.failures", False),
        ("summary.advisory", MISSING),
        ("summary.advisory", "true"),
        ("checks", MISSING),
        ("checks", []),
        ("checks", {}),
        ("checks", [None] * 7),
        ("checks", [{"status": "unknown"}] * 7),
        ("checks", [{"status": "warn"}] * 7),
        ("checks", [{"status": "fail"}] * 7),
    ],
)
def test_shared_go_gate_rejects_invalid_security_evidence(
    tmp_path: Path, field: str, value: object
):
    security, supply_chain = _write_evidence(tmp_path)
    payload = _security_report()
    keys = field.split(".")
    target = payload if len(keys) == 1 else payload[keys[0]]
    if value is MISSING:
        target.pop(keys[-1])
    else:
        target[keys[-1]] = value
    _write_json(security, payload)
    gate = _gate(security, supply_chain)
    assert gate["decision"] == "blocked"
    assert gate["summary"]["failed_checks"] == ["security_check"]


@pytest.mark.parametrize("payload", [[], None, "pass"])
def test_shared_go_gate_rejects_non_object_security_report(
    tmp_path: Path, payload: object
):
    security, supply_chain = _write_evidence(tmp_path)
    _write_json(security, payload)
    assert _gate(security, supply_chain)["decision"] == "blocked"


def test_shared_go_gate_accepts_aware_offset_and_age_boundary(tmp_path: Path):
    security, supply_chain = _write_evidence(tmp_path)
    payload = _security_report(now=NOW - timedelta(days=30))
    payload["generated_at"] = (
        (NOW - timedelta(days=30)).astimezone(timezone(timedelta(hours=2))).isoformat()
    )
    _write_json(security, payload)
    for path in sorted((supply_chain / "base").iterdir()):
        timestamp = (NOW - timedelta(days=30)).timestamp()
        os.utime(path, (timestamp, timestamp))
    assert _gate(security, supply_chain)["decision"] == "go"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        {"dependencies": []},
        {"dependencies": [None]},
        {"dependencies": [{"name": "demo-package", "version": "1.0"}]},
        {"dependencies": [{"name": "demo-package", "version": "1.0", "vulns": {}}]},
        {"dependencies": [{"name": "demo-package", "version": "1.0", "vulns": [{}]}]},
        {"dependencies": [{"name": "demo-package", "version": "2.0", "vulns": []}]},
        {"dependencies": [{"name": "other", "version": "1.0", "vulns": []}]},
        {"dependencies": _audit_payload()["dependencies"] * 2},
        {
            "dependencies": [
                {
                    "name": "demo-package",
                    "version": "1.0",
                    "vulns": [
                        {
                            "id": "TEST-0001",
                            "aliases": [],
                            "fix_versions": ["2.0"],
                            "description": "Synthetic known vulnerability.",
                        }
                    ],
                }
            ]
        },
    ],
)
def test_shared_go_gate_rejects_invalid_or_vulnerable_audit(
    tmp_path: Path, payload: object
):
    security, supply_chain = _write_evidence(tmp_path)
    _write_json(supply_chain / "base" / "pip-audit.json", payload)
    gate = _gate(security, supply_chain)
    assert gate["decision"] == "blocked"
    assert (
        gate["checks"]["supply_chain"]["profiles"]["base"]["pip_audit"]["status"]
        == "fail"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        {"bomFormat": "SPDX", "components": _sbom_payload()["components"]},
        {"bomFormat": "CycloneDX"},
        {"bomFormat": "CycloneDX", "components": []},
        {"bomFormat": "CycloneDX", "components": [None]},
        {"bomFormat": "CycloneDX", "components": [{"name": "demo-package"}]},
        {
            "bomFormat": "CycloneDX",
            "components": [
                {"name": "demo-package", "version": "1.0", "purl": "pkg:pypi/other@1.0"}
            ],
        },
        {
            "bomFormat": "CycloneDX",
            "components": [
                {
                    "name": "demo-package",
                    "version": "2.0",
                    "purl": "pkg:pypi/demo-package@2.0",
                }
            ],
        },
        {"bomFormat": "CycloneDX", "components": _sbom_payload()["components"] * 2},
        {**_sbom_payload(), "vulnerabilities": [{"id": "TEST-0001"}]},
        {**_sbom_payload(), "vulnerabilities": {}},
        {**_sbom_payload(), "vulnerabilities": None},
    ],
)
def test_shared_go_gate_rejects_invalid_or_mismatched_sbom(
    tmp_path: Path, payload: object
):
    security, supply_chain = _write_evidence(tmp_path)
    _write_json(supply_chain / "base" / "sbom-cyclonedx.json", payload)
    gate = _gate(security, supply_chain)
    assert gate["decision"] == "blocked"
    assert (
        gate["checks"]["supply_chain"]["profiles"]["base"]["sbom"]["status"] == "fail"
    )


@pytest.mark.parametrize(
    "name",
    [
        "pip-audit.json",
        "sbom-cyclonedx.json",
        "requirements.txt",
        "requirements-audit.txt",
    ],
)
@pytest.mark.parametrize("problem", ["missing", "invalid", "stale", "future"])
def test_shared_go_gate_rejects_bad_or_missing_scan_files(
    tmp_path: Path, name: str, problem: str
):
    security, supply_chain = _write_evidence(tmp_path)
    path = supply_chain / "base" / name
    if problem == "missing":
        path.unlink()
    elif problem == "invalid":
        path.write_bytes(b"\xff")
    else:
        timestamp = (
            NOW - timedelta(days=31)
            if problem == "stale"
            else NOW + timedelta(seconds=1)
        ).timestamp()
        os.utime(path, (timestamp, timestamp))
    gate = _gate(security, supply_chain)
    assert gate["decision"] == "blocked"
    assert gate["summary"]["failed_checks"] == ["supply_chain"]


@pytest.mark.parametrize("manifest", ["requirements.txt", "requirements-audit.txt"])
@pytest.mark.parametrize(
    "contents",
    [
        "",
        "demo-package>=1.0\n",
        "demo-package==2.0\n",
        "other==1.0\n",
        "demo-package==1.0\ndemo-package==1.0\n",
        "demo-package @ https://example.invalid/demo-package.whl\n",
    ],
)
def test_shared_go_gate_binds_both_requirements_manifests(
    tmp_path: Path, manifest: str, contents: str
):
    security, supply_chain = _write_evidence(tmp_path)
    path = supply_chain / "base" / manifest
    path.write_text(contents, encoding="utf-8")
    os.utime(path, (NOW.timestamp(), NOW.timestamp()))
    assert _gate(security, supply_chain)["decision"] == "blocked"


def _add_editable_and_inactive_pin(supply_chain: Path) -> None:
    directory = supply_chain / "base"
    for name in ("requirements.txt", "requirements-audit.txt"):
        path = directory / name
        contents = 'demo-package==1.0\ninactive-package==2.0; python_version < "1"\n'
        if name == "requirements.txt":
            contents += "-e ./local-project\n"
        path.write_text(contents, encoding="utf-8")
        os.utime(path, (NOW.timestamp(), NOW.timestamp()))
    payload = _sbom_payload()
    payload["components"].extend(
        [
            {
                "type": "library",
                "name": "inactive-package",
                "version": "2.0",
                "purl": "pkg:pypi/inactive-package@2.0",
            },
            {
                "bom-ref": "requirements-L3",
                "description": "requirements line 3: -e ./local-project",
                "externalReferences": [
                    {
                        "comment": "explicit local path",
                        "type": "other",
                        "url": "./local-project",
                    }
                ],
                "name": "unknown",
                "type": "library",
            },
        ]
    )
    _write_json(directory / "sbom-cyclonedx.json", payload)


def test_shared_go_gate_uses_separate_audit_sbom_and_editable_inventories(
    tmp_path: Path,
):
    security, supply_chain = _write_evidence(tmp_path)
    _add_editable_and_inactive_pin(supply_chain)
    # pip-audit contains active pins only; CycloneDX contains all pins and editables.
    _write_json(
        supply_chain / "base" / "pip-audit.json", _audit_payload()["dependencies"]
    )
    assert _gate(security, supply_chain)["decision"] == "go"


@pytest.mark.parametrize(
    "problem", ["missing", "changed", "duplicate", "audit-editable", "audit-pin"]
)
def test_shared_go_gate_rejects_inventory_drift_with_editables(
    tmp_path: Path, problem: str
):
    security, supply_chain = _write_evidence(tmp_path)
    _add_editable_and_inactive_pin(supply_chain)
    directory = supply_chain / "base"
    sbom_path = directory / "sbom-cyclonedx.json"
    payload = json.loads(sbom_path.read_text(encoding="utf-8"))
    if problem == "missing":
        payload["components"].pop()
    elif problem == "changed":
        payload["components"][-1]["externalReferences"][0]["url"] = (
            "./different-project"
        )
    elif problem == "duplicate":
        payload["components"].append(deepcopy(payload["components"][-1]))
    else:
        audit_requirements = directory / "requirements-audit.txt"
        contents = audit_requirements.read_text(encoding="utf-8")
        contents += (
            "-e ./local-project\n" if problem == "audit-editable" else "extra==3.0\n"
        )
        audit_requirements.write_text(contents, encoding="utf-8")
        os.utime(audit_requirements, (NOW.timestamp(), NOW.timestamp()))
    _write_json(sbom_path, payload)
    assert _gate(security, supply_chain)["decision"] == "blocked"


@pytest.mark.parametrize(
    "max_age_days", [-1, 0, True, "30", float("inf"), float("nan")]
)
def test_shared_go_gate_rejects_invalid_age_limit(tmp_path: Path, max_age_days: object):
    security, supply_chain = _write_evidence(tmp_path)
    with pytest.raises(ValueError, match="max_age_days"):
        _gate(security, supply_chain, max_age_days=max_age_days)


def test_shared_go_gate_rejects_naive_evaluation_time(tmp_path: Path):
    security, supply_chain = _write_evidence(tmp_path)
    with pytest.raises(ValueError, match="timezone"):
        shared_go_gate.build_gate(
            security_check_json=security,
            supply_chain_dir=supply_chain,
            install_profiles=("base",),
            now=NOW.replace(tzinfo=None),
        )


@pytest.mark.parametrize("profiles", [(), ("unknown",)])
def test_shared_go_gate_requires_known_install_profiles(
    tmp_path: Path, profiles: tuple
):
    security, supply_chain = _write_evidence(tmp_path)
    with pytest.raises(ValueError, match="install_profiles"):
        shared_go_gate.build_gate(
            security_check_json=security,
            supply_chain_dir=supply_chain,
            install_profiles=profiles,
            now=NOW,
        )


@pytest.mark.parametrize("artifact", ["security", "audit", "sbom", "requirements"])
def test_shared_go_gate_does_not_echo_untrusted_payload_secrets(
    tmp_path: Path, artifact: str
):
    security, supply_chain = _write_evidence(tmp_path)
    secret = "synthetic-private-payload-value"
    if artifact == "security":
        payload = _security_report()
        payload["schema"] = secret
        payload["summary"]["profile"] = secret
        _write_json(security, payload)
    elif artifact == "requirements":
        path = supply_chain / "base" / "requirements.txt"
        path.write_text(
            "demo-package @ https://example.invalid/" + secret, encoding="utf-8"
        )
        os.utime(path, (NOW.timestamp(), NOW.timestamp()))
    else:
        filename = "pip-audit.json" if artifact == "audit" else "sbom-cyclonedx.json"
        path = supply_chain / "base" / filename
        if artifact == "audit":
            payload = _audit_payload()
            payload["dependencies"][0]["name"] = secret
            _write_json(path, payload)
        else:
            path.write_text('{"components": "' + secret, encoding="utf-8")
            os.utime(path, (NOW.timestamp(), NOW.timestamp()))
    gate = _gate(security, supply_chain)
    assert gate["decision"] == "blocked"
    assert secret not in json.dumps(gate)


def test_shared_go_gate_blocks_missing_supply_chain_and_strict_cli_returns_nonzero(
    tmp_path: Path, monkeypatch
):
    security, _ = _write_evidence(tmp_path)
    output = tmp_path / "shared_go_gate.json"
    monkeypatch.setattr(shared_go_gate, "_utc_now", lambda: NOW)
    rc = shared_go_gate.main(
        [
            "--security-check-json",
            str(security),
            "--supply-chain-dir",
            str(tmp_path / "missing-supply-chain"),
            "--output",
            str(output),
            "--strict",
        ]
    )
    assert rc == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["decision"] == "blocked"
    assert payload["summary"]["failed_checks"] == ["supply_chain"]


@pytest.mark.parametrize(
    "invocation", [[str(TOOL_PATH)], ["-m", "tools.shared_go_gate"]]
)
def test_shared_go_gate_strict_cli_rejects_then_continues_with_valid_evidence(
    tmp_path: Path, invocation: list[str]
):
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    security, supply_chain = _write_evidence(tmp_path, now=now)
    output = tmp_path / "shared_go_gate.json"
    args = [
        sys.executable,
        *invocation,
        "--security-check-json",
        str(security),
        "--supply-chain-dir",
        str(supply_chain),
        "--install-profile",
        "base",
        "--output",
        str(output),
        "--strict",
    ]
    _write_json(supply_chain / "base" / "pip-audit.json", {}, now=now)
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    working_dir = ROOT if invocation[0] == "-m" else tmp_path
    invalid = subprocess.run(
        args,
        cwd=working_dir,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert invalid.returncode == 1, invalid.stderr
    assert json.loads(output.read_text())["decision"] == "blocked"
    _write_json(supply_chain / "base" / "pip-audit.json", _audit_payload(), now=now)
    valid = subprocess.run(
        args,
        cwd=working_dir,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert valid.returncode == 0, valid.stderr
    assert json.loads(output.read_text())["decision"] == "go"


def test_shared_go_gate_strict_cli_rejects_invalid_age_limit(tmp_path: Path):
    with pytest.raises(SystemExit) as error:
        shared_go_gate.main(["--artifact-max-age-days", "-1", "--strict"])
    assert error.value.code == 2


@pytest.mark.parametrize("problem", ["missing", "invalid-json"])
def test_shared_go_gate_rejects_unreadable_security_report(
    tmp_path: Path, problem: str
):
    security, supply_chain = _write_evidence(tmp_path)
    if problem == "missing":
        security.unlink()
    else:
        security.write_bytes(b"\xff")
    gate = _gate(security, supply_chain)
    assert gate["decision"] == "blocked"
    assert gate["summary"]["failed_checks"] == ["security_check"]


NONREGULAR_INPUTS = (
    "security-check.json",
    "supply-chain/base/requirements.txt",
    "supply-chain/base/requirements-audit.txt",
    "supply-chain/base/pip-audit.json",
    "supply-chain/base/sbom-cyclonedx.json",
)


@pytest.mark.skipif(os.name != "posix", reason="POSIX FIFO regression")
@pytest.mark.parametrize("relative_path", NONREGULAR_INPUTS)
@pytest.mark.parametrize("symlink", [False, True], ids=["fifo", "symlink-to-fifo"])
def test_shared_go_gate_rejects_static_fifo_without_reading(
    tmp_path: Path, relative_path: str, symlink: bool
):
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    security, supply_chain = _write_evidence(tmp_path, now=now)
    target = tmp_path / relative_path
    target.unlink()
    fifo = tmp_path / "agilab-gate-nonregular-input.fifo" if symlink else target
    os.mkfifo(fifo)
    if symlink:
        target.symlink_to(fifo)
    output = tmp_path / "agilab-gate-nonregular-result.json"
    # A read spy proves the rejected path is never opened. The process deadline
    # also bounds a regression that bypasses this particular read surface.
    script = """
import json, pathlib, sys
from tools import shared_go_gate
target = pathlib.Path(sys.argv[1])
original = pathlib.Path.read_text
def read_text(path, *args, **kwargs):
    if path == target:
        raise AssertionError("nonregular artifact must not be read")
    return original(path, *args, **kwargs)
pathlib.Path.read_text = read_text
code = shared_go_gate.main([
    "--security-check-json", sys.argv[2], "--supply-chain-dir", sys.argv[3],
    "--output", sys.argv[4], "--strict"
])
assert code == 1
assert json.loads(original(pathlib.Path(sys.argv[4])))["decision"] == "blocked"
raise SystemExit(code)
"""
    # subprocess.run kills and waits for its own child on timeout.
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(target),
            str(security),
            str(supply_chain),
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert child.returncode == 1, child.stderr
    assert child.stderr == ""
    gate = json.loads(output.read_text())
    assert gate["decision"] == "blocked"
    assert "not a regular file" in json.dumps(gate)


@pytest.mark.parametrize("relative_path", NONREGULAR_INPUTS)
def test_shared_go_gate_accepts_regular_symlink_inputs(
    tmp_path: Path, relative_path: str
):
    security, supply_chain = _write_evidence(tmp_path)
    target = tmp_path / relative_path
    regular = tmp_path / "agilab-gate-regular-artifact"
    target.rename(regular)
    target.symlink_to(regular)
    assert _gate(security, supply_chain)["decision"] == "go"


@pytest.fixture
def registered_source_evidence(tmp_path: Path):
    from tools import profile_supply_chain_scan as producer

    security, supply_chain = _write_evidence(tmp_path)
    directory = supply_chain / "packaged-projects"
    (supply_chain / "base").rename(directory)
    sources = dict(list(producer.first_party_sources().items())[:2])
    requirements = directory / "requirements.txt"
    requirements.write_text(
        "demo-package==1.0\n"
        + "".join(f"{name} @ {source['uri']}\n" for name, source in sources.items())
    )
    producer.write_pip_audit_requirements(
        requirements, directory / "requirements-audit.txt"
    )
    payload = _sbom_payload()
    payload["components"].extend(
        {
            "name": name,
            "type": "library",
            "externalReferences": [{"type": "other", "url": source["uri"]}],
        }
        for name, source in sources.items()
    )
    sbom = directory / "sbom-cyclonedx.json"
    _write_json(sbom, payload)
    producer.add_first_party_sbom_provenance(requirements, sbom)
    for path in directory.iterdir():
        os.utime(path, (NOW.timestamp(), NOW.timestamp()))
    return security, supply_chain, directory, sources


def _registered_gate(evidence):
    security, supply_chain, _, _ = evidence
    return shared_go_gate.build_gate(
        security_check_json=security,
        supply_chain_dir=supply_chain,
        install_profiles=("packaged-projects",),
        now=NOW,
    )


def test_shared_go_gate_accepts_registered_producer_sources(registered_source_evidence):
    assert _registered_gate(registered_source_evidence)["decision"] == "go"


def test_shared_go_gate_accepts_registered_editable_producer_sources(
    registered_source_evidence,
):
    from tools import profile_supply_chain_scan as producer

    _, _, directory, sources = registered_source_evidence
    requirements = directory / "requirements.txt"
    requirements.write_text(
        "demo-package==1.0\n"
        + "".join(f"-e {source['uri']}\n" for source in sources.values())
    )
    producer.write_pip_audit_requirements(
        requirements, directory / "requirements-audit.txt"
    )
    for path in (requirements, directory / "requirements-audit.txt"):
        os.utime(path, (NOW.timestamp(), NOW.timestamp()))
    assert _registered_gate(registered_source_evidence)["decision"] == "go"


@pytest.mark.parametrize(
    "problem",
    [
        "unregistered-uri",
        "remote-uri",
        "wrong-name",
        "swapped-uri",
        "version",
        "manifest",
        "digest",
        "missing-provenance",
        "duplicate-provenance",
        "missing-reference",
        "wrong-reference",
        "purl",
        "audit-requirement",
        "audit-source",
        "audit-inventory",
        "missing-component",
    ],
)
def test_shared_go_gate_rejects_registered_source_drift(
    registered_source_evidence, problem: str
):
    _, _, directory, sources = registered_source_evidence
    name, source = next(iter(sources.items()))
    requirements = directory / "requirements.txt"
    audit_requirements = directory / "requirements-audit.txt"
    sbom = directory / "sbom-cyclonedx.json"
    payload = json.loads(sbom.read_text())
    component = next(c for c in payload["components"] if c["name"] == name)
    if problem in {"unregistered-uri", "remote-uri", "wrong-name", "swapped-uri"}:
        replacement = {
            "unregistered-uri": f"{name} @ file:///unregistered",
            "remote-uri": f"{name} @ https://example.invalid/package.whl",
            "wrong-name": f"unregistered-package @ {source['uri']}",
            "swapped-uri": f"{name} @ {list(sources.values())[1]['uri']}",
        }[problem]
        requirements.write_text(
            requirements.read_text().replace(f"{name} @ {source['uri']}", replacement)
        )
    elif problem == "version":
        component.update(version="0.0.0", purl=f"pkg:pypi/{name}@0.0.0")
    elif problem in {"manifest", "digest"}:
        index = 0 if problem == "manifest" else 1
        component["properties"][index]["value"] = "wrong" if index == 0 else "0" * 64
    elif problem == "missing-provenance":
        component.pop("properties")
    elif problem == "duplicate-provenance":
        component["properties"].append(deepcopy(component["properties"][0]))
    elif problem == "missing-reference":
        component.pop("externalReferences")
    elif problem == "wrong-reference":
        component["externalReferences"][0]["url"] = "file:///unregistered"
    elif problem == "purl":
        component["purl"] = "pkg:pypi/unregistered@1.0"
    elif problem == "audit-requirement":
        audit_requirements.write_text(audit_requirements.read_text() + "extra==2.0\n")
    elif problem == "audit-source":
        audit_requirements.write_text(
            audit_requirements.read_text() + f"{name} @ {source['uri']}\n"
        )
    elif problem == "audit-inventory":
        audit_path = directory / "pip-audit.json"
        audit = json.loads(audit_path.read_text())
        audit["dependencies"].append(
            {"name": name, "version": source["version"], "vulns": []}
        )
        _write_json(audit_path, audit)
    elif problem == "missing-component":
        payload["components"].remove(component)
    _write_json(sbom, payload)
    for path in (requirements, audit_requirements):
        os.utime(path, (NOW.timestamp(), NOW.timestamp()))
    assert _registered_gate(registered_source_evidence)["decision"] == "blocked"
