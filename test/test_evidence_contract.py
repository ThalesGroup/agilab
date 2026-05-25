from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "agilab" / "evidence_contract.py"


def _load_module():
    previous_package = sys.modules.get("agilab")
    sys.modules.pop("agilab.evidence_contract", None)
    package = types.ModuleType("agilab")
    package.__path__ = [str(ROOT / "src" / "agilab")]  # type: ignore[attr-defined]
    package.__file__ = str(ROOT / "src" / "agilab" / "__init__.py")
    package.__package__ = "agilab"
    sys.modules["agilab"] = package
    spec = importlib.util.spec_from_file_location("agilab.evidence_contract", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous_package is None:
            sys.modules.pop("agilab", None)
        else:
            sys.modules["agilab"] = previous_package
    return module


def _write_run_manifest(
    tmp_path: Path,
    *,
    status: str = "pass",
    argv: tuple[str, ...] | None = None,
    env_overrides: dict[str, str] | None = None,
    artifacts: list[object] | None = None,
    validations: list[object] | None = None,
    started_at: str = "2026-05-19T10:00:00Z",
    finished_at: str = "2026-05-19T10:00:02Z",
) -> Path:
    from agilab import run_manifest

    tmp_path.mkdir(parents=True, exist_ok=True)
    artifact = tmp_path / "metrics.json"
    artifact.write_text('{"accuracy": 1.0}\n', encoding="utf-8")
    manifest_artifacts = artifacts or [
        run_manifest.RunManifestArtifact(
            name="run_manifest",
            path=str(tmp_path / "run_manifest.json"),
            kind="manifest",
            exists=True,
        ),
        run_manifest.RunManifestArtifact.from_path(artifact),
    ]
    manifest_validations = validations or [
        run_manifest.RunManifestValidation(
            label="proof_steps",
            status=status,
            summary="all proof steps passed" if status == "pass" else "proof failed",
            details={"model": "demo-model", "dataset": "demo-dataset"},
        )
    ]
    manifest = run_manifest.build_run_manifest(
        path_id="source-checkout-first-proof",
        label="AGILAB first-proof",
        status=status,
        command=run_manifest.RunManifestCommand(
            label="agilab first-proof",
            argv=argv if argv is not None else (sys.executable, "-c", "print('replayed')"),
            cwd=str(tmp_path),
            env_overrides=env_overrides or {"AGILAB_DISABLE_BACKGROUND_SERVICES": "1"},
        ),
        environment=run_manifest.RunManifestEnvironment(
            python_version="3.13.0",
            python_executable=sys.executable,
            platform="test",
            repo_root=str(tmp_path),
            active_app=str(tmp_path / "flight_telemetry_project"),
            app_name="flight_telemetry_project",
        ),
        timing=run_manifest.RunManifestTiming(
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=2.0,
            target_seconds=60.0,
        ),
        artifacts=manifest_artifacts,
        validations=manifest_validations,
        run_id="run-demo",
        created_at="2026-05-19T10:00:02Z",
    )
    path = tmp_path / "run_manifest.json"
    return run_manifest.write_run_manifest(manifest, path)


def test_verify_manifest_and_standard_exports(tmp_path: Path) -> None:
    module = _load_module()
    manifest_path = _write_run_manifest(tmp_path)
    manifest = module.load_manifest(manifest_path)

    report = module.verify_manifest(manifest_path)
    openlineage = module.build_openlineage_event(manifest, manifest_path)
    ro_crate = module.build_ro_crate_metadata(manifest, manifest_path)
    otel = module.build_otel_trace_export(manifest, manifest_path)
    cards = module.build_cards(manifest, manifest_path)

    assert report["schema"] == module.VERIFY_SCHEMA
    assert report["status"] == "pass"
    assert {check["id"] for check in report["checks"]} >= {
        "manifest_schema_supported",
        "manifest_status_pass",
        "validations_pass",
        "declared_artifacts_present",
        "replay_available",
    }
    assert openlineage["eventType"] == "COMPLETE"
    assert openlineage["run"]["runId"] == "run-demo"
    assert ro_crate["@graph"][0]["@id"] == "ro-crate-metadata.json"
    assert otel["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["traceId"]
    assert cards["model"]["name"] == "demo-model"
    assert cards["dataset"]["name"] == "demo-dataset"
    assert cards["eval"]["status"] == "pass"


def test_default_manifest_path_prefers_first_existing_candidate(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    first = tmp_path / "missing" / "run_manifest.json"
    second = tmp_path / "present" / "run_manifest.json"
    second.parent.mkdir()
    second.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(module, "DEFAULT_MANIFEST_CANDIDATES", (first, second))
    assert module.default_manifest_path() == second

    second.unlink()
    assert module.default_manifest_path() == first


def test_verify_manifest_reports_missing_invalid_skipped_artifacts_and_secret_env(tmp_path: Path) -> None:
    module = _load_module()

    missing_report = module.verify_manifest(tmp_path / "missing.json")
    assert missing_report["status"] == "fail"
    assert missing_report["checks"][0]["id"] == "manifest_exists"

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text('{"schema_version": 999, "kind": "agilab.run_manifest"}\n', encoding="utf-8")
    invalid_report = module.verify_manifest(invalid_path)
    assert invalid_report["status"] == "fail"
    assert invalid_report["checks"][1]["id"] == "manifest_schema_supported"

    manifest_path = _write_run_manifest(
        tmp_path,
        env_overrides={"OPENAI_API_KEY": "plain-secret"},
    )
    report = module.verify_manifest(manifest_path, check_artifacts=False)

    checks = {check["id"]: check for check in report["checks"]}
    assert checks["declared_artifacts_present"]["summary"] == "Artifact existence checks skipped."
    assert checks["secret_env_values_redacted"]["status"] == "fail"


def test_verify_manifest_detects_missing_relative_artifact_and_unavailable_replay(tmp_path: Path) -> None:
    from agilab import run_manifest

    module = _load_module()
    manifest_path = _write_run_manifest(
        tmp_path,
        argv=("missing-replay-command",),
        artifacts=[
            run_manifest.RunManifestArtifact(
                name="relative-missing",
                path="missing-output.json",
                kind="file",
                exists=True,
            )
        ],
    )

    report = module.verify_manifest(manifest_path)

    checks = {check["id"]: check for check in report["checks"]}
    assert checks["replay_available"]["status"] == "fail"
    assert checks["declared_artifacts_present"]["status"] == "fail"
    assert checks["declared_artifacts_present"]["details"]["missing"] == [
        str(tmp_path / "missing-output.json")
    ]


def test_proof_pack_writes_all_interop_files_and_metadata_store(tmp_path: Path) -> None:
    module = _load_module()
    manifest_path = _write_run_manifest(tmp_path)
    output_dir = tmp_path / "proof-pack"
    metadata_store = tmp_path / "metadata-store.json"

    result = module.write_proof_pack(
        manifest_path,
        output_dir,
        metadata_store_path=metadata_store,
    )

    generated_names = {path.name for path in result.generated_files}
    assert {
        module.PROOF_PACK_FILENAME,
        module.RUN_MANIFEST_SNAPSHOT_FILENAME,
        module.OPENLINEAGE_FILENAME,
        module.RO_CRATE_FILENAME,
        module.OTEL_TRACE_FILENAME,
        module.POLICY_REPORT_FILENAME,
        module.MODEL_CARD_FILENAME,
        module.DATASET_CARD_FILENAME,
        module.PROMPT_CARD_FILENAME,
        module.EVAL_CARD_FILENAME,
    } <= generated_names
    proof_pack = json.loads(result.proof_pack_path.read_text(encoding="utf-8"))
    assert proof_pack["schema"] == module.PROOF_PACK_SCHEMA
    assert proof_pack["standards"]["openlineage"] == module.OPENLINEAGE_FILENAME
    store = json.loads(metadata_store.read_text(encoding="utf-8"))
    assert store["schema"] == module.METADATA_STORE_SCHEMA
    assert store["entry_count"] == 1
    assert store["entries"][0]["run_id"] == "run-demo"


def test_proof_capsule_archive_verifies_replays_and_detects_tampering(tmp_path: Path, capsys) -> None:
    module = _load_module()
    manifest_path = _write_run_manifest(tmp_path)
    capsule_path = tmp_path / "run.agipack"

    result = module.write_proof_capsule(manifest_path, capsule_path)

    assert result.capsule_path == capsule_path
    assert result.capsule_manifest["schema"] == module.PROOF_CAPSULE_SCHEMA
    assert result.capsule_manifest["signed"] is False
    assert {entry["path"] for entry in result.capsule_manifest["entries"]} >= {
        module.PROOF_PACK_FILENAME,
        module.RUN_MANIFEST_SNAPSHOT_FILENAME,
    }

    verify_report = module.verify_proof_capsule(capsule_path)
    assert verify_report["schema"] == module.CAPSULE_VERIFY_SCHEMA
    assert verify_report["status"] == "pass"
    assert verify_report["manifest"]["run_id"] == "run-demo"

    assert module.main(["verify", str(capsule_path), "--json", "--strict"]) == 0
    cli_verify = json.loads(capsys.readouterr().out)
    assert cli_verify["capsule_path"] == str(capsule_path)

    assert module.main(["replay", str(capsule_path), "--json"]) == 0
    replay_report = json.loads(capsys.readouterr().out)
    assert replay_report["safe_default"] == "print-only"
    assert replay_report["source_capsule"] == str(capsule_path)

    cli_capsule = tmp_path / "cli.agipack"
    assert module.main(["prove", str(manifest_path), "--export", str(cli_capsule), "--json"]) == 0
    prove_report = json.loads(capsys.readouterr().out)
    assert prove_report["schema"] == module.PROOF_CAPSULE_SCHEMA
    assert prove_report["capsule_path"] == str(cli_capsule)

    unsigned_required = module.verify_proof_capsule(capsule_path, require_signature=True)
    unsigned_required_checks = {check["id"]: check for check in unsigned_required["checks"]}
    assert unsigned_required["status"] == "fail"
    assert unsigned_required_checks["capsule_signature_present"]["status"] == "fail"

    key_path = tmp_path / "signer.pem"
    signature_path = tmp_path / "run.agipack.sig.json"
    signature_result = module.sign_proof_capsule(
        capsule_path,
        key_path,
        signature_path=signature_path,
        signer="AGILAB QA",
        issuer="local",
        generate_key=True,
    )
    assert signature_result.signature["schema"] == module.PROOF_CAPSULE_SIGNATURE_SCHEMA
    assert signature_result.signature["subject"]["sha256"] == module.sha256_file(capsule_path)
    assert key_path.is_file()

    trust_policy = tmp_path / "trust-policy.toml"
    trust_policy.write_text(
        f"""
schema = "{module.TRUST_POLICY_SCHEMA}"
allowed_public_key_sha256 = ["{signature_result.signature["key"]["public_key_sha256"]}"]
allowed_signers = ["AGILAB QA"]
allowed_issuers = ["local"]
""".lstrip(),
        encoding="utf-8",
    )
    signed_verify = module.verify_proof_capsule(
        capsule_path,
        signature_path=signature_path,
        trust_policy_path=trust_policy,
        require_signature=True,
    )
    signed_checks = {check["id"]: check for check in signed_verify["checks"]}
    assert signed_verify["status"] == "pass"
    assert signed_checks["capsule_signature_cryptographic_valid"]["status"] == "pass"
    assert signed_checks["capsule_trust_policy_allows_public_key"]["status"] == "pass"

    cli_signature = tmp_path / "cli.agipack.sig.json"
    assert module.main([
        "sign",
        str(cli_capsule),
        "--key",
        str(key_path),
        "--signature",
        str(cli_signature),
        "--signer",
        "AGILAB QA",
        "--issuer",
        "local",
        "--json",
    ]) == 0
    sign_report = json.loads(capsys.readouterr().out)
    assert sign_report["status"] == "pass"
    assert sign_report["signature_path"] == str(cli_signature)

    assert module.main([
        "verify",
        str(capsule_path),
        "--signature",
        str(signature_path),
        "--trust-policy",
        str(trust_policy),
        "--require-signature",
        "--json",
        "--strict",
    ]) == 0
    cli_signed_verify = json.loads(capsys.readouterr().out)
    assert cli_signed_verify["signature_path"] == str(signature_path)

    bad_trust_policy = tmp_path / "bad-trust-policy.toml"
    bad_trust_policy.write_text(
        f"""
schema = "{module.TRUST_POLICY_SCHEMA}"
allowed_public_key_sha256 = ["not-{signature_result.signature["key"]["public_key_sha256"]}"]
allowed_signers = ["Other"]
""".lstrip(),
        encoding="utf-8",
    )
    bad_signed_verify = module.verify_proof_capsule(
        capsule_path,
        signature_path=signature_path,
        trust_policy_path=bad_trust_policy,
        require_signature=True,
    )
    bad_checks = {check["id"]: check for check in bad_signed_verify["checks"]}
    assert bad_signed_verify["status"] == "fail"
    assert bad_checks["capsule_trust_policy_allows_public_key"]["status"] == "fail"
    assert bad_checks["capsule_trust_policy_allows_signer"]["status"] == "fail"

    tampered_path = tmp_path / "tampered.agipack"
    with zipfile.ZipFile(capsule_path) as source, zipfile.ZipFile(tampered_path, "w") as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == module.RUN_MANIFEST_SNAPSHOT_FILENAME:
                data = data + b"\n"
            target.writestr(info, data)

    tampered_report = module.verify_proof_capsule(tampered_path)
    checks = {check["id"]: check for check in tampered_report["checks"]}
    assert tampered_report["status"] == "fail"
    assert checks["capsule_entry_hashes_match"]["status"] == "fail"

    tampered_signed_report = module.verify_proof_capsule(
        tampered_path,
        signature_path=signature_path,
        trust_policy_path=trust_policy,
        require_signature=True,
    )
    tampered_signed_checks = {check["id"]: check for check in tampered_signed_report["checks"]}
    assert tampered_signed_report["status"] == "fail"
    assert tampered_signed_checks["capsule_signature_subject_matches"]["status"] == "fail"


def test_policy_check_custom_policy_and_failed_manifest(tmp_path: Path) -> None:
    module = _load_module()
    manifest_path = _write_run_manifest(tmp_path, status="fail")
    manifest = module.load_manifest(manifest_path)
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "schema": "agilab.policy.v1",
                "id": "custom",
                "rules": [{"id": "command_present"}],
            }
        ),
        encoding="utf-8",
    )

    default_report = module.evaluate_policy(manifest, manifest_path)
    custom_report = module.evaluate_policy(manifest, manifest_path, policy_path=policy_path)

    assert default_report["status"] == "fail"
    assert custom_report["status"] == "pass"
    assert [rule["id"] for rule in custom_report["rules"]] == ["command_present"]


