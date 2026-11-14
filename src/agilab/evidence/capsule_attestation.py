"""Optional official Sigstore verification of artifacts and user proof capsules.

Ed25519/local-trust capsule verification remains unchanged. This adapter never
signs, obtains OIDC credentials, deploys a service, or invents an attestation.
Official API: https://sigstore.github.io/sigstore-python/api/verify/verifier/
SLSA predicate: https://slsa.dev/spec/v1.2/build-provenance
"""

from __future__ import annotations

import argparse
import importlib
from importlib.metadata import version
import io
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping, Sequence
import zipfile
import zlib

from agilab.evidence import evidence_contract
from agilab.security.secret_uri import redact_text
from agilab.evidence.evaluation import (
    _digest,
    _text,
    check_file_reference,
    file_reference,
    read_evidence_json,
)

SCHEMA = "agilab.external_attestation_verification.v1"
SLSA_PREDICATE = "https://slsa.dev/provenance/v1"
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"


def _backend() -> tuple[Any, Any, Any, str]:
    try:
        models = importlib.import_module("sigstore.models")
        verify = importlib.import_module("sigstore.verify")
        policy = importlib.import_module("sigstore.verify.policy")
        installed = version("sigstore")
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)", installed)
        if match is None or not (4, 5, 1) <= tuple(map(int, match.groups())) < (
            5,
            0,
            0,
        ):
            raise RuntimeError(
                "This adapter requires the supported optional sigstore 4.x backend"
            )
        return models.Bundle, verify.Verifier, policy.Identity, installed
    except ImportError as exc:
        raise RuntimeError(
            "External attestation verification requires the optional Sigstore backend. "
            "Install sigstore>=4.5.1,<5 in the selected environment, then retry. "
            "Local Ed25519 capsule verification remains available."
        ) from exc


def _identity(issuer: str, identity: str) -> None:
    _text(issuer, "Trusted OIDC issuer")
    _text(identity, "Exact signing identity")
    if not issuer.startswith("https://") or any(
        c in issuer + identity for c in ("\n", "\r", "*")
    ):
        raise ValueError(
            "Declare an HTTPS issuer and an exact signing identity, without wildcards"
        )


def _provenance(
    payload: bytes,
    artifact: Mapping[str, Any],
    subject_name: str,
    expectations: Mapping[str, Any],
) -> dict[str, Any]:
    if set(expectations) != {"builder_id", "build_type", "source_uri", "source_digest"}:
        raise ValueError(
            "SLSA verification requires exact builder_id, build_type, source_uri and source_digest"
        )
    for key in ("builder_id", "build_type", "source_uri"):
        _text(expectations[key], key)
    source_digest = expectations["source_digest"]
    if not isinstance(source_digest, dict) or set(source_digest) != {"sha256"}:
        raise ValueError("Declare the expected source SHA-256 digest")
    _digest(source_digest["sha256"])
    statement = read_evidence_json(payload)
    if (
        statement.get("_type") != STATEMENT_TYPE
        or statement.get("predicateType") != SLSA_PREDICATE
    ):
        raise ValueError(
            "The signed statement is not an in-toto v1 SLSA provenance v1 statement"
        )
    subjects = statement.get("subject")
    if not isinstance(subjects, list):
        raise ValueError("The signed provenance has no subjects")
    matches = [
        s for s in subjects if isinstance(s, dict) and s.get("name") == subject_name
    ]
    if (
        len(matches) != 1
        or matches[0].get("digest", {}).get("sha256") != artifact["sha256"]
    ):
        raise ValueError(
            "The signed provenance subject does not match the actual artifact digest and name"
        )
    predicate = statement.get("predicate", {})
    definition = predicate.get("buildDefinition", {})
    builder = predicate.get("runDetails", {}).get("builder", {}).get("id")
    if (
        builder != expectations["builder_id"]
        or definition.get("buildType") != expectations["build_type"]
    ):
        raise ValueError(
            "The signed provenance builder or build type does not match the trusted expectations"
        )
    dependencies = definition.get("resolvedDependencies", [])
    matches = [
        d
        for d in dependencies
        if isinstance(d, dict)
        and d.get("uri") == expectations["source_uri"]
        and d.get("digest", {}).get("sha256") == source_digest["sha256"]
    ]
    if not matches:
        raise ValueError(
            "The signed provenance does not bind the expected source digest"
        )
    return {
        "predicate_type": SLSA_PREDICATE,
        "subject_name": subject_name,
        **expectations,
    }


