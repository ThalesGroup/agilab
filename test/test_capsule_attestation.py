from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import struct
import zipfile

import pytest

from agilab.evidence import capsule_attestation as adapter
from agilab.evidence import evaluation, evidence_contract
from test.test_evaluation import build_public_case


@pytest.mark.parametrize(
    "verify_api", ["verify_external_artifact", "verify_external_capsule"]
)
def test_optional_backend_missing_fails_before_any_input_is_read(
    tmp_path, monkeypatch, verify_api
):
    original = adapter.importlib.import_module

    def unexpected_read(*args, **kwargs):
        raise AssertionError("No input may be read before backend readiness")

    monkeypatch.setattr(adapter, "file_reference", unexpected_read)

    def missing(name):
        if name.startswith("sigstore"):
            raise ModuleNotFoundError(
                "synthetic missing optional backend", name="sigstore"
            )
        return original(name)

    monkeypatch.setattr(adapter.importlib, "import_module", missing)
    with pytest.raises(RuntimeError, match="optional Sigstore backend"):
        getattr(adapter, verify_api)(
            tmp_path,
            "absent.agipack",
            "absent.bundle",
            issuer="https://token.actions.githubusercontent.com",
            identity="https://example.org/exact-signer",
        )


def provenance_statement(digest="b" * 64):
    return {
        "_type": adapter.STATEMENT_TYPE,
        "subject": [{"name": "candidate.agipack", "digest": {"sha256": digest}}],
        "predicateType": adapter.SLSA_PREDICATE,
        "predicate": {
            "buildDefinition": {
                "buildType": "https://example.org/build/v1",
                "resolvedDependencies": [
                    {
                        "uri": "https://example.org/source",
                        "digest": {"sha256": "c" * 64},
                    }
                ],
            },
            "runDetails": {"builder": {"id": "https://example.org/trusted-builder"}},
        },
    }


PROVENANCE_POLICY = {
    "builder_id": "https://example.org/trusted-builder",
    "build_type": "https://example.org/build/v1",
    "source_uri": "https://example.org/source",
    "source_digest": {"sha256": "c" * 64},
}


def test_slsa_statement_policy_parser_is_separate_from_cryptographic_verification():
    # Synthetic statement tests parsing and policy only. It is never presented as signed evidence.
    statement = provenance_statement()
    result = adapter._provenance(
        json.dumps(statement).encode(),
        {"sha256": "b" * 64},
        "candidate.agipack",
        PROVENANCE_POLICY,
    )
    assert result["predicate_type"] == adapter.SLSA_PREDICATE
    assert "status" not in result
    for changed in (
        {**statement, "predicateType": "https://example.org/unknown"},
        {
            **statement,
            "subject": [{"name": "other.agipack", "digest": {"sha256": "b" * 64}}],
        },
        provenance_statement("d" * 64),
        {**statement, "subject": statement["subject"] * 2},
        {**statement, "predicate": {}},
    ):
        with pytest.raises(ValueError):
            adapter._provenance(
                json.dumps(changed).encode(),
                {"sha256": "b" * 64},
                "candidate.agipack",
                PROVENANCE_POLICY,
            )
    for key, wrong in (
        ("builder_id", "wrong-builder"),
        ("build_type", "wrong-type"),
        ("source_uri", "wrong-source"),
        ("source_digest", {"sha256": "d" * 64}),
    ):
        with pytest.raises(ValueError):
            adapter._provenance(
                json.dumps(statement).encode(),
                {"sha256": "b" * 64},
                "candidate.agipack",
                {**PROVENANCE_POLICY, key: wrong},
            )


def test_identity_policy_requires_explicit_issuer_and_exact_identity():
    for issuer, identity in (
        ("", "signer"),
        ("http://issuer", "signer"),
        ("https://issuer", "*"),
        ("https://issuer", "signer\ninjected"),
    ):
        with pytest.raises(ValueError):
            adapter._identity(issuer, identity)


