from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "relative",
    [
        "AGENTS.md",
        "agent-context-rules.json",
        "tools/agent_context_router.py",
        "docs/source/contributor-guide.rst",
        "docs/source/faq.rst",
        *(
            f"{provider}/skills/{skill}/{document}"
            for provider in (".claude", ".codex")
            for skill, document in (
                ("agilab-docs", "SKILL.md"),
                ("agilab-intent-router", "SKILL.md"),
                ("agilab-runbook", "SKILL.md"),
                ("agilab-huggingface-spaces", "SKILL.md"),
                ("svg-diagram-tuning", "SKILL.md"),
                ("agilab-deep-audit", "references/ARCHITECTURE_FOUNDATIONS.md"),
            )
        ),
    ],
)
def test_public_agent_guidance_does_not_route_docs_to_private_source(relative: str) -> None:
    text = (ROOT / relative).read_text(encoding="utf-8")
    assert "../thales_agilab/docs/source" not in text


def _module(name: str):
    spec = importlib.util.spec_from_file_location(
        f"private_boundary_{name}", ROOT / "tools" / f"{name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def public_docs(tmp_path, monkeypatch):
    docs = _module("sync_docs_source")
    repo = tmp_path / "public"
    source = repo / "docs" / "source"
    source.mkdir(parents=True)
    (source / "index.rst").write_text("Public documentation\n", encoding="utf-8")
    monkeypatch.setattr(docs, "REPO_ROOT", repo)
    monkeypatch.setattr(docs, "DEFAULT_TARGET", source)
    monkeypatch.delenv("AGILAB_DOCS_SOURCE", raising=False)
    monkeypatch.delenv("DOCS_REPOSITORY", raising=False)
    private = tmp_path / "thales_agilab" / "docs" / "source"
    private.mkdir(parents=True)
    (private / "index.rst").write_text("PRIVATE MUST NOT EXPORT\n", encoding="utf-8")
    return docs, repo, source, private


def test_default_source_is_current_public_checkout_without_private_discovery(public_docs, monkeypatch):
    docs, repo, source, _private = public_docs
    monkeypatch.setattr(docs, "_primary_git_checkout_root", lambda *_: pytest.fail("private discovery"))
    assert docs.canonical_source_configuration().path == source
    assert docs.canonical_source_configuration().origin == "public-checkout"
    assert docs.canonical_source_configuration(repo).required


@pytest.mark.parametrize("environment", ["AGILAB_DOCS_SOURCE", "DOCS_REPOSITORY"])
def test_private_environment_source_is_rejected_before_manifest_read(public_docs, monkeypatch, environment):
    docs, _repo, _source, private = public_docs
    configured = private if environment == "AGILAB_DOCS_SOURCE" else private.parents[1]
    monkeypatch.setenv(environment, str(configured))
    monkeypatch.setattr(docs, "build_manifest", lambda *_: pytest.fail("read private manifest"))
    with pytest.raises(ValueError, match="external and private"):
        docs.canonical_source_configuration()


@pytest.mark.parametrize("mode", ["--check", "--apply", "--verify-stamp", "--refresh-ui-robot-evidence-stamp", "--verify-target-integrity"])
def test_explicit_private_cli_source_is_rejected_before_copy_or_verification(public_docs, monkeypatch, mode):
    docs, _repo, source, private = public_docs
    before = (source / "index.rst").read_bytes()
    monkeypatch.setattr(docs, "managed_source_snapshot", lambda *_: pytest.fail("read private snapshot"))
    with pytest.raises(SystemExit) as error:
        docs.main(["--source", str(private), "--target", str(source), mode])
    assert error.value.code == 2
    assert (source / "index.rst").read_bytes() == before


def test_public_source_symlink_to_private_directory_is_rejected(public_docs):
    docs, repo, source, private = public_docs
    (source / "index.rst").unlink()
    source.rmdir()
    source.symlink_to(private, target_is_directory=True)
    with pytest.raises(ValueError, match="external and private"):
        docs.canonical_source_configuration(repo)


def test_public_check_uses_target_integrity_without_external_snapshot(public_docs, monkeypatch):
    docs, _repo, source, _private = public_docs
    docs.write_target_only_mirror_stamp(source)
    monkeypatch.setattr(docs, "managed_source_snapshot", lambda *_: pytest.fail("unexpected import"))
    assert docs.main(["--target", str(source), "--check"]) == 0
    result = docs.canonical_mirror_alignment_result(source, source, source_required=True)
    assert result.status == "pass"
    assert result.checked is False
    assert "public docs/source is authoritative" in result.message


def test_public_authored_change_can_refresh_stamp_and_verify_without_import(public_docs, monkeypatch):
    docs, _repo, source, _private = public_docs
    docs.write_target_only_mirror_stamp(source)
    (source / "index.rst").write_text("Updated public documentation\n", encoding="utf-8")
    monkeypatch.setattr(docs, "managed_source_snapshot", lambda *_: pytest.fail("unexpected import"))
    assert docs.main(["--target", str(source), "--apply"]) == 0
    assert docs.main(["--target", str(source), "--verify-stamp"]) == 0
    assert docs.main(["--target", str(source), "--verify-target-integrity"]) == 0
    stamp, _error = docs._read_stamp(source)
    assert stamp["source_status"] != "verified"


def test_maintenance_checks_authoritative_public_docs_without_external_sync_plan(public_docs, monkeypatch):
    docs, repo, source, _private = public_docs
    docs.write_target_only_mirror_stamp(source)
    dashboard = _module("maintenance_dashboard")
    monkeypatch.setattr(dashboard, "_load_tool", lambda *_args: docs)
    monkeypatch.setattr(docs, "make_sync_plan", lambda *_args, **_kwargs: pytest.fail("external sync plan"))
    check = dashboard.check_docs_mirror(repo).as_dict()
    assert check["status"] == "pass"
    assert check["details"]["canonical_alignment_checked"] is False


def _publisher(public_docs, monkeypatch):
    docs, repo, source, private = public_docs
    publisher = _module("pypi_publish")
    monkeypatch.setattr(publisher, "REPO_ROOT", repo)
    monkeypatch.setattr(publisher, "_sync_docs_source_module", lambda: docs)
    return publisher, repo, source, private


def test_release_does_not_discover_or_commit_a_private_docs_repository(public_docs, monkeypatch):
    publisher, _repo, _source, _private = _publisher(public_docs, monkeypatch)
    monkeypatch.setattr(publisher, "_git_repository_root_for_path", lambda *_: pytest.fail("external Git discovery"))
    assert publisher.find_docs_repository() == (None, None)


def test_release_private_export_is_rejected_even_when_explicit(public_docs, monkeypatch):
    publisher, _repo, _source, private = _publisher(public_docs, monkeypatch)
    monkeypatch.setattr(publisher, "run", lambda *_args, **_kwargs: pytest.fail("private copy command"))
    with pytest.raises(SystemExit, match="external and private"):
        publisher.sync_docs_source_mirror(private)


@pytest.mark.parametrize("action", ["update_docs_index_release_link", "validate_planned_docs_release", "generate_docs_in_docs_repository"])
def test_release_rejects_private_index_symlink_before_read_or_write(public_docs, monkeypatch, action):
    publisher, _repo, source, private = _publisher(public_docs, monkeypatch)
    before = (private / "index.rst").read_bytes()
    (source / "index.rst").unlink()
    (source / "index.rst").symlink_to(private / "index.rst")
    monkeypatch.setattr(publisher, "run", lambda *_args, **_kwargs: pytest.fail("unsafe build"))
    with pytest.raises(SystemExit, match="symlink"):
        if action == "generate_docs_in_docs_repository":
            getattr(publisher, action)()
        else:
            getattr(publisher, action)("v2026.10.14")
    assert (private / "index.rst").read_bytes() == before


def test_release_updates_only_public_index_and_builds_without_private_generator(public_docs, monkeypatch):
    publisher, repo, source, private = _publisher(public_docs, monkeypatch)
    public_index = source / "index.rst"
    public_index.write_text("`latest public GitHub release <https://github.com/ThalesGroup/agilab/releases/tag/v2026.1.1>`__\n", encoding="utf-8")
    private_before = (private / "index.rst").read_bytes()
    publisher.update_docs_index_release_link("v2026.10.14")
    assert "/tag/v2026.10.14" in public_index.read_text()
    assert (private / "index.rst").read_bytes() == private_before
    calls = []
    monkeypatch.setattr(publisher, "run", lambda argv, **kwargs: calls.append((argv, kwargs)))
    publisher.generate_docs_in_docs_repository()
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[:2] == ["uv", "run"]
    assert argv[-7:] == ["python", "-m", "sphinx", "-b", "html", str(source), str(repo / "docs" / "html")]
    assert kwargs == {"cwd": repo}
    assert "docs/gen-docs.py" not in argv
    assert "sphinx-rtd-theme" in argv


@pytest.mark.parametrize("action", ["find_docs_repository", "generate_docs_in_docs_repository"])
def test_release_rejects_stale_private_environment_before_any_command(public_docs, monkeypatch, action):
    publisher, _repo, _source, private = _publisher(public_docs, monkeypatch)
    monkeypatch.setenv("AGILAB_DOCS_SOURCE", str(private))
    monkeypatch.setattr(publisher, "run", lambda *_args, **_kwargs: pytest.fail("command with private source"))
    with pytest.raises(SystemExit, match="external and private"):
        getattr(publisher, action)()