def test_policy_loading_and_metadata_store_edge_cases(tmp_path: Path) -> None:
    module = _load_module()
    manifest_path = _write_run_manifest(tmp_path)
    manifest = module.load_manifest(manifest_path)

    mapping_policy = tmp_path / "policy.toml"
    mapping_policy.write_text(
        """
id = "mapping-policy"

[rules]
command_present = true
validations_pass = false
unknown_rule = true
""".strip()
        + "\n",
        encoding="utf-8",
    )
    report = module.evaluate_policy(manifest, manifest_path, policy_path=mapping_policy)
    assert report["status"] == "fail"
    assert [rule["id"] for rule in report["rules"]] == ["command_present", "unknown_rule"]
    assert report["rules"][1]["summary"] == "Unknown or unsupported policy rule: unknown_rule"

    assert module.load_policy(None)["id"] == module.DEFAULT_POLICY_ID
    bad_extension = tmp_path / "policy.txt"
    bad_extension.write_text("rules = []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON or TOML"):
        module.load_policy(bad_extension)

    list_policy = tmp_path / "policy.json"
    list_policy.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must contain an object"):
        module.load_policy(list_policy)

    with pytest.raises(ValueError, match="mapping or list"):
        module._policy_rule_ids({"rules": "command_present"})

    unsupported_store = tmp_path / "unsupported-store.json"
    unsupported_store.write_text('{"schema": "other", "entries": []}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported metadata store schema"):
        module.append_metadata_store(unsupported_store, {"run_id": "run-demo"})

    existing_store = tmp_path / "metadata-store.json"
    existing_store.write_text(
        json.dumps(
            {
                "schema": module.METADATA_STORE_SCHEMA,
                "entries": [
                    {"run_id": "run-demo", "created_at": "2026-05-18T00:00:00Z"},
                    {"run_id": "run-old", "created_at": "2026-05-17T00:00:00Z"},
                ],
            }
        ),
        encoding="utf-8",
    )
    store = module.append_metadata_store(
        existing_store,
        {"run_id": "run-demo", "created_at": "2026-05-19T00:00:00Z"},
    )
    assert [entry["run_id"] for entry in store["entries"]] == ["run-old", "run-demo"]
    assert store["entries"][1]["created_at"] == "2026-05-19T00:00:00Z"


def test_replay_is_print_only_by_default_and_executes_when_requested(tmp_path: Path) -> None:
    module = _load_module()
    manifest = module.load_manifest(_write_run_manifest(tmp_path))

    print_rc, print_payload = module.run_replay(manifest)
    exec_rc, exec_payload = module.run_replay(manifest, execute=True, timeout_seconds=10)

    assert print_rc == 0
    assert print_payload["safe_default"] == "print-only"
    assert "stdout" not in print_payload
    assert exec_rc == 0
    assert exec_payload["status"] == "pass"
    assert exec_payload["stdout"].strip() == "replayed"


def test_replay_failure_paths_and_human_summaries(tmp_path: Path, capsys) -> None:
    module = _load_module()

    empty_command = module.load_manifest(_write_run_manifest(tmp_path / "empty", argv=()))
    empty_rc, empty_payload = module.run_replay(empty_command, execute=True)
    assert empty_rc == 2
    assert empty_payload["error"] == "No replay command recorded."

    failing_command = module.load_manifest(
        _write_run_manifest(
            tmp_path / "failing",
            argv=(sys.executable, "-c", "import sys; sys.exit(7)"),
        )
    )
    failing_rc, failing_payload = module.run_replay(failing_command, execute=True, timeout_seconds=10)
    assert failing_rc == 7
    assert failing_payload["status"] == "fail"

    assert module.main(["verify", str(tmp_path / "missing.json"), "--strict"]) == 1
    verify_text = capsys.readouterr().out
    assert "agilab.evidence_verification.v1: fail" in verify_text
    assert "- manifest_exists: fail" in verify_text

    failed_manifest_path = _write_run_manifest(tmp_path / "failed-policy", status="fail")
    assert module.main(["policy-check", str(failed_manifest_path), "--strict"]) == 1
    policy_text = capsys.readouterr().out
    assert "agilab.policy_report.v1: fail" in policy_text
    assert "- manifest_status_pass: fail" in policy_text


def test_cli_commands_emit_json_and_write_outputs(tmp_path: Path, capsys) -> None:
    module = _load_module()
    manifest_path = _write_run_manifest(tmp_path)
    output_dir = tmp_path / "exports"

    assert module.main(["verify", str(manifest_path), "--json", "--strict"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"

    assert module.main([
        "export-lineage",
        str(manifest_path),
        "--format",
        "openlineage",
        "--output-dir",
        str(output_dir),
        "--json",
    ]) == 0
    export_report = json.loads(capsys.readouterr().out)
    assert export_report["paths"]["openlineage"] == str(output_dir / module.OPENLINEAGE_FILENAME)
    assert (output_dir / module.OPENLINEAGE_FILENAME).is_file()

    assert module.main(["cards", str(manifest_path), "--json"]) == 0
    cards_report = json.loads(capsys.readouterr().out)
    assert cards_report["cards"]["model"]["card_type"] == "model"


def test_cli_commands_cover_proof_pack_replay_policy_cards_and_metadata_store(tmp_path: Path, capsys) -> None:
    module = _load_module()
    manifest_path = _write_run_manifest(tmp_path)
    proof_dir = tmp_path / "proof-pack"
    metadata_store = tmp_path / "metadata-store.json"

    assert module.main([
        "prove",
        str(manifest_path),
        "--output-dir",
        str(proof_dir),
        "--metadata-store",
        str(metadata_store),
        "--json",
    ]) == 0
    proof_report = json.loads(capsys.readouterr().out)
    assert proof_report["proof_pack_path"] == str(proof_dir / module.PROOF_PACK_FILENAME)
    assert metadata_store.is_file()

    assert module.main(["replay", str(manifest_path), "--json"]) == 0
    replay_report = json.loads(capsys.readouterr().out)
    assert replay_report["safe_default"] == "print-only"

    assert module.main(["policy-check", str(manifest_path), "--strict", "--json"]) == 0
    policy_report = json.loads(capsys.readouterr().out)
    assert policy_report["status"] == "pass"

    card_dir = tmp_path / "cards"
    assert module.main(["cards", str(manifest_path), "--output-dir", str(card_dir), "--json"]) == 0
    cards_report = json.loads(capsys.readouterr().out)
    assert cards_report["paths"]["model"] == str(card_dir / module.MODEL_CARD_FILENAME)

    second_store = tmp_path / "second-store.json"
    assert module.main(["metadata-store", str(manifest_path), "--store", str(second_store), "--json"]) == 0
    store_report = json.loads(capsys.readouterr().out)
    assert store_report["entry_count"] == 1

    otel_path = tmp_path / "otel.json"
    assert module.main([
        "export-lineage",
        str(manifest_path),
        "--format",
        "otel",
        "--output",
        str(otel_path),
        "--json",
    ]) == 0
    single_export = json.loads(capsys.readouterr().out)
    assert single_export["paths"]["otel"] == str(otel_path)

    traces_path = tmp_path / "traces.json"
    assert module.main([
        "export-traces",
        str(manifest_path),
        "--output",
        str(traces_path),
        "--json",
    ]) == 0
    trace_export = json.loads(capsys.readouterr().out)
    assert trace_export["formats"] == ["otel"]
    assert trace_export["paths"]["otel"] == str(traces_path)

    all_exports = tmp_path / "all-exports"
    assert module.main([
        "export-lineage",
        str(manifest_path),
        "--format",
        "all",
        "--output-dir",
        str(all_exports),
        "--json",
    ]) == 0
    all_export_report = json.loads(capsys.readouterr().out)
    assert all_export_report["formats"] == ["openlineage", "otel", "ro-crate"]


def test_private_serialization_and_time_helpers_cover_edge_types(tmp_path: Path) -> None:
    module = _load_module()
    manifest_path = _write_run_manifest(
        tmp_path,
        started_at="not-a-date",
        finished_at="2026-05-19T10:00:02",
    )
    manifest = module.load_manifest(manifest_path)
    otel = module.build_otel_trace_export(manifest, manifest_path)
    span = otel["resourceSpans"][0]["scopeSpans"][0]["spans"][0]

    assert span["startTimeUnixNano"] == "0"
    assert int(span["endTimeUnixNano"]) > 0
    assert module._otel_attr("enabled", True)["value"] == {"boolValue": True}
    assert module._json_safe({"path": tmp_path, "tuple": (tmp_path,), "set": {"b", "a"}}) == {
        "path": str(tmp_path),
        "tuple": [str(tmp_path)],
        "set": ["a", "b"],
    }


def test_defensive_helper_branches_and_export_errors(tmp_path: Path, monkeypatch) -> None:
    from agilab import run_manifest

    module = _load_module()
    manifest_path = _write_run_manifest(
        tmp_path,
        artifacts=[
            run_manifest.RunManifestArtifact(
                name="snapshot",
                path=str(tmp_path / module.RUN_MANIFEST_SNAPSHOT_FILENAME),
                kind="manifest",
                exists=False,
            )
        ],
    )
    manifest = module.load_manifest(manifest_path)

    ro_crate = module.build_ro_crate_metadata(manifest, manifest_path)
    graph_ids = {node["@id"] for node in ro_crate["@graph"]}
    assert module.RUN_MANIFEST_SNAPSHOT_FILENAME in graph_ids
    assert len([node for node in ro_crate["@graph"] if node["@id"] == module.RUN_MANIFEST_SNAPSHOT_FILENAME]) == 1

    result = module.write_proof_pack(manifest_path, tmp_path / "proof-pack-without-store")
    assert result.proof_pack_path.is_file()

    with pytest.raises(ValueError, match="single --format"):
        module._write_selected_exports(
            module._selected_exports(manifest, manifest_path, "all"),
            str(tmp_path / "one.json"),
            None,
        )

    assert module._replay_available(manifest) is True
    empty_manifest = run_manifest.build_run_manifest(
        path_id="empty-command",
        label="empty",
        status="pass",
        command=run_manifest.RunManifestCommand(label="", argv=(), cwd=str(tmp_path)),
        environment=manifest.environment,
        timing=manifest.timing,
        artifacts=(),
        validations=manifest.validations,
    )
    assert module._replay_available(empty_manifest) is False
    assert module._iso_to_unix_nanos("") == "0"

    policy_ids = module._policy_rule_ids(
        {"rules": [{"id": "skip-me", "required": False}, "plain-rule"]}
    )
    assert policy_ids == ("plain-rule",)

    monkeypatch.setattr(module, "tomllib", None)
    policy_path = tmp_path / "policy.toml"
    policy_path.write_text('id = "toml-policy"\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="TOML policy files require"):
        module.load_policy(policy_path)

    summary = module._human_summary(
        {
            "schema": "demo.schema",
            "status": "pass",
            "checks": ["not-a-check"],
            "rules": ["not-a-rule"],
            "paths": {"z": tmp_path / "z.json", "a": tmp_path / "a.json"},
        }
    )
    assert "a: " in summary
    assert "z: " in summary

    class UnsupportedArgs:
        command = "unsupported"
        manifest = str(manifest_path)

    class UnsupportedParser:
        message = ""

        def parse_args(self, _argv):
            return UnsupportedArgs()

        def error(self, message):
            self.message = message

    parser = UnsupportedParser()
    monkeypatch.setattr(module, "_build_parser", lambda: parser)
    assert module.main(["unsupported", str(manifest_path)]) == 2
    assert parser.message == "unsupported command: unsupported"