def test_real_sdk_rejects_unsigned_bundle_and_no_silent_mode_fallback(tmp_path):
    pytest.importorskip("sigstore")
    (tmp_path / "artifact.bin").write_bytes(b"public test artifact")
    (tmp_path / "unsigned.bundle.json").write_text("{}")
    options = dict(
        issuer="https://token.actions.githubusercontent.com",
        identity="https://example.org/exact-signer",
    )
    result = adapter.verify_external_artifact(
        tmp_path, "artifact.bin", "unsigned.bundle.json", **options
    )
    assert result["status"] == "fail"
    assert result["backend"] == "sigstore-python"
    with pytest.raises(ValueError, match="explicit provenance policy"):
        adapter.verify_external_artifact(
            tmp_path,
            "artifact.bin",
            "unsigned.bundle.json",
            mode="slsa-provenance",
            **options,
        )
    with pytest.raises(ValueError, match="select slsa-provenance"):
        adapter.verify_external_artifact(
            tmp_path,
            "artifact.bin",
            "unsigned.bundle.json",
            provenance=PROVENANCE_POLICY,
            **options,
        )


@pytest.fixture
def real_official_sigstore_fixture(tmp_path, monkeypatch):
    pytest.importorskip("sigstore")
    from sigstore._internal import tuf

    # Keep production embedded trust material in this test's private cache.
    # No global cache, trust policy, issuer or verification outcome is changed.
    monkeypatch.setattr(
        tuf,
        "_get_dirs",
        lambda url: (tmp_path / "sigstore-metadata", tmp_path / "sigstore-targets"),
    )
    value = os.environ.get("AGILAB_ATTESTATION_FIXTURE_DIR")
    if not value:
        pytest.skip(
            "Requires an actual downloaded official Sigstore fixture; no synthetic cryptographic pass"
        )
    root = Path(value).resolve()
    metadata = json.loads(
        (root / "official-sigstore-fixture-metadata.json").read_text()
    )
    assert (
        evaluation.file_reference(root, metadata["artifact"]["path"])
        == metadata["artifact"]
    )
    assert (
        evaluation.file_reference(root, metadata["bundle"]["path"])
        == metadata["bundle"]
    )
    return root, metadata


def test_actual_official_bundle_has_a_cryptographically_verified_subject(
    real_official_sigstore_fixture,
):
    root, metadata = real_official_sigstore_fixture
    result = adapter.verify_external_artifact(
        root,
        metadata["artifact"]["path"],
        metadata["bundle"]["path"],
        issuer=metadata["issuer"],
        identity=metadata["identity"],
    )
    assert result["status"] == "pass", result
    assert result["capsule_status"] == "not_checked"
    assert result["provenance_status"] == "not_requested"


def test_actual_official_bundle_rejects_wrong_identity_issuer_and_digest(
    real_official_sigstore_fixture, tmp_path
):
    root, metadata = real_official_sigstore_fixture
    options = dict(issuer=metadata["issuer"], identity=metadata["identity"])
    for changed in (
        {**options, "identity": "https://example.org/wrong-identity"},
        {**options, "issuer": "https://example.org/wrong-issuer"},
    ):
        assert (
            adapter.verify_external_artifact(
                root,
                metadata["artifact"]["path"],
                metadata["bundle"]["path"],
                **changed,
            )["status"]
            == "fail"
        )
    (tmp_path / "wrong-public-artifact.bin").write_bytes(b"different public artifact")
    (tmp_path / "official.bundle.json").write_bytes(
        (root / metadata["bundle"]["path"]).read_bytes()
    )
    assert (
        adapter.verify_external_artifact(
            tmp_path, "wrong-public-artifact.bin", "official.bundle.json", **options
        )["status"]
        == "fail"
    )


def test_generic_distribution_bundle_cannot_attest_a_different_user_capsule(
    real_official_sigstore_fixture, tmp_path
):
    fixture_root, metadata = real_official_sigstore_fixture
    root, _ = build_public_case(tmp_path)
    # Produce a real local AGILAB capsule through the unchanged existing producer.
    evidence_contract.write_proof_capsule(
        root / "candidate-run.json", root / "public-candidate.agipack"
    )
    assert (
        evidence_contract.verify_proof_capsule(root / "public-candidate.agipack")[
            "status"
        ]
        == "pass"
    )
    (root / "other-distribution.bundle.json").write_bytes(
        (fixture_root / metadata["bundle"]["path"]).read_bytes()
    )
    result = adapter.verify_external_capsule(
        root,
        "public-candidate.agipack",
        "other-distribution.bundle.json",
        issuer=metadata["issuer"],
        identity=metadata["identity"],
    )
    assert result["capsule_status"] == "pass"
    assert result["status"] == "fail"