def verify_external_artifact(
    app_root: Path,
    artifact_path: str | Path,
    bundle_path: str | Path,
    *,
    issuer: str,
    identity: str,
    mode: str = "signature",
    provenance: Mapping[str, Any] | None = None,
    subject_name: str | None = None,
    offline: bool = True,
) -> dict[str, Any]:
    """Verify actual artifact bytes with a production Sigstore trust root.

    Signature and SLSA modes are explicit; no fallback or mode detection occurs.
    Offline mode uses the SDK's local/bootstrap trust material without refreshing
    TUF. An online trust-root refresh must be explicitly requested.
    """
    Bundle, Verifier, Identity, installed = _backend()  # Fail before reading inputs.
    _identity(issuer, identity)
    if mode not in {"signature", "slsa-provenance"}:
        raise ValueError("Attestation mode must be signature or slsa-provenance")
    if mode == "signature" and provenance is not None:
        raise ValueError(
            "Signature mode does not verify SLSA provenance; select slsa-provenance explicitly"
        )
    if mode == "slsa-provenance" and not provenance:
        raise ValueError("SLSA mode requires an explicit provenance policy")
    if type(offline) is not bool:
        raise ValueError("offline must be a boolean")
    root = app_root.resolve(strict=True)
    artifact = file_reference(root, artifact_path)
    bundle_ref = file_reference(root, bundle_path)
    artifact_bytes = check_file_reference(root, artifact)
    bundle_bytes = check_file_reference(root, bundle_ref)
    base = {
        "schema": SCHEMA,
        "producer": __name__,
        "backend": "sigstore-python",
        "backend_version": installed,
        "mode": mode,
        "offline": offline,
        "artifact": artifact,
        "bundle": bundle_ref,
        "trusted_issuer": issuer,
        "exact_identity": identity,
        "capsule_status": "not_checked",
        "provenance_status": "not_requested",
        "claim_scope": "External artifact signature verification; no user capsule signing or deployment claim.",
    }
    try:
        bundle = Bundle.from_json(bundle_bytes)
        verifier = Verifier.production(offline=offline)
        policy = Identity(identity=identity, issuer=issuer)
        if mode == "signature":
            verifier.verify_artifact(artifact_bytes, bundle, policy)
            bound = None
        else:
            content_type, signed_payload = verifier.verify_dsse(bundle, policy)
            if content_type != "application/vnd.in-toto+json":
                raise ValueError("Unsupported signed DSSE payload type")
            bound = _provenance(
                signed_payload,
                artifact,
                subject_name or Path(artifact["path"]).name,
                provenance,
            )
        # Recheck both input byte identities after the cryptographic operation.
        check_file_reference(root, artifact)
        check_file_reference(root, bundle_ref)
        return {
            **base,
            "status": "pass",
            "provenance_status": "pass" if bound else "not_requested",
            "provenance": bound,
        }
    except Exception as exc:
        # No alternate cryptographic path is attempted after an SDK failure.
        return {
            **base,
            "status": "fail",
            "provenance_status": "fail"
            if mode == "slsa-provenance"
            else "not_requested",
            "reason": f"External attestation verification failed ({type(exc).__name__}): {redact_text(str(exc))[:400]}",
        }


# Bounds apply to untrusted expanded bytes before the existing ZIP verifier runs.
MAX_CAPSULE_MEMBERS = 256
MAX_CAPSULE_MEMBER_BYTES = 16 * 1024 * 1024
MAX_CAPSULE_MANIFEST_BYTES = 1024 * 1024
MAX_CAPSULE_EXPANDED_BYTES = 32 * 1024 * 1024
_CAPSULE_READ_BYTES = 64 * 1024


