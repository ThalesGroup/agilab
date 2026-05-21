from __future__ import annotations

import pytest

from agi_env import snippet_contract


def test_snippet_contract_block_freezes_current_api_version() -> None:
    block = snippet_contract.snippet_contract_block(app="demo", generator="test.generator")

    assert snippet_contract.GENERATED_SNIPPET_HEADER in block
    assert f"# snippet_api: {snippet_contract.CURRENT_SNIPPET_API}" in block
    assert "# app: demo" in block
    assert "# generator: test.generator" in block
    assert f'{snippet_contract.SNIPPET_API_NAME} = "{snippet_contract.CURRENT_SNIPPET_API}"' in block
    assert "require_supported_snippet_api(AGILAB_SNIPPET_API)" in block


def test_extract_and_check_current_snippet_api() -> None:
    code = f"""
from agi_cluster.agi_distributor import AGI
{snippet_contract.SNIPPET_API_NAME} = "{snippet_contract.CURRENT_SNIPPET_API}"
"""

    assert snippet_contract.is_generated_agi_snippet(code) is True
    assert snippet_contract.extract_snippet_api(code) == snippet_contract.CURRENT_SNIPPET_API
    assert snippet_contract.extract_snippet_api_version(code) == snippet_contract.CURRENT_SNIPPET_API
    assert snippet_contract.is_supported_snippet_api(code) is True
    assert snippet_contract.is_current_snippet_api(code) is True

    assert snippet_contract.extract_snippet_api("# snippet_api: agi.snippet.v1\n") == snippet_contract.CURRENT_SNIPPET_API
    assert snippet_contract.extract_snippet_api("AGILAB_SNIPPET_API_VERSION = 7\n") == "legacy.version.7"


def test_plain_python_snippet_is_not_agi_contract_bound() -> None:
    assert snippet_contract.is_generated_agi_snippet("print('hello')") is False
    assert snippet_contract.extract_snippet_api("print('hello')") is None


def test_require_supported_snippet_api_raises_cleanup_message_for_stale_versions() -> None:
    snippet_contract.require_supported_snippet_api(snippet_contract.CURRENT_SNIPPET_API)

    with pytest.raises(RuntimeError, match="Clean up old generated AGI_\\*\\.py snippets"):
        snippet_contract.require_supported_snippet_api("agi.snippet.v0")

    with pytest.raises(RuntimeError, match="Clean up old generated AGI_\\*\\.py snippets"):
        snippet_contract.require_current_snippet_api("not-a-version")

    with pytest.raises(RuntimeError, match="Clean up old generated AGI_\\*\\.py snippets"):
        snippet_contract.require_current_snippet_api(snippet_contract.CURRENT_SNIPPET_API_VERSION)


def test_stale_snippet_cleanup_message_includes_affected_paths() -> None:
    message = snippet_contract.stale_snippet_cleanup_message(["/tmp/AGI_run_demo.py"])

    assert "AGILAB core snippet API changed" in message
    assert "/tmp/AGI_run_demo.py" in message


def test_clean_stale_snippet_files_deletes_only_unsupported_generated_snippets(tmp_path) -> None:
    stale = tmp_path / "AGI_run_stale.py"
    stale.write_text(
        "from agi_cluster.agi_distributor import AGI\n"
        "async def main():\n"
        "    await AGI.run(None)\n",
        encoding="utf-8",
    )
    current = tmp_path / "AGI_run_current.py"
    current.write_text(
        f"{snippet_contract.snippet_contract_block(app='demo')}\n"
        "from agi_cluster.agi_distributor import AGI\n",
        encoding="utf-8",
    )
    plain = tmp_path / "plain.py"
    plain.write_text("print('hello')\n", encoding="utf-8")

    deleted, failed = snippet_contract.clean_stale_snippet_files([stale, current, plain])

    assert deleted == [stale]
    assert failed == []
    assert not stale.exists()
    assert current.exists()
    assert plain.exists()


def test_clean_stale_snippet_files_reports_bad_paths_and_delete_failures(tmp_path, monkeypatch) -> None:
    stale = tmp_path / "AGI_run_stale.py"
    stale.write_text("from agi_cluster.agi_distributor import AGI\nAGI.run(None)\n", encoding="utf-8")
    unreadable = tmp_path / "AGI_unreadable.py"
    unreadable.write_text("from agi_cluster.agi_distributor import AGI\nAGI.run(None)\n", encoding="utf-8")

    original_path = snippet_contract.Path

    class _PathFactory:
        def __call__(self, value):
            if value == object_marker:
                raise TypeError("bad path")
            return original_path(value)

    object_marker = object()
    monkeypatch.setattr(snippet_contract, "Path", _PathFactory())
    deleted, failed = snippet_contract.clean_stale_snippet_files([object_marker])
    assert deleted == []
    assert failed == [original_path(str(object_marker))]

    monkeypatch.setattr(snippet_contract, "Path", original_path)
    original_read_text = original_path.read_text
    monkeypatch.setattr(
        original_path,
        "read_text",
        lambda self, *args, **kwargs: (_ for _ in ()).throw(OSError("read")) if self == unreadable else original_read_text(self, *args, **kwargs),
    )
    deleted, failed = snippet_contract.clean_stale_snippet_files([unreadable])
    assert deleted == []
    assert failed == [unreadable]

    monkeypatch.setattr(original_path, "read_text", original_read_text)
    original_unlink = original_path.unlink
    monkeypatch.setattr(
        original_path,
        "unlink",
        lambda self, *args, **kwargs: (_ for _ in ()).throw(OSError("unlink")) if self == stale else original_unlink(self, *args, **kwargs),
    )
    deleted, failed = snippet_contract.clean_stale_snippet_files([stale])
    assert deleted == []
    assert failed == [stale]