def test_capsule_local_contract_uses_captured_bytes_during_path_swap(
    tmp_path, monkeypatch
):
    # Exercise local capture only; no cryptographic verification is reached.
    monkeypatch.setattr(adapter, "_backend", lambda: None)
    root, _ = build_public_case(tmp_path)
    capsule = root / "public-candidate.agipack"
    evidence_contract.write_proof_capsule(root / "candidate-run.json", capsule)
    frozen = capsule.read_bytes()
    outside = tmp_path / "outside.agipack"
    outside.write_bytes(b"outside-must-not-be-opened")
    original = evidence_contract.verify_proof_capsule
    observed = []

    def swap_before_contract(path, **kwargs):
        capsule.unlink()
        capsule.symlink_to(outside)
        observed.append(Path(path).read_bytes())
        return original(path, **kwargs)

    monkeypatch.setattr(evidence_contract, "verify_proof_capsule", swap_before_contract)
    try:
        try:
            adapter.verify_external_capsule(
                root,
                capsule.name,
                "missing.bundle.json",
                issuer="https://token.actions.githubusercontent.com",
                identity="https://example.org/exact-signer",
            )
        except (OSError, ValueError):
            pass
    finally:
        capsule.unlink()
        capsule.write_bytes(frozen)
    assert observed == [frozen]
    assert outside.read_bytes() == b"outside-must-not-be-opened"


def test_real_aba_swap_cannot_join_local_capsule_to_other_signed_artifact(
    real_official_sigstore_fixture, tmp_path, monkeypatch
):
    """Real files and production SDK; the signed distribution is not a user capsule."""
    fixture_root, metadata = real_official_sigstore_fixture
    root, _ = build_public_case(tmp_path)
    capsule = root / "public-candidate.agipack"
    evidence_contract.write_proof_capsule(root / "candidate-run.json", capsule)
    captured_a = capsule.read_bytes()
    signed_b = (fixture_root / metadata["artifact"]["path"]).read_bytes()
    assert captured_a != signed_b
    (root / "official.bundle.json").write_bytes(
        (fixture_root / metadata["bundle"]["path"]).read_bytes()
    )
    options = dict(issuer=metadata["issuer"], identity=metadata["identity"])
    # B independently passes real production verification, without a capsule claim.
    assert (
        adapter.verify_external_artifact(
            fixture_root,
            metadata["artifact"]["path"],
            metadata["bundle"]["path"],
            **options,
        )["status"]
        == "pass"
    )

    local_verify = evidence_contract.verify_proof_capsule
    external_verify = adapter.verify_external_artifact
    local_results, external_results, swaps = [], [], []

    def observe_local(path, **kwargs):
        assert Path(path).read_bytes() == captured_a
        result = local_verify(path, **kwargs)
        local_results.append(result["status"])
        return result

    def swap_external(*args, **kwargs):
        assert capsule.read_bytes() == captured_a
        capsule.write_bytes(signed_b)
        swaps.append("B")
        try:
            result = external_verify(*args, **kwargs)
            external_results.append(result)
            return result
        finally:
            # Restore A after every external post-read check and before the outer check.
            capsule.write_bytes(captured_a)
            swaps.append("A")

    monkeypatch.setattr(evidence_contract, "verify_proof_capsule", observe_local)
    monkeypatch.setattr(adapter, "verify_external_artifact", swap_external)
    try:
        result = adapter.verify_external_capsule(
            root, capsule.name, "official.bundle.json", **options
        )
    except ValueError as exc:
        result = {"status": "fail", "reason": str(exc)}
    assert local_results == ["pass"]
    assert len(external_results) == 1
    assert swaps == ["B", "A"]
    assert capsule.read_bytes() == captured_a
    assert result["status"] != "pass", {
        "combined": result,
        "individual_external_status": external_results[0]["status"],
        "local_status": local_results[0],
    }