def _preflight_capsule_manifest(
    captured: bytes, payload_sizes: Mapping[str, int]
) -> None:
    """Bound the shared verifier's read schedule to the checked ZIP inventory."""
    try:
        manifest = read_evidence_json(captured)
        if manifest.get("schema") != evidence_contract.PROOF_CAPSULE_SCHEMA:
            raise ValueError("Unsupported capsule manifest schema")
        entries = manifest.get("entries")
        if not isinstance(entries, list) or len(entries) > MAX_CAPSULE_MEMBERS - 1:
            raise ValueError("Capsule manifest entries must be a bounded list")
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise ValueError("Capsule manifest entries must be mappings")
            name = entry.get("path")
            # Exact membership also requires the normalized safe spelling already
            # established by ZIP preflight; aliases and the manifest are excluded.
            if not isinstance(name, str) or name in seen or name not in payload_sizes:
                raise ValueError("Capsule manifest paths are invalid or duplicated")
            seen.add(name)
            _digest(entry.get("sha256"))
            size = entry.get("size_bytes")
            if (
                isinstance(size, bool)
                or not isinstance(size, int)
                or size != payload_sizes[name]
            ):
                raise ValueError("Capsule manifest size differs from ZIP metadata")
        if seen != set(payload_sizes):
            raise ValueError("Capsule manifest inventory differs from ZIP members")
    except ValueError as exc:
        raise ValueError(
            "capsule ZIP manifest has invalid schema, entries or inventory"
        ) from exc


def _preflight_capsule_archive(captured: bytes) -> None:
    """Reject unsafe ZIP metadata and stream bounded members before delegation."""
    try:
        with zipfile.ZipFile(io.BytesIO(captured)) as archive:
            members = archive.infolist()
            if len(members) > MAX_CAPSULE_MEMBERS:
                raise ValueError("capsule ZIP exceeds the member-count limit")
            names: set[str] = set()
            expanded = 0
            for member in members:
                name = member.filename
                if (
                    name != member.orig_filename
                    or "\\" in name
                    or ":" in name
                    or any(part in {"", ".", ".."} for part in name.split("/"))
                    or name in names
                ):
                    raise ValueError(
                        "capsule ZIP has duplicate or malformed member names"
                    )
                names.add(name)
                if member.compress_type not in {
                    zipfile.ZIP_STORED,
                    zipfile.ZIP_DEFLATED,
                }:
                    raise ValueError(
                        "capsule ZIP uses an unsupported compression method"
                    )
                if member.flag_bits & 1:
                    raise ValueError("capsule ZIP contains an encrypted member")
                limit = (
                    MAX_CAPSULE_MANIFEST_BYTES
                    if name == evidence_contract.PROOF_CAPSULE_MANIFEST_FILENAME
                    else MAX_CAPSULE_MEMBER_BYTES
                )
                if member.file_size < 0 or member.file_size > limit:
                    raise ValueError("capsule ZIP exceeds a member expansion limit")
                expanded += member.file_size
                if expanded > MAX_CAPSULE_EXPANDED_BYTES:
                    raise ValueError("capsule ZIP exceeds the total expansion limit")
            if evidence_contract.PROOF_CAPSULE_MANIFEST_FILENAME not in names:
                raise ValueError("capsule ZIP is missing its manifest")
            # Validate every member/CRC with explicit read sizes. No archive.read()
            # or unbounded decompression may run until all metadata passes.
            manifest_bytes = bytearray()
            for member in members:
                observed = 0
                with archive.open(member) as stream:
                    while True:
                        chunk = stream.read(
                            min(_CAPSULE_READ_BYTES, member.file_size - observed + 1)
                        )
                        if not chunk:
                            break
                        observed += len(chunk)
                        if (
                            member.filename
                            == evidence_contract.PROOF_CAPSULE_MANIFEST_FILENAME
                        ):
                            manifest_bytes.extend(chunk)
                        if observed > member.file_size:
                            raise ValueError(
                                "capsule ZIP member exceeds its declared size"
                            )
                if observed != member.file_size:
                    raise ValueError("capsule ZIP member has an inconsistent size")
            _preflight_capsule_manifest(
                bytes(manifest_bytes),
                {
                    member.filename: member.file_size
                    for member in members
                    if member.filename
                    != evidence_contract.PROOF_CAPSULE_MANIFEST_FILENAME
                },
            )
    except (
        zipfile.BadZipFile,
        RuntimeError,
        NotImplementedError,
        EOFError,
        zlib.error,
    ) as exc:
        raise ValueError("Invalid capsule ZIP archive") from exc


