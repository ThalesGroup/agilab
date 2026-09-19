import hashlib

import pytest

from tools.agent_context.materialize import materialize_context


def recommendation():
    return {
        "context_profile": {
            "max_total_tokens": 1400,
            "baseline_files": ["policy.md"],
            "matched_packs": [],
        },
        "recommended_skills": [],
    }


def prepare(tmp_path):
    (tmp_path / "policy.md").write_text("Always preserve approvals.\n")
    return recommendation()


def test_materialized_budget_counts_rendered_text_and_omissions(tmp_path):
    payload = prepare(tmp_path)
    (tmp_path / "code.py").write_text("value = 1\n" * 200)
    result = materialize_context(
        payload,
        root=tmp_path,
        count_tokens=len,
        selectors=["code.py"],
        reserve_tokens=100,
    )
    assert result["status"] == "pass"
    assert result["actual_tokens"] == len(result["context_text"]) <= 1300
    code = next(item for item in result["selected"] if item["path"] == "code.py")
    assert 0 < code["end_line"] < 200
    assert code["omitted_lines"] == 200 - code["end_line"]
    assert (
        code["sha256"]
        == hashlib.sha256((tmp_path / "code.py").read_bytes()).hexdigest()
    )
    assert any(item["reason"] == "excerpt_truncated" for item in result["omissions"])
    assert result["complete"] is False


def test_required_policy_is_not_silently_truncated(tmp_path):
    payload = prepare(tmp_path)
    (tmp_path / "policy.md").write_text("Mandatory policy.\n" * 200)
    result = materialize_context(payload, root=tmp_path, count_tokens=len)
    assert result["status"] == "mandatory-context-blocked"
    assert result["actual_tokens"] <= result["context_token_budget"]
    assert not result["selected"]
    assert result["omissions"][0]["required"] is True


def test_symbol_unicode_and_duplicate_aliases(tmp_path):
    payload = prepare(tmp_path)
    code = (
        'def first():\n    return "不需要"\n\ndef selected():\n    return "évidence"\n'
    )
    (tmp_path / "code.py").write_text(code)
    (tmp_path / "copy.py").write_text(code)
    result = materialize_context(
        payload,
        root=tmp_path,
        count_tokens=lambda text: len(text.encode()),
        selectors=["code.py::selected", "copy.py::selected"],
        reserve_tokens=100,
    )
    assert result["status"] == "pass"
    assert "évidence" in result["context_text"]
    assert "不需要" not in result["context_text"]
    assert len(result["selected"]) == 2  # policy and one copy of the symbol
    assert result["omissions"][0]["reason"] == "duplicate_content"
    assert result["actual_tokens"] == len(result["context_text"].encode())


def test_missing_policy_and_escaped_paths_fail_closed(tmp_path):
    payload = recommendation()
    result = materialize_context(
        payload,
        root=tmp_path,
        count_tokens=len,
        selectors=["../secrets.json", ".git/config", "missing.py"],
    )
    assert result["status"] == "mandatory-context-blocked"
    assert not result["context_text"]
    assert any(item["reason"] == "outside_repository" for item in result["omissions"])


def test_materialize_does_not_expand_polluted_directory(tmp_path):
    payload = prepare(tmp_path)
    folder = tmp_path / "src"
    folder.mkdir()
    (folder / "local-secrets.json").write_text('{"secret": "not requested"}')
    result = materialize_context(
        payload, root=tmp_path, count_tokens=len, selectors=["src"]
    )
    assert "not requested" not in result["context_text"]
    assert result["omissions"]


def test_line_selector_and_invalid_reserve(tmp_path):
    payload = prepare(tmp_path)
    (tmp_path / "code.py").write_text("first\nsecond\nthird\n")
    result = materialize_context(
        payload, root=tmp_path, count_tokens=len, selectors=["code.py#L2-L2"]
    )
    assert "second" in result["context_text"]
    assert "third" not in result["context_text"]
    with pytest.raises(ValueError, match="reserve"):
        materialize_context(
            payload, root=tmp_path, count_tokens=len, reserve_tokens=1400
        )


def test_nonregular_source_is_rejected_before_reading(tmp_path, monkeypatch):
    import os

    if not hasattr(os, "mkfifo"):
        pytest.skip("named pipes require POSIX")
    payload = prepare(tmp_path)
    os.mkfifo(tmp_path / "source.py")
    real_open = os.open

    def guarded_open(path, *args, **kwargs):
        assert str(path) != str(tmp_path / "source.py"), (
            "FIFO must be rejected before open"
        )
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded_open)
    result = materialize_context(
        payload, root=tmp_path, count_tokens=len, selectors=["source.py"]
    )
    assert result["status"] == "pass"
    assert result["omissions"] == [
        {"selector": "source.py", "reason": "not_regular_file", "required": False}
    ]


def test_mandatory_runbook_is_required_even_without_selected_pack(tmp_path):
    payload = prepare(tmp_path)
    payload["context_profile"]["mandatory_files"] = ["AGENTS.md"]
    result = materialize_context(payload, root=tmp_path, count_tokens=len)
    assert result["status"] == "mandatory-context-blocked"
    assert any(
        item["selector"] == "AGENTS.md" and item["required"]
        for item in result["omissions"]
    )


def test_explicit_symbol_does_not_fill_spare_budget_with_unrelated_pack_source(
    tmp_path,
):
    payload = prepare(tmp_path)
    (tmp_path / "requested.py").write_text("value = 1\n")
    (tmp_path / "unrelated.py").write_text("UNRELATED = True\n")
    payload["context_profile"]["matched_packs"] = [{"files": ["unrelated.py"]}]
    result = materialize_context(
        payload,
        root=tmp_path,
        count_tokens=len,
        selectors=["requested.py"],
        reserve_tokens=100,
    )
    assert "UNRELATED" not in result["context_text"]
    assert result["complete"] is True
    assert result["omissions"] == [
        {"selector": "unrelated.py", "reason": "not_selected", "required": False}
    ]