@pytest.mark.parametrize(
    "changed",
    [
        {"path": "other.agipack"},
        {"sha256": "0" * 64},
        {"size_bytes": 0},
    ],
    ids=["path", "digest", "size"],
)
def test_capsule_composition_rejects_mismatched_external_reference(
    tmp_path, monkeypatch, changed
):
    root, _ = build_public_case(tmp_path)
    capsule = root / "public-candidate.agipack"
    evidence_contract.write_proof_capsule(root / "candidate-run.json", capsule)
    (root / "controlled.bundle.json").write_text("{}")
    monkeypatch.setattr(adapter, "_backend", lambda: None)

    def mismatched_external(selected_root, artifact, bundle, **kwargs):
        return {
            "status": "pass",
            "artifact": {**adapter.file_reference(selected_root, artifact), **changed},
            "bundle": adapter.file_reference(selected_root, bundle),
        }

    # Controlled result composition only; no cryptographic success is claimed.
    monkeypatch.setattr(adapter, "verify_external_artifact", mismatched_external)
    with pytest.raises(ValueError, match="different captured capsule reference"):
        adapter.verify_external_capsule(root, capsule.name, "controlled.bundle.json")


def test_capsule_same_captured_bytes_compose_without_a_signing_claim(
    tmp_path, monkeypatch
):
    root, _ = build_public_case(tmp_path)
    capsule = root / "public-candidate.agipack"
    evidence_contract.write_proof_capsule(root / "candidate-run.json", capsule)
    (root / "controlled.bundle.json").write_text("{}")
    capsule_ref = adapter.file_reference(root, capsule.name)
    bundle_ref = adapter.file_reference(root, "controlled.bundle.json")
    monkeypatch.setattr(adapter, "_backend", lambda: None)
    local_verify = evidence_contract.verify_proof_capsule
    captured = []

    def observe_local(path):
        captured.append(Path(path).read_bytes())
        return local_verify(path)

    def controlled_external(selected_root, artifact, bundle, **kwargs):
        assert Path(selected_root) != root
        assert (Path(selected_root) / artifact).read_bytes() == captured[0]
        assert kwargs["subject_name"] == capsule.name
        return {
            "status": "pass",
            "artifact": adapter.file_reference(selected_root, artifact),
            "bundle": adapter.file_reference(selected_root, bundle),
        }

    monkeypatch.setattr(evidence_contract, "verify_proof_capsule", observe_local)
    monkeypatch.setattr(adapter, "verify_external_artifact", controlled_external)
    result = adapter.verify_external_capsule(
        root, capsule.name, "controlled.bundle.json"
    )
    assert result["status"] == result["capsule_status"] == "pass"
    assert result["artifact"] == capsule_ref
    assert result["bundle"] == bundle_ref


