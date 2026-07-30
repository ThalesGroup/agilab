from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path("tools/sync_docs_source.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("sync_docs_source_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_manifest_ignores_junk_files(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    (source / "guide.rst").parent.mkdir(parents=True)
    (source / "guide.rst").write_text("hello\n", encoding="utf-8")
    (source / ".DS_Store").write_text("junk\n", encoding="utf-8")
    (source / "__pycache__" / "ignored.pyc").parent.mkdir(parents=True)
    (source / "__pycache__" / "ignored.pyc").write_bytes(b"x")

    manifest = module.build_manifest(source)

    assert manifest == {"guide.rst": source / "guide.rst"}


def test_configured_canonical_source_honors_environment(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    configured = tmp_path / "isolated-canonical"
    monkeypatch.setenv(module.DOCS_SOURCE_ENV, str(configured))

    assert module.configured_canonical_source() == configured


def test_build_manifest_excludes_only_public_owned_docs_artifacts(
    tmp_path: Path,
) -> None:
    module = _load_module()
    root = tmp_path / "source"
    managed = root / "data" / "managed.json"
    managed.parent.mkdir(parents=True)
    managed.write_text("managed\n", encoding="utf-8")
    for rel_path in module.PUBLIC_OWNED_EXCLUSIONS:
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("public-owned\n", encoding="utf-8")

    manifest = module.build_manifest(root)

    assert manifest == {"data/managed.json": managed}


def test_make_sync_plan_reports_create_update_and_delete(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "same.rst").parent.mkdir(parents=True)
    (target / "same.rst").parent.mkdir(parents=True)
    (source / "same.rst").write_text("same\n", encoding="utf-8")
    (target / "same.rst").write_text("same\n", encoding="utf-8")
    (source / "new.rst").write_text("new\n", encoding="utf-8")
    (source / "changed.rst").write_text("source\n", encoding="utf-8")
    (target / "changed.rst").write_text("target\n", encoding="utf-8")
    (target / "extra.rst").write_text("extra\n", encoding="utf-8")

    plan = module.make_sync_plan(source, target, delete_extra=True)

    assert plan.created == ["new.rst"]
    assert plan.updated == ["changed.rst"]
    assert plan.deleted == ["extra.rst"]


def test_apply_sync_plan_copies_and_deletes(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "nested" / "guide.rst").parent.mkdir(parents=True)
    (target / "stale.rst").parent.mkdir(parents=True)
    (source / "nested" / "guide.rst").write_text("guide\n", encoding="utf-8")
    (target / "nested" / "guide.rst").parent.mkdir(parents=True, exist_ok=True)
    (target / "nested" / "guide.rst").write_text("old\n", encoding="utf-8")
    (target / "stale.rst").write_text("stale\n", encoding="utf-8")

    plan = module.make_sync_plan(source, target, delete_extra=True)
    module.apply_sync_plan(source, target, plan)

    assert (target / "nested" / "guide.rst").read_text(encoding="utf-8") == "guide\n"
    assert not (target / "stale.rst").exists()


def test_apply_delete_preserves_public_owned_artifacts_and_manages_adjacent_data(
    tmp_path: Path,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    for rel_path in module.PUBLIC_OWNED_EXCLUSIONS:
        source_path = source / rel_path
        target_path = target / rel_path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text("canonical-copy\n", encoding="utf-8")
        target_path.write_text("public-generated\n", encoding="utf-8")
    (source / "data" / "managed.json").write_text("new\n", encoding="utf-8")
    (target / "data" / "managed.json").write_text("old\n", encoding="utf-8")
    (target / "data" / "stale.json").write_text("stale\n", encoding="utf-8")

    plan = module.make_sync_plan(source, target, delete_extra=True)
    module.apply_sync_plan(source, target, plan)

    assert plan.updated == ["data/managed.json"]
    assert plan.deleted == ["data/stale.json"]
    for rel_path in module.PUBLIC_OWNED_EXCLUSIONS:
        assert (target / rel_path).read_text(encoding="utf-8") == "public-generated\n"
    assert (target / "data" / "managed.json").read_text(encoding="utf-8") == "new\n"
    assert not (target / "data" / "stale.json").exists()


def test_public_owned_artifact_changes_do_not_change_managed_digest(
    tmp_path: Path,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    before = module._manifest_state(target)
    for rel_path in module.PUBLIC_OWNED_EXCLUSIONS:
        path = target / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("generated version one\n", encoding="utf-8")
    after_create = module._manifest_state(target)
    for rel_path in module.PUBLIC_OWNED_EXCLUSIONS:
        (target / rel_path).write_text("generated version two\n", encoding="utf-8")

    assert after_create == before
    assert module._manifest_state(target) == before


def test_make_sync_plan_normalizes_unicode_relative_paths(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()

    source_name = "TP Prompt Ingénierie.pptx"
    target_name = "TP Prompt Inge\u0301nierie.pptx"
    (source / source_name).write_text("same\n", encoding="utf-8")
    (target / target_name).write_text("same\n", encoding="utf-8")

    plan = module.make_sync_plan(source, target, delete_extra=True)

    assert not plan.has_changes()


def test_main_check_and_apply_modes(tmp_path: Path, capsys) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("guide\n", encoding="utf-8")

    exit_code = module.main(["--source", str(source), "--target", str(target), "--check"])

    assert exit_code == 1
    assert "create: 1" in capsys.readouterr().out

    exit_code = module.main(["--source", str(source), "--target", str(target), "--apply"])

    assert exit_code == 0
    assert (target / "guide.rst").read_text(encoding="utf-8") == "guide\n"
    stamp = target.parent / module.STAMP_FILE_NAME
    assert stamp.exists()
    payload = json.loads(stamp.read_text(encoding="utf-8"))
    assert payload["file_count"] == 1
    assert payload["managed_target"] == "docs/source"
    assert payload["format_version"] == 2
    assert payload["source_status"] == "verified"
    assert payload["source_digest_sha256"] == payload["target_digest_sha256"]
    assert payload["public_owned_exclusions"] == sorted(
        module.PUBLIC_OWNED_EXCLUSIONS
    )


def test_apply_without_delete_fails_before_mutating_target_or_stamp(
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("canonical\n", encoding="utf-8")
    (source / "new.rst").write_text("new\n", encoding="utf-8")
    (target / "guide.rst").write_text("stale\n", encoding="utf-8")
    (target / "removed.rst").write_text("extra\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()

    exit_code = module.main(
        ["--source", str(source), "--target", str(target), "--apply"]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "No changes were applied" in captured.err
    assert "rerun with --apply --delete" in captured.err
    assert (target / "guide.rst").read_text(encoding="utf-8") == "stale\n"
    assert not (target / "new.rst").exists()
    assert (target / "removed.rst").read_text(encoding="utf-8") == "extra\n"
    assert stamp_path.read_bytes() == stamp_before


def test_main_missing_canonical_source_requires_explicit_degraded_mode(
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    assert module.main(["--target", str(target), "--write-target-only-stamp"]) == 0
    capsys.readouterr()

    exit_code = module.main(
        [
            "--source",
            str(tmp_path / "missing-source"),
            "--target",
            str(target),
            "--verify-stamp",
            "--quiet",
        ]
    )

    assert exit_code == 1
    assert "canonical docs source not found" in capsys.readouterr().out

    exit_code = module.main(
        [
            "--source",
            str(tmp_path / "missing-source"),
            "--target",
            str(target),
            "--verify-stamp",
            "--skip-missing-source",
            "--quiet",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "target integrity only" in output
    assert "canonical drift NOT CHECKED" in output

    exit_code = module.main(
        [
            "--source",
            str(tmp_path / "missing-source"),
            "--target",
            str(target),
            "--check",
            "--skip-missing-source",
            "--quiet",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "target integrity only" in output
    assert "canonical drift NOT CHECKED" in output


def test_verify_stamp_passes_after_apply(tmp_path: Path, capsys) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("guide\n", encoding="utf-8")

    assert module.main(["--source", str(source), "--target", str(target), "--apply"]) == 0

    exit_code = module.main(
        [
            "--source",
            str(source),
            "--target",
            str(target),
            "--verify-stamp",
        ]
    )

    assert exit_code == 0
    assert "mirror stamp ok:" in capsys.readouterr().out


def test_verify_stamp_detects_canonical_source_drift(tmp_path: Path, capsys) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("guide\n", encoding="utf-8")
    assert module.main(["--source", str(source), "--target", str(target), "--apply"]) == 0
    capsys.readouterr()
    (source / "guide.rst").write_text("canonical changed\n", encoding="utf-8")

    exit_code = module.main(
        [
            "--source",
            str(source),
            "--target",
            str(target),
            "--verify-stamp",
        ]
    )

    assert exit_code == 1
    assert "canonical source drift" in capsys.readouterr().out


def test_verified_stamp_rejects_self_source_and_unsynced_trees(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("source\n", encoding="utf-8")
    (target / "guide.rst").write_text("target\n", encoding="utf-8")

    with pytest.raises(ValueError, match="same directory"):
        module.build_mirror_stamp(target, target)
    with pytest.raises(ValueError, match="differ"):
        module.build_mirror_stamp(source, target)


def test_target_only_stamp_is_explicitly_noncanonical(tmp_path: Path, capsys) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("guide\n", encoding="utf-8")
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")

    exit_code = module.main(
        ["--target", str(target), "--write-target-only-stamp", "--quiet"]
    )

    assert exit_code == 0
    assert capsys.readouterr().out == ""
    payload = json.loads(
        module.stamp_path_for_target(target).read_text(encoding="utf-8")
    )
    assert payload["source_status"] == "unavailable"
    assert payload["source_digest_sha256"] is None

    exit_code = module.main(
        [
            "--source",
            str(source),
            "--target",
            str(target),
            "--verify-stamp",
            "--quiet",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out == ""

    (source / "guide.rst").write_text("canonical changed\n", encoding="utf-8")
    exit_code = module.main(
        [
            "--source",
            str(source),
            "--target",
            str(target),
            "--verify-stamp",
            "--quiet",
        ]
    )
    assert exit_code == 1
    assert "canonical source drift" in capsys.readouterr().out


def test_refresh_target_integrity_stamp_preserves_verified_evidence_for_exclusions(
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("guide\n", encoding="utf-8")
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    stamp_path = module.write_mirror_stamp(source, target)
    stamp_before = stamp_path.read_bytes()
    release_proof = target / "data" / "release_proof.toml"
    release_proof.parent.mkdir(parents=True)
    release_proof.write_text("[release]\n", encoding="utf-8")

    exit_code = module.main(
        ["--target", str(target), "--refresh-target-integrity-stamp"]
    )

    assert exit_code == 0
    assert "existing mirror stamp preserved" in capsys.readouterr().out
    assert stamp_path.read_bytes() == stamp_before
    payload = json.loads(stamp_path.read_text(encoding="utf-8"))
    assert payload["source_status"] == "verified"
    assert payload["source_digest_sha256"] == payload["target_digest_sha256"]


def test_refresh_target_integrity_stamp_downgrades_changed_managed_target(
    tmp_path: Path,
) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("guide\n", encoding="utf-8")
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    stamp_path = module.write_mirror_stamp(source, target)
    (target / "guide.rst").write_text("release changed managed docs\n", encoding="utf-8")

    exit_code = module.main(
        [
            "--target",
            str(target),
            "--refresh-target-integrity-stamp",
            "--quiet",
        ]
    )

    assert exit_code == 0
    payload = json.loads(stamp_path.read_text(encoding="utf-8"))
    assert payload["source_status"] == "unavailable"
    assert payload["source_digest_sha256"] is None
    assert payload["target_digest_sha256"] == module._manifest_state(target)[
        "digest_sha256"
    ]


def test_refresh_target_integrity_stamp_preserves_valid_target_only_evidence(
    tmp_path: Path,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    stamp_before = stamp_path.read_bytes()

    exit_code = module.main(
        [
            "--target",
            str(target),
            "--refresh-target-integrity-stamp",
            "--quiet",
        ]
    )

    assert exit_code == 0
    assert stamp_path.read_bytes() == stamp_before


def test_refresh_target_integrity_stamp_repairs_missing_stamp_honestly(
    tmp_path: Path,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    stamp_path = module.stamp_path_for_target(target)
    assert not stamp_path.exists()

    exit_code = module.main(
        [
            "--target",
            str(target),
            "--refresh-target-integrity-stamp",
            "--quiet",
        ]
    )

    assert exit_code == 0
    payload = json.loads(stamp_path.read_text(encoding="utf-8"))
    assert payload["source_status"] == "unavailable"
    assert payload["source_digest_sha256"] is None


def test_target_only_stamp_still_detects_target_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    assert module.main(["--target", str(target), "--write-target-only-stamp"]) == 0
    capsys.readouterr()
    (target / "guide.rst").write_text("changed\n", encoding="utf-8")

    exit_code = module.main(
        [
            "--source",
            str(tmp_path / "missing-source"),
            "--target",
            str(target),
            "--verify-stamp",
            "--skip-missing-source",
        ]
    )

    assert exit_code == 1
    assert "mirror stamp mismatch" in capsys.readouterr().out


def test_verify_stamp_detects_unmanaged_edit(tmp_path: Path, capsys) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("guide\n", encoding="utf-8")

    assert module.main(["--source", str(source), "--target", str(target), "--apply"]) == 0
    (target / "guide.rst").write_text("changed\n", encoding="utf-8")

    exit_code = module.main(
        [
            "--source",
            str(source),
            "--target",
            str(target),
            "--verify-stamp",
        ]
    )

    assert exit_code == 1
    assert "mirror stamp mismatch" in capsys.readouterr().out


def test_verify_stamp_reports_missing_stamp(tmp_path: Path, capsys) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")

    exit_code = module.main(
        [
            "--source",
            str(tmp_path / "source"),
            "--target",
            str(target),
            "--verify-stamp",
        ]
    )

    assert exit_code == 1
    assert "missing mirror stamp" in capsys.readouterr().out


def test_verify_stamp_rejects_non_object_json(tmp_path: Path) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    module.stamp_path_for_target(target).write_text("[]\n", encoding="utf-8")

    ok, message = module.verify_mirror_stamp(
        target,
        source=None,
        skip_missing_source=True,
    )

    assert ok is False
    assert "expected a JSON object" in message


def test_v1_stamp_rejection_names_both_regeneration_modes(tmp_path: Path) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    module.stamp_path_for_target(target).write_text(
        json.dumps({"format_version": 1}) + "\n",
        encoding="utf-8",
    )

    ok, message = module.verify_mirror_stamp(
        target,
        source=None,
        skip_missing_source=True,
    )

    assert ok is False
    assert "unsupported mirror stamp format" in message
    assert "--apply --delete" in message
    assert "--write-target-only-stamp" in message


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("managed_target", "other/source"),
        ("source_hint", "untrusted/source"),
        ("sync_tool", "tools/other_sync.py"),
    ],
)
def test_verify_stamp_rejects_false_identity_metadata(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    stamp_path = module.write_target_only_mirror_stamp(target)
    payload = json.loads(stamp_path.read_text(encoding="utf-8"))
    payload[field] = replacement
    stamp_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    ok, message = module.verify_mirror_stamp(
        target,
        source=None,
        skip_missing_source=True,
    )

    assert ok is False
    assert f"{field} mismatch" in message


def test_structured_target_and_canonical_checks_do_not_call_missing_source_pass(
    tmp_path: Path,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.mkdir()
    (target / "guide.rst").write_text("guide\n", encoding="utf-8")
    module.write_target_only_mirror_stamp(target)

    target_ok, target_message = module.verify_target_mirror_integrity(target)
    canonical_status, canonical_message = module.verify_canonical_mirror_alignment(
        target,
        tmp_path / "missing-canonical",
    )

    assert target_ok is True
    assert "target integrity verified" in target_message
    assert canonical_status == "skipped"
    assert "canonical drift NOT CHECKED" in canonical_message
