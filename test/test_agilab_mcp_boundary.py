"""Read-boundary disclosure contract for the AGILAB MCP server.

The boundary itself is unchanged: what a client may read is exactly what it
could read before. These tests pin that the boundary is *visible* - reported in
the server manifest, and warned about on stderr when it falls back to the wide
default that includes the whole repository checkout.
"""

from __future__ import annotations

import io
import json

import pytest

from agilab_mcp import manifest_tools, server


def test_explicit_roots_are_reported_as_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("AGILAB_MCP_ALLOWED_ROOTS", str(tmp_path))

    boundary = manifest_tools.read_boundary()
    assert boundary["source"] == manifest_tools.READ_BOUNDARY_SOURCE_CONFIGURED
    assert boundary["roots"] == [str(tmp_path.resolve())]
    assert boundary["includes_repository_root"] is False
    assert server.read_boundary_warning() is None


def test_unset_roots_fall_back_to_default_and_warn(monkeypatch):
    monkeypatch.delenv("AGILAB_MCP_ALLOWED_ROOTS", raising=False)

    boundary = manifest_tools.read_boundary()
    assert boundary["source"] == manifest_tools.READ_BOUNDARY_SOURCE_DEFAULT

    warning = server.read_boundary_warning()
    if boundary["includes_repository_root"]:
        assert warning is not None
        assert "AGILAB_MCP_ALLOWED_ROOTS" in warning
        assert ".git" in warning
    else:  # pragma: no cover - installed layouts without a repo checkout
        assert warning is None


def test_server_manifest_publishes_the_effective_boundary(tmp_path, monkeypatch):
    monkeypatch.setenv("AGILAB_MCP_ALLOWED_ROOTS", str(tmp_path))

    policy = server.server_manifest()["policy"]
    # Existing policy claims must not regress.
    assert policy["read_only"] is True
    assert policy["local_files_only"] is True
    assert policy["execution_tools_enabled"] is False
    assert policy["shell_enabled"] is False
    assert policy["read_boundary"]["roots"] == [str(tmp_path.resolve())]


def test_warning_goes_to_stderr_and_never_corrupts_the_jsonrpc_stream(monkeypatch):
    """stdout carries the JSON-RPC stream; a stray line desynchronises clients."""

    monkeypatch.delenv("AGILAB_MCP_ALLOWED_ROOTS", raising=False)
    stdout, stderr = io.StringIO(), io.StringIO()
    stdin = io.StringIO('{"jsonrpc":"2.0","id":1,"method":"initialize"}\n')

    assert server.serve_stdio(stdin=stdin, stdout=stdout, stderr=stderr) == 0

    lines = stdout.getvalue().splitlines()
    assert len(lines) == 1
    # Every stdout line must parse as JSON, warning or not.
    assert json.loads(lines[0])["id"] == 1
    if server.read_boundary_warning() is not None:
        assert "AGILAB_MCP_ALLOWED_ROOTS" in stderr.getvalue()


def test_boundary_disclosure_does_not_widen_access(tmp_path, monkeypatch):
    """Reporting the boundary must not change what the boundary permits."""

    monkeypatch.setenv("AGILAB_MCP_ALLOWED_ROOTS", str(tmp_path))

    with pytest.raises(ValueError, match="outside configured read roots"):
        manifest_tools.read_manifest("/etc/passwd")