def _declared_capsule_archive(entries):
    """Small ZIP bytes with controlled central-directory sizes; never expands them."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, _ in entries:
            archive.writestr(name, b"{}")
    data = bytearray(buffer.getvalue())
    position = 0
    for name, declared_size in entries:
        position = data.index(bytes((80, 75, 1, 2)), position)
        assert name.encode() in data[position + 46 : position + 46 + len(name.encode())]
        struct.pack_into("<I", data, position + 24, declared_size)
        position += 46 + len(name.encode())
    return bytes(data)


@pytest.mark.parametrize(
    "entries",
    [
        [("agipack-manifest.json", 2 * 1024**3)],
        [("agipack-manifest.json", 2), ("blob.bin", 16 * 1024**2 + 1)],
        [("agipack-manifest.json", 2)]
        + [(f"blob-{i}.bin", 16 * 1024**2) for i in range(3)],
        [("agipack-manifest.json", 2)] + [(f"blob-{i}.bin", 2) for i in range(256)],
    ],
    ids=["declared-2-GiB-manifest", "per-member", "total-expansion", "member-count"],
)
def test_capsule_expansion_metadata_rejected_before_any_member_read(
    tmp_path, monkeypatch, entries
):
    data = _declared_capsule_archive(entries)
    assert len(data) < 40_000
    (tmp_path / "untrusted.agipack").write_bytes(data)
    reads, delegated = [], []
    monkeypatch.setattr(adapter, "_backend", lambda: None)

    def forbidden_read(*args, **kwargs):
        reads.append((args[1:], kwargs))
        raise AssertionError("Expansion limits must precede member reads")

    def forbidden_delegate(*args, **kwargs):
        delegated.append(True)
        raise AssertionError("Unsafe archive must not reach the shared verifier")

    monkeypatch.setattr(zipfile.ZipFile, "read", forbidden_read)
    monkeypatch.setattr(zipfile.ZipFile, "open", forbidden_read)
    monkeypatch.setattr(evidence_contract, "verify_proof_capsule", forbidden_delegate)
    with pytest.raises(ValueError, match="capsule ZIP"):
        adapter.verify_external_capsule(
            tmp_path, "untrusted.agipack", "absent.bundle.json"
        )
    assert reads == []
    assert delegated == []


@pytest.mark.parametrize(
    "kind",
    ["not-zip", "truncated", "duplicate", "unsafe-path", "crc", "compression"],
)
def test_capsule_malformed_archive_rejected_before_shared_verifier(
    tmp_path, monkeypatch, kind
):
    buffer = io.BytesIO()
    compression = zipfile.ZIP_BZIP2 if kind == "compression" else zipfile.ZIP_STORED
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        archive.writestr("agipack-manifest.json", b"{}")
        if kind == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr("agipack-manifest.json", b"{}")
        if kind == "unsafe-path":
            archive.writestr("../outside.bin", b"outside")
    data = buffer.getvalue()
    if kind == "not-zip":
        data = b"not a zip archive"
    elif kind == "truncated":
        data = data[:-10]
    elif kind == "crc":
        data = data.replace(b"{}", b"{x", 1)
    (tmp_path / "malformed.agipack").write_bytes(data)
    delegated = []
    monkeypatch.setattr(adapter, "_backend", lambda: None)

    def forbidden_delegate(*args, **kwargs):
        delegated.append(True)
        raise AssertionError("Malformed archive reached shared verifier")

    monkeypatch.setattr(evidence_contract, "verify_proof_capsule", forbidden_delegate)
    with pytest.raises(ValueError, match="capsule ZIP"):
        adapter.verify_external_capsule(
            tmp_path, "malformed.agipack", "absent.bundle.json"
        )
    assert delegated == []


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate",
        "excessive",
        "reviewer-513",
        "missing-entries",
        "entries-object",
        "entry-not-mapping",
        "path-not-text",
        "unsafe-path",
        "path-alias",
        "missing-payload",
        "unlisted-payload",
        "manifest-as-payload",
        "bad-digest",
        "bad-size",
        "size-text",
        "size-bool",
        "wrong-schema",
    ],
)
def test_capsule_manifest_inventory_rejected_before_shared_verifier(
    tmp_path, monkeypatch, kind
):
    blob = b"x" * (64 * 1024)
    entry = {
        "path": "blob.bin",
        "sha256": hashlib.sha256(blob).hexdigest(),
        "size_bytes": len(blob),
    }
    manifest = {"schema": evidence_contract.PROOF_CAPSULE_SCHEMA, "entries": [entry]}
    if kind == "duplicate":
        manifest["entries"] = [entry, entry.copy()]
    elif kind in {"excessive", "reviewer-513"}:
        count = 513 if kind == "reviewer-513" else adapter.MAX_CAPSULE_MEMBERS
        manifest["entries"] = [entry.copy() for _ in range(count)]
    elif kind == "missing-entries":
        del manifest["entries"]
    elif kind == "entries-object":
        manifest["entries"] = {}
    elif kind == "entry-not-mapping":
        manifest["entries"] = [None]
    elif kind == "missing-payload":
        entry["path"] = "absent.bin"
    elif kind == "unlisted-payload":
        manifest["entries"] = []
    elif kind == "wrong-schema":
        manifest["schema"] = "unsupported"
    else:
        field, value = {
            "path-not-text": ("path", 1),
            "unsafe-path": ("path", "../blob.bin"),
            "path-alias": ("path", "./blob.bin"),
            "manifest-as-payload": (
                "path",
                evidence_contract.PROOF_CAPSULE_MANIFEST_FILENAME,
            ),
            "bad-digest": ("sha256", "not-a-digest"),
            "bad-size": ("size_bytes", len(blob) + 1),
            "size-text": ("size_bytes", str(len(blob))),
            "size-bool": ("size_bytes", True),
        }[kind]
        entry[field] = value
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            evidence_contract.PROOF_CAPSULE_MANIFEST_FILENAME, json.dumps(manifest)
        )
        archive.writestr("blob.bin", blob)
    captured = buffer.getvalue()
    assert len(captured) < 4096
    (tmp_path / "invalid-inventory.agipack").write_bytes(captured)
    delegated = []
    monkeypatch.setattr(adapter, "_backend", lambda: None)

    def forbidden_delegate(*args, **kwargs):
        delegated.append(True)
        raise AssertionError("Invalid manifest reached the shared verifier")

    monkeypatch.setattr(evidence_contract, "verify_proof_capsule", forbidden_delegate)
    with pytest.raises(ValueError, match="capsule ZIP manifest"):
        adapter.verify_external_capsule(
            tmp_path, "invalid-inventory.agipack", "absent.bundle.json"
        )
    assert delegated == []


@pytest.mark.parametrize(
    "manifest",
    [
        b'{"schema":"agilab.proof_capsule.v1","entries":[],"entries":[]}',
        b'{"schema":"agilab.proof_capsule.v1","entries":[],"value":NaN}',
        b"[]",
        b"{",
    ],
    ids=["duplicate-json-key", "nonfinite-json", "nonobject-json", "malformed-json"],
)
def test_capsule_manifest_json_rejected_before_shared_verifier(
    tmp_path, monkeypatch, manifest
):
    with zipfile.ZipFile(tmp_path / "invalid-json.agipack", "w") as archive:
        archive.writestr(evidence_contract.PROOF_CAPSULE_MANIFEST_FILENAME, manifest)
        archive.writestr("blob.bin", b"small")
    delegated = []
    monkeypatch.setattr(adapter, "_backend", lambda: None)

    def forbidden_delegate(*args, **kwargs):
        delegated.append(True)
        raise AssertionError("Invalid manifest JSON reached the shared verifier")

    monkeypatch.setattr(evidence_contract, "verify_proof_capsule", forbidden_delegate)
    with pytest.raises(ValueError, match="capsule ZIP manifest"):
        adapter.verify_external_capsule(
            tmp_path, "invalid-json.agipack", "absent.bundle.json"
        )
    assert delegated == []


def test_capsule_unique_manifest_inventory_accepts_the_member_count_boundary():
    entries = [
        {
            "path": f"blob-{i}.bin",
            "sha256": hashlib.sha256(b"x").hexdigest(),
            "size_bytes": 1,
        }
        for i in range(adapter.MAX_CAPSULE_MEMBERS - 1)
    ]
    manifest = {"schema": evidence_contract.PROOF_CAPSULE_SCHEMA, "entries": entries}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            evidence_contract.PROOF_CAPSULE_MANIFEST_FILENAME, json.dumps(manifest)
        )
        for entry in entries:
            archive.writestr(entry["path"], b"x")
    adapter._preflight_capsule_archive(buffer.getvalue())


def test_capsule_preflight_streams_bounded_reads_then_preserves_local_validation(
    tmp_path, monkeypatch
):
    root, _ = build_public_case(tmp_path)
    capsule = root / "public-candidate.agipack"
    evidence_contract.write_proof_capsule(root / "candidate-run.json", capsule)
    (root / "controlled.bundle.json").write_text("{}")
    monkeypatch.setattr(adapter, "_backend", lambda: None)
    local_verify = evidence_contract.verify_proof_capsule
    stream_read = zipfile.ZipExtFile.read
    preflight_reads, delegated = [], []

    def bounded_read(stream, size=-1):
        if not delegated:
            assert 0 < size <= 64 * 1024
            preflight_reads.append(size)
        return stream_read(stream, size)

    def observe_delegate(path):
        assert preflight_reads
        delegated.append(True)
        return local_verify(path)

    def controlled_external(selected_root, artifact, bundle, **kwargs):
        # Composition control only; this is not a signed-user-capsule positive.
        return {
            "status": "fail",
            "artifact": adapter.file_reference(selected_root, artifact),
            "bundle": adapter.file_reference(selected_root, bundle),
        }

    monkeypatch.setattr(zipfile.ZipExtFile, "read", bounded_read)
    monkeypatch.setattr(evidence_contract, "verify_proof_capsule", observe_delegate)
    monkeypatch.setattr(adapter, "verify_external_artifact", controlled_external)
    result = adapter.verify_external_capsule(
        root, capsule.name, "controlled.bundle.json"
    )
    assert delegated == [True]
    assert result["capsule_status"] == "pass"
    assert result["status"] == "fail"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO required")
def test_capsule_fifo_is_rejected_by_descriptor_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "_backend", lambda: None)
    os.mkfifo(tmp_path / "input.agipack")
    with pytest.raises(ValueError, match="regular files"):
        adapter.verify_external_capsule(tmp_path, "input.agipack", "absent.bundle.json")