def verify_external_capsule(
    app_root: Path,
    capsule_path: str | Path,
    bundle_path: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    """Require both the existing capsule contract and a real matching external bundle."""
    _backend()
    root = app_root.resolve(strict=True)
    capsule_ref = file_reference(root, capsule_path)
    capsule = root / capsule_ref["path"]
    if capsule.suffix != ".agipack":
        raise ValueError(
            "External capsule verification requires a .agipack proof capsule"
        )
    captured = check_file_reference(root, capsule_ref)
    _preflight_capsule_archive(captured)
    # Both verifiers receive one private capture; the original path cannot select
    # different bytes between local ZIP validation and production SDK verification.
    with tempfile.TemporaryDirectory(prefix="agilab-capsule-contract-") as directory:
        snapshot_root = Path(directory)
        snapshot = snapshot_root / "captured.agipack"
        snapshot.write_bytes(captured)
        snapshot_ref = {**capsule_ref, "path": snapshot.name}
        local = evidence_contract.verify_proof_capsule(snapshot)
        if local["status"] != "pass":
            return {
                "schema": SCHEMA,
                "status": "fail",
                "capsule_status": "fail",
                "reason": "The existing local capsule contract did not verify",
            }
        bundle_ref = file_reference(root, bundle_path)
        bundle_bytes = check_file_reference(root, bundle_ref)
        snapshot_bundle = snapshot_root / "captured.bundle.json"
        snapshot_bundle.write_bytes(bundle_bytes)
        snapshot_bundle_ref = {**bundle_ref, "path": snapshot_bundle.name}
        options = dict(kwargs)
        if options.get("subject_name") is None:
            options["subject_name"] = capsule.name
        result = verify_external_artifact(
            snapshot_root, snapshot.name, snapshot_bundle.name, **options
        )
        if result.get("artifact") != snapshot_ref:
            raise ValueError(
                "External verification selected a different captured capsule reference"
            )
        if result.get("bundle") != snapshot_bundle_ref:
            raise ValueError(
                "External verification selected a different captured bundle reference"
            )
    # Retain descriptor-confined post-read checks on both original inputs too.
    check_file_reference(root, capsule_ref)
    check_file_reference(root, bundle_ref)
    result["artifact"] = capsule_ref
    result["bundle"] = bundle_ref
    result["capsule_status"] = local["status"]
    result["claim_scope"] = (
        "Existing local capsule contract plus the matching external signature and requested provenance policy. "
        "No new capsule signature was created and no serving deployment was performed."
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify an existing optional Sigstore signature or SLSA bundle; never signs."
    )
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--issuer", required=True, help="Trusted exact OIDC issuer.")
    parser.add_argument(
        "--identity", required=True, help="Trusted exact certificate identity."
    )
    parser.add_argument(
        "--mode", choices=("signature", "slsa-provenance"), default="signature"
    )
    parser.add_argument(
        "--provenance-policy",
        help="App-root-relative JSON with exact SLSA builder, build type and source digest expectations.",
    )
    parser.add_argument(
        "--capsule",
        action="store_true",
        help="Also require the existing .agipack capsule contract.",
    )
    parser.add_argument(
        "--refresh-trust-root",
        action="store_true",
        help="Explicitly allow the official SDK to refresh its production TUF trust root.",
    )
    args = parser.parse_args(argv)
    try:
        from agilab.evidence.evaluation import read_evidence_file

        _backend()
        provenance = (
            read_evidence_json(
                read_evidence_file(args.app_root, args.provenance_policy)
            )
            if args.provenance_policy
            else None
        )
        function = verify_external_capsule if args.capsule else verify_external_artifact
        result = function(
            args.app_root,
            args.artifact,
            args.bundle,
            issuer=args.issuer,
            identity=args.identity,
            mode=args.mode,
            provenance=provenance,
            offline=not args.refresh_trust_root,
        )
    except (RuntimeError, OSError, ValueError) as exc:
        result = {"schema": SCHEMA, "status": "unavailable", "reason": str(exc)}
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
