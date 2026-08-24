from __future__ import annotations

import asyncio
import io
import json
import os
import pickle
import stat
import sys
import urllib.error
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_cluster.agi_distributor import runtime_misc_support


def test_ensure_asyncio_run_signature_patches_pydevd_shim():
    def _fake_run(main, debug=None):
        return ("orig", main, debug)

    _fake_run.__module__ = "pydevd.fake"
    fake_asyncio = SimpleNamespace(
        run=_fake_run,
        set_event_loop=lambda _loop: None,
    )

    runtime_misc_support.ensure_asyncio_run_signature(asyncio_module=fake_asyncio)

    patched = fake_asyncio.run
    assert patched is not _fake_run
    assert patched("task", debug=True) == ("orig", "task", True)

    async def _coro():
        return 7

    assert patched(_coro(), loop_factory=asyncio.new_event_loop) == 7


def test_ensure_asyncio_run_signature_tolerates_event_loop_runtime_errors():
    def _fake_run(main, debug=None):
        return ("orig", main, debug)

    _fake_run.__module__ = "pydevd.fake"
    set_calls = []

    def _fake_set_event_loop(loop):
        set_calls.append(loop)
        raise RuntimeError("loop policy locked")

    fake_asyncio = SimpleNamespace(
        run=_fake_run,
        set_event_loop=_fake_set_event_loop,
    )

    runtime_misc_support.ensure_asyncio_run_signature(asyncio_module=fake_asyncio)

    class _Loop:
        def __init__(self):
            self.debug = None
            self.closed = False
            self.awaited = []

        def set_debug(self, value):
            self.debug = value

        def run_until_complete(self, main):
            self.awaited.append(main)
            return "done"

        def close(self):
            self.closed = True

    loop = _Loop()
    patched = fake_asyncio.run
    assert patched("task", debug=True, loop_factory=lambda: loop) == "done"
    assert loop.debug is True
    assert loop.closed is True
    assert set_calls == [loop, None]


def test_ensure_asyncio_run_signature_leaves_non_pydevd_shim_untouched():
    def _fake_run(main, debug=None):
        return ("orig", main, debug)

    _fake_run.__module__ = "custom.runner"
    fake_asyncio = SimpleNamespace(
        run=_fake_run,
        set_event_loop=lambda _loop: None,
    )

    runtime_misc_support.ensure_asyncio_run_signature(asyncio_module=fake_asyncio)

    assert fake_asyncio.run is _fake_run


def test_ensure_asyncio_run_signature_handles_uninspectable_run():
    def _fake_run(main, debug=None):
        return ("orig", main, debug)

    fake_asyncio = SimpleNamespace(
        run=_fake_run,
        set_event_loop=lambda _loop: None,
    )

    runtime_misc_support.ensure_asyncio_run_signature(
        asyncio_module=fake_asyncio,
        inspect_signature_fn=lambda *_a, **_k: (_ for _ in ()).throw(
            ValueError("no signature")
        ),
    )

    assert fake_asyncio.run is _fake_run


def test_agi_version_missing_on_pypi_detection(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)

    assert runtime_misc_support.agi_version_missing_on_pypi(project) is False

    pyproject = project / "pyproject.toml"
    pyproject.write_text("[project]\nname='demo'\n", encoding="utf-8")
    assert runtime_misc_support.agi_version_missing_on_pypi(project) is False

    pyproject.write_text('agi-core = "==1.2.3"\n', encoding="utf-8")

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return io.StringIO(json.dumps(self._payload))

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        runtime_misc_support.urllib.request,
        "urlopen",
        lambda *_a, **_k: _Resp({"releases": {"1.2.3": [{}]}}),
    )
    assert runtime_misc_support.agi_version_missing_on_pypi(project) is False

    monkeypatch.setattr(
        runtime_misc_support.urllib.request,
        "urlopen",
        lambda *_a, **_k: _Resp({"releases": {"1.2.4": [{}]}}),
    )
    assert runtime_misc_support.agi_version_missing_on_pypi(project) is True

    monkeypatch.setattr(
        runtime_misc_support.urllib.request,
        "urlopen",
        lambda *_a, **_k: (_ for _ in ()).throw(urllib.error.URLError("network down")),
    )
    assert runtime_misc_support.agi_version_missing_on_pypi(project) is False


def test_agi_version_missing_on_pypi_propagates_unexpected_lookup_bug(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    (project / "pyproject.toml").write_text('agi-core = "==1.2.3"\n', encoding="utf-8")

    monkeypatch.setattr(
        runtime_misc_support.urllib.request,
        "urlopen",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("programmer bug")),
    )

    with pytest.raises(RuntimeError, match="programmer bug"):
        runtime_misc_support.agi_version_missing_on_pypi(project)


def test_agi_version_missing_on_pypi_ignores_unpinned_specs_and_read_failures(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    pyproject = project / "pyproject.toml"
    pyproject.write_text('agi-core = ">=1.2"\n', encoding="utf-8")

    assert runtime_misc_support.agi_version_missing_on_pypi(project) is False

    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self, *args, **kwargs: (_ for _ in ()).throw(UnicodeError("bad file")),
    )
    assert runtime_misc_support.agi_version_missing_on_pypi(project) is False


def test_format_exception_chain_compacts_causes():
    try:
        try:
            raise ValueError("inner")
        except ValueError as exc:
            raise RuntimeError("RuntimeError: inner") from exc
    except Exception as exc:
        text = runtime_misc_support.format_exception_chain(exc)

    assert "inner" in text
    assert ("RuntimeError" in text) or ("ValueError" in text)


def test_format_exception_chain_strips_generic_error_prefixes():
    class CustomError(Exception):
        pass

    text = runtime_misc_support.format_exception_chain(
        CustomError("CustomError: precise detail")
    )

    assert text.endswith("CustomError: precise detail")


def test_format_exception_chain_handles_context_normalization_edges(monkeypatch):
    class SilentError(Exception):
        def __str__(self):
            return ""

    def _fake_tb(lines):
        return SimpleNamespace(format_exception_only=lambda: list(lines))

    try:
        try:
            try:
                try:
                    raise SilentError()
                except SilentError:
                    raise RuntimeError("duplicate")
            except RuntimeError:
                raise RuntimeError("duplicate")
        except RuntimeError:
            raise RuntimeError("fresh detail")
    except RuntimeError as exc:
        exc_4 = exc
        exc_3 = exc.__context__
        exc_2 = exc_3.__context__
        exc_1 = exc_2.__context__

    mapping = {
        id(exc_1): _fake_tb([""]),
        id(exc_2): _fake_tb(["SilentError: \n"]),
        id(exc_3): _fake_tb(["prefix SilentError:\n"]),
        id(exc_4): _fake_tb(["fresh detail\n"]),
    }
    monkeypatch.setattr(
        runtime_misc_support.traceback.TracebackException,
        "from_exception",
        staticmethod(lambda current: mapping[id(current)]),
    )

    text = runtime_misc_support.format_exception_chain(exc_4)

    assert "SilentError:" in text
    assert "fresh detail" in text


def test_load_capacity_predictor_rejects_missing_trusted_root_by_default(tmp_path):
    model_path = tmp_path / "balancer_model.pkl"
    model_path.write_bytes(b"pickle-bytes")
    calls = {"load": 0, "retrain": 0, "warnings": []}
    log = SimpleNamespace(
        warning=lambda message, path: calls["warnings"].append((message, path))
    )

    loaded = runtime_misc_support.load_capacity_predictor(
        model_path,
        load_fn=lambda _stream: calls.__setitem__("load", calls["load"] + 1),
        retrain_fn=lambda: calls.__setitem__("retrain", calls["retrain"] + 1),
        log=log,
    )

    assert loaded is None
    assert calls["load"] == 0
    assert calls["retrain"] == 1
    assert "without a trusted resource root" in calls["warnings"][0][0]


def test_load_capacity_predictor_returns_signed_trusted_value(tmp_path):
    model_path = tmp_path / "resources" / "balancer_model.pkl"
    model_path.parent.mkdir()
    model_path.write_bytes(b"pickle-bytes")
    runtime_misc_support.write_capacity_model_manifest(model_path)

    loaded = runtime_misc_support.load_capacity_predictor(
        model_path,
        load_fn=lambda stream: {"size": len(stream.read())},
        trusted_root=model_path.parent,
    )

    assert loaded == {"size": len(b"pickle-bytes")}


def test_load_capacity_predictor_suppresses_only_sklearn_version_warning(
    monkeypatch, tmp_path
):
    class FakeInconsistentVersionWarning(Warning):
        pass

    model_path = tmp_path / "resources" / "balancer_model.pkl"
    model_path.parent.mkdir()
    model_path.write_bytes(b"pickle-bytes")
    runtime_misc_support.write_capacity_model_manifest(model_path)
    monkeypatch.setattr(
        runtime_misc_support,
        "_sklearn_inconsistent_version_warning",
        lambda: FakeInconsistentVersionWarning,
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        loaded = runtime_misc_support.load_capacity_predictor(
            model_path,
            load_fn=lambda _stream: warnings.warn(
                "version drift",
                FakeInconsistentVersionWarning,
            )
            or {"ok": True},
            trusted_root=model_path.parent,
        )

    assert loaded == {"ok": True}
    assert caught == []

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        loaded = runtime_misc_support.load_capacity_predictor(
            model_path,
            load_fn=lambda _stream: warnings.warn("other warning", UserWarning)
            or {"ok": True},
            trusted_root=model_path.parent,
        )

    assert loaded == {"ok": True}
    assert [item.category for item in caught] == [UserWarning]


def test_load_capacity_predictor_rejects_missing_signature_manifest(tmp_path):
    model_path = tmp_path / "resources" / "balancer_model.pkl"
    model_path.parent.mkdir()
    model_path.write_bytes(b"pickle-bytes")
    calls = {"load": 0, "retrain": 0, "warnings": []}
    log = SimpleNamespace(
        warning=lambda message, path, exc: calls["warnings"].append(
            (message, path, str(exc))
        )
    )

    loaded = runtime_misc_support.load_capacity_predictor(
        model_path,
        load_fn=lambda _stream: calls.__setitem__("load", calls["load"] + 1),
        retrain_fn=lambda: calls.__setitem__("retrain", calls["retrain"] + 1),
        log=log,
        trusted_root=model_path.parent,
    )

    assert loaded is None
    assert calls["load"] == 0
    assert calls["retrain"] == 1
    assert "model manifest is missing" in calls["warnings"][0][2]


def test_load_capacity_predictor_rejects_signature_mismatch(tmp_path):
    model_path = tmp_path / "resources" / "balancer_model.pkl"
    model_path.parent.mkdir()
    model_path.write_bytes(b"pickle-bytes")
    manifest_path = runtime_misc_support.write_capacity_model_manifest(model_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["digest_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    calls = {"load": 0, "retrain": 0, "warnings": []}
    log = SimpleNamespace(
        warning=lambda message, path, exc: calls["warnings"].append(
            (message, path, str(exc))
        )
    )

    loaded = runtime_misc_support.load_capacity_predictor(
        model_path,
        load_fn=lambda _stream: calls.__setitem__("load", calls["load"] + 1),
        retrain_fn=lambda: calls.__setitem__("retrain", calls["retrain"] + 1),
        log=log,
        trusted_root=model_path.parent,
    )

    assert loaded is None
    assert calls["load"] == 0
    assert calls["retrain"] == 1
    assert "sha256 mismatch" in calls["warnings"][0][2]


def test_capacity_model_manifest_error_reports_all_validation_failures(monkeypatch, tmp_path):
    model_path = tmp_path / "resources" / "balancer_model.pkl"
    model_path.parent.mkdir()
    model_path.write_bytes(b"pickle-bytes")
    manifest_path = runtime_misc_support.write_capacity_model_manifest(model_path)
    original_payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    manifest_path.write_text("{bad json", encoding="utf-8")
    assert "model manifest is unreadable" in runtime_misc_support._capacity_model_manifest_error(model_path)

    for key, value, expected in (
        ("schema", "wrong", "schema mismatch"),
        ("model_file", "other.pkl", "file mismatch"),
        ("algorithm", "md5", "algorithm mismatch"),
        ("size_bytes", 1, "size mismatch"),
        ("digest_sha256", "", "digest missing"),
    ):
        payload = dict(original_payload)
        payload[key] = value
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        assert expected in runtime_misc_support._capacity_model_manifest_error(model_path)

    manifest_path.write_text(json.dumps(original_payload), encoding="utf-8")
    original_stat = Path.stat

    def _raise_for_model(path, *args, **kwargs):
        if path == model_path:
            raise OSError("stat blocked")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _raise_for_model)
    assert "cannot stat model file" in (
        runtime_misc_support._capacity_model_manifest_error(model_path)
    )
    assert "cannot stat model file" in runtime_misc_support._capacity_model_trust_error(
        model_path,
        model_path.parent,
    )


def test_load_capacity_predictor_retrains_when_missing(tmp_path):
    calls = {"retrain": 0}

    loaded = runtime_misc_support.load_capacity_predictor(
        tmp_path / "missing.pkl",
        retrain_fn=lambda: calls.__setitem__("retrain", calls["retrain"] + 1),
    )

    assert loaded is None
    assert calls["retrain"] == 1


def test_load_capacity_predictor_handles_legacy_module_error(tmp_path):
    model_path = tmp_path / "resources" / "balancer_model.pkl"
    model_path.parent.mkdir()
    model_path.write_bytes(b"pickle-bytes")
    runtime_misc_support.write_capacity_model_manifest(model_path)
    calls = {"retrain": 0, "warnings": []}
    log = SimpleNamespace(
        warning=lambda message, path, exc: calls["warnings"].append(
            (message, path, str(exc))
        )
    )

    loaded = runtime_misc_support.load_capacity_predictor(
        model_path,
        load_fn=lambda _stream: (_ for _ in ()).throw(
            ModuleNotFoundError("numpy.core.numeric")
        ),
        retrain_fn=lambda: calls.__setitem__("retrain", calls["retrain"] + 1),
        log=log,
        trusted_root=model_path.parent,
    )

    assert loaded is None
    assert calls["retrain"] == 1
    assert calls["warnings"]
    assert "numpy.core.numeric" in calls["warnings"][0][2]


def test_load_capacity_predictor_rejects_model_outside_trusted_root(tmp_path):
    model_path = tmp_path / "outside" / "balancer_model.pkl"
    trusted_root = tmp_path / "resources"
    model_path.parent.mkdir()
    trusted_root.mkdir()
    model_path.write_bytes(b"pickle-bytes")
    calls = {"load": 0, "retrain": 0, "warnings": []}
    log = SimpleNamespace(
        warning=lambda message, path, exc: calls["warnings"].append(
            (message, path, str(exc))
        )
    )

    loaded = runtime_misc_support.load_capacity_predictor(
        model_path,
        load_fn=lambda _stream: calls.__setitem__("load", calls["load"] + 1),
        retrain_fn=lambda: calls.__setitem__("retrain", calls["retrain"] + 1),
        log=log,
        trusted_root=trusted_root,
    )

    assert loaded is None
    assert calls["load"] == 0
    assert calls["retrain"] == 1
    assert "outside trusted resource root" in calls["warnings"][0][2]


def test_windows_capacity_model_owner_error_accepts_matching_sid(tmp_path):
    model_path = tmp_path / "balancer_model.pkl"
    model_path.write_bytes(b"pickle-bytes")

    error = runtime_misc_support._windows_capacity_model_owner_error(
        model_path,
        identities_fn=lambda _path: (
            "S-1-5-21-1000",
            ("S-1-5-21-1000",),
            "DOMAIN\\runner",
        ),
        acl_grants_fn=lambda _path: (("S-1-5-21-1000", 0x10000000),),
    )

    assert error is None


def test_windows_capacity_model_owner_error_rejects_mismatched_sid(tmp_path):
    model_path = tmp_path / "balancer_model.pkl"
    model_path.write_bytes(b"pickle-bytes")

    error = runtime_misc_support._windows_capacity_model_owner_error(
        model_path,
        identities_fn=lambda _path: (
            "S-1-5-21-2000",
            ("S-1-5-21-1000",),
            "DOMAIN\\other",
        ),
    )

    assert error == "model file is owned by DOMAIN\\other, not the current Windows token"


def test_windows_capacity_model_owner_error_accepts_token_default_owner(tmp_path):
    model_path = tmp_path / "balancer_model.pkl"
    model_path.write_bytes(b"pickle-bytes")

    error = runtime_misc_support._windows_capacity_model_owner_error(
        model_path,
        identities_fn=lambda _path: (
            "S-1-5-32-544",
            ("S-1-5-21-1000", "S-1-5-32-544"),
            "BUILTIN\\Administrators",
        ),
        acl_grants_fn=lambda _path: (),
    )

    assert error is None


@pytest.mark.parametrize(
    "trustee_sid",
    ("S-1-1-0", "S-1-5-11", "S-1-5-32-545"),
)
@pytest.mark.parametrize(
    "access_mask",
    (0x00000002, 0x00010000, 0x00040000, 0x00080000),
)
def test_windows_capacity_model_owner_error_rejects_broad_write_dacl(
    tmp_path, trustee_sid, access_mask
):
    model_path = tmp_path / "balancer_model.pkl"
    model_path.write_bytes(b"pickle-bytes")

    error = runtime_misc_support._windows_capacity_model_owner_error(
        model_path,
        identities_fn=lambda _path: (
            "S-1-5-21-1000",
            ("S-1-5-21-1000",),
            "DOMAIN\\runner",
        ),
        acl_grants_fn=lambda _path: ((trustee_sid, access_mask),),
    )

    assert error == (
        "model file grants unsafe write/delete access to untrusted Windows "
        f"principal {trustee_sid}"
    )


@pytest.mark.parametrize(
    "access_mask",
    (0x00000002, 0x00010000, 0x00040000, 0x00080000),
)
def test_windows_capacity_model_owner_error_rejects_untrusted_user_write_dacl(
    tmp_path, access_mask
):
    model_path = tmp_path / "balancer_model.pkl"
    model_path.write_bytes(b"pickle-bytes")
    trustee_sid = "S-1-5-21-2000"

    error = runtime_misc_support._windows_capacity_model_owner_error(
        model_path,
        identities_fn=lambda _path: (
            "S-1-5-21-1000",
            ("S-1-5-21-1000",),
            "DOMAIN\\runner",
        ),
        acl_grants_fn=lambda _path: ((trustee_sid, access_mask),),
    )

    assert error == (
        "model file grants unsafe write/delete access to untrusted Windows "
        f"principal {trustee_sid}"
    )


def test_windows_capacity_model_owner_error_allows_untrusted_read_only_dacl(tmp_path):
    model_path = tmp_path / "balancer_model.pkl"
    model_path.write_bytes(b"pickle-bytes")

    error = runtime_misc_support._windows_capacity_model_owner_error(
        model_path,
        identities_fn=lambda _path: (
            "S-1-5-21-1000",
            ("S-1-5-21-1000",),
            "DOMAIN\\runner",
        ),
        acl_grants_fn=lambda _path: (("S-1-5-21-2000", 0x00000001),),
    )

    assert error is None


@pytest.mark.parametrize("trustee_sid", ("S-1-5-18", "S-1-5-32-544"))
def test_windows_capacity_model_owner_error_allows_privileged_system_write_dacl(
    tmp_path, trustee_sid
):
    model_path = tmp_path / "balancer_model.pkl"
    model_path.write_bytes(b"pickle-bytes")

    error = runtime_misc_support._windows_capacity_model_owner_error(
        model_path,
        identities_fn=lambda _path: (
            "S-1-5-21-1000",
            ("S-1-5-21-1000",),
            "DOMAIN\\runner",
        ),
        acl_grants_fn=lambda _path: ((trustee_sid, 0x10000000),),
    )

    assert error is None


def test_windows_capacity_model_owner_error_allows_verified_owner_rights_write_dacl(
    tmp_path,
):
    model_path = tmp_path / "balancer_model.pkl"
    model_path.write_bytes(b"pickle-bytes")

    error = runtime_misc_support._windows_capacity_model_owner_error(
        model_path,
        identities_fn=lambda _path: (
            "S-1-5-21-1000",
            ("S-1-5-21-1000",),
            "DOMAIN\\runner",
        ),
        acl_grants_fn=lambda _path: (("S-1-3-4", 0x10000000),),
    )

    assert error is None


def test_windows_capacity_model_owner_error_rejects_owner_rights_for_untrusted_owner(
    tmp_path,
):
    model_path = tmp_path / "balancer_model.pkl"
    model_path.write_bytes(b"pickle-bytes")

    error = runtime_misc_support._windows_capacity_model_owner_error(
        model_path,
        identities_fn=lambda _path: (
            "S-1-5-21-2000",
            ("S-1-5-21-1000",),
            "DOMAIN\\other",
        ),
        acl_grants_fn=lambda _path: (("S-1-3-4", 0x10000000),),
    )

    assert error == "model file is owned by DOMAIN\\other, not the current Windows token"


def test_windows_capacity_model_owner_error_fails_closed_on_dacl_lookup_error(
    tmp_path,
):
    model_path = tmp_path / "balancer_model.pkl"
    model_path.write_bytes(b"pickle-bytes")

    def _raise_lookup(_path):
        raise OSError("ACL access denied")

    error = runtime_misc_support._windows_capacity_model_owner_error(
        model_path,
        identities_fn=lambda _path: (
            "S-1-5-21-1000",
            ("S-1-5-21-1000",),
            "DOMAIN\\runner",
        ),
        acl_grants_fn=_raise_lookup,
    )

    assert error == "cannot verify model file ACL on Windows: ACL access denied"


def test_windows_capacity_model_dacl_grants_requests_and_parses_dacl(
    tmp_path, monkeypatch
):
    model_path = tmp_path / "balancer_model.pkl"
    model_path.write_bytes(b"pickle-bytes")
    calls = {}

    class _FakeDacl:
        @staticmethod
        def IsValid():
            return True

        @staticmethod
        def GetAceCount():
            return 1

        @staticmethod
        def GetAce(_index):
            return ((0, 0), 0x00000002, "S-1-1-0")

    class _FakeSecurityDescriptor:
        @staticmethod
        def GetSecurityDescriptorDacl():
            return _FakeDacl()

    def _get_file_security(path, information):
        calls.update(path=path, information=information)
        return _FakeSecurityDescriptor()

    fake_win32security = SimpleNamespace(
        DACL_SECURITY_INFORMATION=0x00000004,
        GetFileSecurity=_get_file_security,
        ConvertSidToStringSid=lambda sid: sid,
    )
    monkeypatch.setitem(sys.modules, "win32security", fake_win32security)

    assert runtime_misc_support._windows_capacity_model_dacl_grants(model_path) == (
        ("S-1-1-0", 0x00000002),
    )
    assert calls == {
        "path": str(model_path),
        "information": fake_win32security.DACL_SECURITY_INFORMATION,
    }


def test_capacity_file_trust_checks_windows_security_for_ancestors_and_entries(
    tmp_path, monkeypatch
):
    trusted_root = tmp_path / "resources"
    model_dir = trusted_root / "models"
    model_dir.mkdir(parents=True)
    model_path = model_dir / "balancer_model.pkl"
    manifest_path = runtime_misc_support.capacity_model_manifest_path(model_path)
    model_path.write_bytes(b"pickle-bytes")
    manifest_path.write_text("{}", encoding="utf-8")
    checked = []

    def _check_security(path, *, label, **_kwargs):
        checked.append((path, label))
        return None

    monkeypatch.setattr(runtime_misc_support, "_is_windows", lambda: True)
    monkeypatch.setattr(
        runtime_misc_support,
        "_windows_capacity_model_owner_error",
        _check_security,
    )

    assert (
        runtime_misc_support._capacity_file_trust_error(
            model_path,
            trusted_root,
            label="model file",
        )
        is None
    )
    assert (
        runtime_misc_support._capacity_file_trust_error(
            manifest_path,
            trusted_root,
            label="model manifest",
        )
        is None
    )
    assert checked == [
        (trusted_root, f"trusted ancestor {trusted_root}"),
        (model_dir, f"trusted ancestor {model_dir}"),
        (model_path, "model file"),
        (trusted_root, f"trusted ancestor {trusted_root}"),
        (model_dir, f"trusted ancestor {model_dir}"),
        (manifest_path, "model manifest"),
    ]


def test_windows_capacity_model_owner_error_fails_closed_on_lookup_error(tmp_path):
    model_path = tmp_path / "balancer_model.pkl"
    model_path.write_bytes(b"pickle-bytes")

    def _raise_lookup(_path):
        raise OSError("access denied")

    error = runtime_misc_support._windows_capacity_model_owner_error(
        model_path,
        identities_fn=_raise_lookup,
    )

    assert error == "cannot verify model file ownership on Windows: access denied"


@pytest.mark.skipif(os.name != "nt", reason="native Windows ownership semantics")
def test_windows_capacity_model_owner_error_accepts_current_user_file(tmp_path):
    model_path = tmp_path / "balancer_model.pkl"
    model_path.write_bytes(b"pickle-bytes")

    assert runtime_misc_support._windows_capacity_model_owner_error(model_path) is None


def test_load_capacity_predictor_rejects_windows_owner_mismatch(
    tmp_path, monkeypatch
):
    model_path = tmp_path / "resources" / "balancer_model.pkl"
    model_path.parent.mkdir()
    model_path.write_bytes(b"pickle-bytes")
    runtime_misc_support.write_capacity_model_manifest(model_path)
    calls = {"load": 0, "retrain": 0}

    monkeypatch.setattr(runtime_misc_support, "_is_windows", lambda: True)
    monkeypatch.setattr(
        runtime_misc_support,
        "_windows_capacity_model_owner_error",
        lambda _path, **_kwargs: (
            "model file owner SID does not match the current Windows user"
        ),
    )

    loaded = runtime_misc_support.load_capacity_predictor(
        model_path,
        load_fn=lambda _stream: calls.__setitem__("load", calls["load"] + 1),
        retrain_fn=lambda: calls.__setitem__("retrain", calls["retrain"] + 1),
        trusted_root=model_path.parent,
    )

    assert loaded is None
    assert calls == {"load": 0, "retrain": 1}


@pytest.mark.skipif(os.name == "nt", reason="POSIX world-write semantics")
def test_load_capacity_predictor_rejects_world_writable_trusted_model(tmp_path):
    model_path = tmp_path / "resources" / "balancer_model.pkl"
    model_path.parent.mkdir()
    model_path.write_bytes(b"pickle-bytes")
    model_path.chmod(0o666)
    calls = {"load": 0, "retrain": 0}

    try:
        loaded = runtime_misc_support.load_capacity_predictor(
            model_path,
            load_fn=lambda _stream: calls.__setitem__("load", calls["load"] + 1),
            retrain_fn=lambda: calls.__setitem__("retrain", calls["retrain"] + 1),
            trusted_root=model_path.parent,
        )
    finally:
        model_path.chmod(0o600)

    assert loaded is None
    assert calls == {"load": 0, "retrain": 1}


@pytest.mark.skipif(os.name == "nt", reason="POSIX account database semantics")
def test_posix_group_is_user_private_rejects_shared_primary_gid(monkeypatch):
    current_user = SimpleNamespace(pw_name="runner", pw_gid=1000)
    other_user = SimpleNamespace(pw_name="other", pw_gid=1000)
    monkeypatch.setattr(runtime_misc_support.os, "geteuid", lambda: 1000)
    monkeypatch.setitem(
        sys.modules,
        "pwd",
        SimpleNamespace(
            getpwuid=lambda _uid: current_user,
            getpwall=lambda: (current_user, other_user),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "grp",
        SimpleNamespace(getgrgid=lambda _gid: SimpleNamespace(gr_mem=[])),
    )

    assert not runtime_misc_support._posix_group_is_user_private(
        SimpleNamespace(st_gid=1000)
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX account database semantics")
def test_posix_group_is_user_private_allows_proven_single_user_group(monkeypatch):
    current_user = SimpleNamespace(pw_name="runner", pw_gid=1000)
    unrelated_user = SimpleNamespace(pw_name="other", pw_gid=2000)
    monkeypatch.setattr(runtime_misc_support.os, "geteuid", lambda: 1000)
    monkeypatch.setitem(
        sys.modules,
        "pwd",
        SimpleNamespace(
            getpwuid=lambda _uid: current_user,
            getpwall=lambda: (current_user, unrelated_user),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "grp",
        SimpleNamespace(getgrgid=lambda _gid: SimpleNamespace(gr_mem=["runner"])),
    )

    assert runtime_misc_support._posix_group_is_user_private(
        SimpleNamespace(st_gid=1000)
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX group-write semantics")
def test_load_capacity_predictor_rejects_group_writable_shared_group_model(
    tmp_path, monkeypatch
):
    # Regression: a group-writable model on a shared POSIX host used to be fed
    # straight into pickle.load. Only owner-writable (or user-private-group)
    # files should be trusted.
    model_path = tmp_path / "resources" / "balancer_model.pkl"
    model_path.parent.mkdir()
    model_path.write_bytes(b"pickle-bytes")
    model_path.chmod(0o660)  # rw for owner and group, group-writable
    calls = {"load": 0, "retrain": 0, "warnings": []}
    log = SimpleNamespace(
        warning=lambda message, path, exc: calls["warnings"].append(str(exc))
    )

    # Force the "shared group" verdict so the test does not depend on the CI
    # runner's actual group membership.
    monkeypatch.setattr(
        runtime_misc_support,
        "_posix_group_is_user_private",
        lambda _stat_result: False,
    )

    try:
        loaded = runtime_misc_support.load_capacity_predictor(
            model_path,
            load_fn=lambda _stream: calls.__setitem__("load", calls["load"] + 1),
            retrain_fn=lambda: calls.__setitem__("retrain", calls["retrain"] + 1),
            log=log,
            trusted_root=model_path.parent,
        )
    finally:
        model_path.chmod(0o600)

    assert loaded is None
    assert calls["load"] == 0
    assert calls["retrain"] == 1
    assert any("group-writable" in warning for warning in calls["warnings"])


@pytest.mark.skipif(os.name == "nt", reason="POSIX group-write semantics")
def test_load_capacity_predictor_allows_group_writable_user_private_group(
    tmp_path, monkeypatch
):
    # A user-private group (only the owning user is a member) is not an
    # escalation surface, so group-write on it stays loadable.
    model_path = tmp_path / "resources" / "balancer_model.pkl"
    model_path.parent.mkdir()
    model_path.write_bytes(b"pickle-bytes")
    runtime_misc_support.write_capacity_model_manifest(model_path)
    model_path.chmod(0o660)
    calls = {"load": 0}

    monkeypatch.setattr(
        runtime_misc_support,
        "_posix_group_is_user_private",
        lambda _stat_result: True,
    )

    try:
        assert (
            runtime_misc_support._capacity_model_trust_error(
                model_path, model_path.parent
            )
            is None
        )
        loaded = runtime_misc_support.load_capacity_predictor(
            model_path,
            load_fn=lambda _stream: calls.__setitem__("load", calls["load"] + 1) or "ok",
            trusted_root=model_path.parent,
        )
    finally:
        model_path.chmod(0o600)

    assert loaded == "ok"
    assert calls["load"] == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX replace-while-open semantics")
def test_load_capacity_predictor_hashes_and_loads_from_same_descriptor(
    tmp_path, monkeypatch
):
    model_path = tmp_path / "resources" / "balancer_model.pkl"
    model_path.parent.mkdir()
    model_path.write_bytes(pickle.dumps({"source": "verified"}))
    runtime_misc_support.write_capacity_model_manifest(model_path)
    replacement_path = model_path.with_name("replacement.pkl")
    replacement_path.write_bytes(pickle.dumps({"source": "swapped"}))
    descriptor_ids = []
    original_hash = runtime_misc_support._capacity_model_sha256_stream

    def _hash_then_swap(stream):
        descriptor_stat = os.fstat(stream.fileno())
        descriptor_ids.append((descriptor_stat.st_dev, descriptor_stat.st_ino))
        digest = original_hash(stream)
        replacement_path.replace(model_path)
        return digest

    def _load_same_stream(stream):
        descriptor_stat = os.fstat(stream.fileno())
        descriptor_ids.append((descriptor_stat.st_dev, descriptor_stat.st_ino))
        return pickle.load(stream)

    monkeypatch.setattr(
        runtime_misc_support,
        "_capacity_model_sha256_stream",
        _hash_then_swap,
    )

    loaded = runtime_misc_support.load_capacity_predictor(
        model_path,
        load_fn=_load_same_stream,
        trusted_root=model_path.parent,
    )

    assert loaded == {"source": "verified"}
    assert pickle.loads(model_path.read_bytes()) == {"source": "swapped"}
    assert descriptor_ids[0] == descriptor_ids[1]


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_load_capacity_predictor_rejects_symlink_model(tmp_path):
    resources = tmp_path / "resources"
    resources.mkdir()
    target_path = resources / "target.pkl"
    target_path.write_bytes(pickle.dumps({"trusted": False}))
    model_path = resources / "balancer_model.pkl"
    model_path.symlink_to(target_path.name)
    calls = {"load": 0, "retrain": 0}

    loaded = runtime_misc_support.load_capacity_predictor(
        model_path,
        load_fn=lambda _stream: calls.__setitem__("load", calls["load"] + 1),
        retrain_fn=lambda: calls.__setitem__("retrain", calls["retrain"] + 1),
        trusted_root=resources,
    )

    assert loaded is None
    assert calls == {"load": 0, "retrain": 1}


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_load_capacity_predictor_rejects_symlink_manifest(tmp_path):
    resources = tmp_path / "resources"
    resources.mkdir()
    model_path = resources / "balancer_model.pkl"
    model_path.write_bytes(pickle.dumps({"trusted": True}))
    manifest_path = runtime_misc_support.write_capacity_model_manifest(model_path)
    target_manifest = manifest_path.with_name("manifest-target.json")
    manifest_path.replace(target_manifest)
    manifest_path.symlink_to(target_manifest.name)
    calls = {"load": 0, "retrain": 0}

    loaded = runtime_misc_support.load_capacity_predictor(
        model_path,
        load_fn=lambda _stream: calls.__setitem__("load", calls["load"] + 1),
        retrain_fn=lambda: calls.__setitem__("retrain", calls["retrain"] + 1),
        trusted_root=resources,
    )

    assert loaded is None
    assert calls == {"load": 0, "retrain": 1}


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics")
def test_load_capacity_predictor_rejects_writable_parent_inside_trusted_root(
    tmp_path,
):
    resources = tmp_path / "resources"
    model_dir = resources / "models"
    model_dir.mkdir(parents=True)
    model_path = model_dir / "balancer_model.pkl"
    model_path.write_bytes(pickle.dumps({"trusted": False}))
    runtime_misc_support.write_capacity_model_manifest(model_path)
    model_dir.chmod(0o777)
    calls = {"load": 0, "retrain": 0}

    try:
        loaded = runtime_misc_support.load_capacity_predictor(
            model_path,
            load_fn=lambda _stream: calls.__setitem__("load", calls["load"] + 1),
            retrain_fn=lambda: calls.__setitem__(
                "retrain", calls["retrain"] + 1
            ),
            trusted_root=resources,
        )
    finally:
        model_dir.chmod(0o700)

    assert loaded is None
    assert calls == {"load": 0, "retrain": 1}


@pytest.mark.skipif(os.name == "nt", reason="POSIX ownership semantics")
def test_posix_capacity_entry_rejects_foreign_owner(monkeypatch):
    monkeypatch.setattr(
        runtime_misc_support,
        "_trusted_posix_owner_ids",
        lambda: {0, 1000},
    )
    foreign_stat = SimpleNamespace(
        st_uid=2000,
        st_mode=stat.S_IFREG | 0o600,
    )

    assert runtime_misc_support._posix_capacity_entry_error(
        foreign_stat,
        label="model file",
    ) == "model file is owned by uid 2000, not the current user or root"


def test_bootstrap_capacity_predictor_sets_paths_and_logs_missing_model(tmp_path):
    agi_cls = SimpleNamespace()
    env = SimpleNamespace(resources_path=tmp_path / "resources")
    env.resources_path.mkdir(parents=True, exist_ok=True)
    calls = {"info": []}
    log = SimpleNamespace(
        info=lambda message, path: calls["info"].append((message, path))
    )

    predictor = runtime_misc_support.bootstrap_capacity_predictor(
        agi_cls,
        env,
        missing_log_message="Capacity model not found at %s; skipping bootstrap.",
        log=log,
    )

    assert predictor is None
    assert agi_cls._capacity_predictor is None
    assert agi_cls._capacity_data_file == env.resources_path / "balancer_df.csv"
    assert agi_cls._capacity_model_file == env.resources_path / "balancer_model.pkl"
    assert calls["info"] == [
        (
            "Capacity model not found at %s; skipping bootstrap.",
            agi_cls._capacity_model_file,
        )
    ]


def test_initialize_runtime_state_sets_common_runtime_fields():
    agi_cls = SimpleNamespace()
    env = SimpleNamespace(manager_path=Path("/tmp/manager"), target="demo", verbose=1)
    calls = {"info": []}
    log = SimpleNamespace(
        info=lambda message, target, verbose: calls["info"].append(
            (message, target, verbose)
        )
    )

    runtime_misc_support.initialize_runtime_state(
        agi_cls,
        env,
        workers={"127.0.0.1": 1},
        verbose=2,
        rapids_enabled=True,
        args={"secret": 1},
        worker_args={"public": 1},
        workers_data_path="/tmp/data",
        args_transform_fn=lambda args: {"public": args["secret"]},
        log=log,
        log_message="runtime for %s v%s",
    )

    assert agi_cls.env is env
    assert agi_cls.target_path == env.manager_path
    assert agi_cls._target == "demo"
    assert agi_cls._rapids_enabled is True
    assert agi_cls._args == {"public": 1}
    assert agi_cls._worker_args == {"public": 1}
    assert agi_cls.verbose == 2
    assert agi_cls._workers == {"127.0.0.1": 1}
    assert agi_cls._workers_data_path == "/tmp/data"
    assert agi_cls._run_time == {}
    assert calls["info"] == [("runtime for %s v%s", "demo", 1)]


def test_initialize_runtime_state_normalizes_workflow_module_workers_data_path():
    agi_cls = SimpleNamespace()
    env = SimpleNamespace(
        manager_path=Path("/tmp/manager"),
        target="flight_trajectory_project",
        verbose=0,
    )
    session_root = Path("/Users/agi/clustershare/agi/workflows/20260618T093102Z-492de776")

    runtime_misc_support.initialize_runtime_state(
        agi_cls,
        env,
        workers={"127.0.0.1": 1},
        verbose=0,
        rapids_enabled=False,
        args={"data_in": "flight_trajectory/dataset"},
        worker_args={"data_in": "flight_trajectory/dataset"},
        workers_data_path=str(session_root / "flight_trajectory"),
    )

    assert agi_cls._workers_data_path == str(session_root)


def test_initialize_runtime_state_preserves_workflow_session_workers_data_path():
    agi_cls = SimpleNamespace()
    env = SimpleNamespace(
        manager_path=Path("/tmp/manager"),
        target="flight_trajectory_project",
        verbose=0,
    )
    session_root = Path("/Users/agi/clustershare/agi/workflows/20260618T093102Z-492de776")

    runtime_misc_support.initialize_runtime_state(
        agi_cls,
        env,
        workers={"127.0.0.1": 1},
        verbose=0,
        rapids_enabled=False,
        args={"data_in": "flight_trajectory/dataset"},
        worker_args={"data_in": "flight_trajectory/dataset"},
        workers_data_path=str(session_root),
    )

    assert agi_cls._workers_data_path == str(session_root)


def test_initialize_runtime_state_sets_workflow_data_root_without_rebinding_cluster_share():
    agi_cls = SimpleNamespace()
    env = SimpleNamespace(
        manager_path=Path("/tmp/manager"),
        target="flight_trajectory_project",
        verbose=0,
        home_abs=Path("/home/agi"),
        AGI_CLUSTER_SHARE="clustershare/agi",
        agi_share_path="clustershare/agi",
        agi_share_path_abs=Path("/home/agi/clustershare/agi"),
        _share_root_cache=Path("/home/agi/clustershare/agi"),
        _share_target_name=lambda: "flight_trajectory",
        envars={},
    )
    session_root = "clustershare/agi/workflows/20260618T093102Z-492de776"

    runtime_misc_support.initialize_runtime_state(
        agi_cls,
        env,
        workers={"127.0.0.1": 1},
        verbose=0,
        rapids_enabled=False,
        args={"data_in": "flight_trajectory/dataset"},
        worker_args={"data_in": "flight_trajectory/dataset"},
        workers_data_path=session_root,
    )

    expected_root = (Path("/home/agi") / session_root).resolve(strict=False)
    assert agi_cls._workers_data_path == session_root
    assert env.AGI_CLUSTER_SHARE == "clustershare/agi"
    assert env.agi_share_path == "clustershare/agi"
    assert env.agi_share_path_abs == Path("/home/agi/clustershare/agi")
    assert env._share_root_cache == Path("/home/agi/clustershare/agi")
    assert env.AGILAB_WORKFLOW_DATA_ROOT == session_root
    assert env.agi_workflow_data_root == session_root
    assert env.agi_workflow_data_root_abs == expected_root
    assert env.share_target_name == "flight_trajectory"
    assert env.app_data_rel == expected_root / "flight_trajectory"
    assert env.dataframe_path == expected_root / "flight_trajectory" / "dataframe"
    assert env.envars["AGILAB_WORKFLOW_DATA_ROOT"] == session_root
    assert "AGI_CLUSTER_SHARE" not in env.envars


def test_initialize_runtime_state_preserves_scheduler_share_for_remote_workers_path():
    agi_cls = SimpleNamespace()
    scheduler_share = Path("/home/agi/data")
    env = SimpleNamespace(
        manager_path=Path("/tmp/manager"),
        target="flight_trajectory_project",
        verbose=0,
        home_abs=Path("/home/agi"),
        AGI_CLUSTER_SHARE=str(scheduler_share),
        agi_share_path=str(scheduler_share),
        agi_share_path_abs=scheduler_share,
        _share_root_cache=scheduler_share,
        _share_target_name=lambda: "flight_trajectory",
        share_target_name="scheduler",
        app_data_rel=scheduler_share / "scheduler",
        dataframe_path=scheduler_share / "scheduler" / "dataframe",
        envars={"AGI_CLUSTER_SHARE": str(scheduler_share)},
    )

    runtime_misc_support.initialize_runtime_state(
        agi_cls,
        env,
        workers={"192.168.20.15": 1},
        verbose=0,
        rapids_enabled=False,
        args={"data_in": "flight_trajectory/dataset"},
        worker_args={"data_in": "flight_trajectory/dataset"},
        workers_data_path="clustershare",
    )

    assert agi_cls._workers_data_path == "clustershare"
    assert env.AGI_CLUSTER_SHARE == str(scheduler_share)
    assert env.agi_share_path == str(scheduler_share)
    assert env.agi_share_path_abs == scheduler_share
    assert env._share_root_cache == scheduler_share
    assert env.share_target_name == "scheduler"
    assert env.app_data_rel == scheduler_share / "scheduler"
    assert env.dataframe_path == scheduler_share / "scheduler" / "dataframe"
    assert env.envars["AGI_CLUSTER_SHARE"] == str(scheduler_share)


def test_initialize_runtime_state_normalizes_windows_module_workers_data_path():
    agi_cls = SimpleNamespace()
    env = SimpleNamespace(
        manager_path=Path("/tmp/manager"),
        target="flight_trajectory_project",
        verbose=0,
    )
    session_root = (
        r"C:\Users\agi\clustershare\agi\workflows"
        r"\20260618T093102Z-492de776"
    )

    runtime_misc_support.initialize_runtime_state(
        agi_cls,
        env,
        workers={"127.0.0.1": 1},
        verbose=0,
        rapids_enabled=False,
        args={"data_in": "flight_trajectory/dataset"},
        worker_args={"data_in": "flight_trajectory/dataset"},
        workers_data_path=rf"{session_root}\flight_trajectory",
    )

    assert agi_cls._workers_data_path == session_root


def test_configure_runtime_mode_supports_default_dask_mode():
    agi_cls = SimpleNamespace(_RUN_MASK=0b001111, RAPIDS_MODE=16, DASK_MODE=4)
    env = SimpleNamespace(mode2int=lambda value: {"d": 4}[value])

    mode = runtime_misc_support.configure_runtime_mode(
        agi_cls,
        env,
        None,
        default_mode=agi_cls.DASK_MODE,
        require_dask=True,
    )

    assert mode == 4
    assert agi_cls._mode == 4
    assert agi_cls._run_types[0] == "run --no-sync"


def test_configure_runtime_mode_rejects_invalid_type_with_custom_message():
    agi_cls = SimpleNamespace(_RUN_MASK=0b001111, RAPIDS_MODE=16, DASK_MODE=4)
    env = SimpleNamespace(mode2int=lambda value: value)

    with pytest.raises(
        ValueError, match="parameter <mode> must be an int, a list of int or a string"
    ):
        runtime_misc_support.configure_runtime_mode(
            agi_cls,
            env,
            ["d"],
            invalid_type_message="parameter <mode> must be an int, a list of int or a string",
        )


def test_configure_runtime_mode_rejects_missing_default_and_unimplemented_mask():
    # New contract: the whole mode is validated against the supported bit
    # space (_RAPIDS_SET); the old masked check was a tautology that let
    # out-of-range modes such as 999 silently take the install/deploy path.
    agi_cls = SimpleNamespace(
        _RUN_MASK=0b001111, RAPIDS_MODE=16, DASK_MODE=4, _RAPIDS_SET=0b111111
    )
    env = SimpleNamespace(mode2int=lambda value: value)

    with pytest.raises(ValueError, match="parameter <mode> must be an int or a string"):
        runtime_misc_support.configure_runtime_mode(agi_cls, env, None)

    with pytest.raises(ValueError, match="mode 999 not implemented"):
        runtime_misc_support.configure_runtime_mode(agi_cls, env, 999)

    with pytest.raises(ValueError, match="mode -7 not implemented"):
        runtime_misc_support.configure_runtime_mode(agi_cls, env, -7)

    # Modes inside the supported bit space (e.g. the install bit) stay valid.
    assert runtime_misc_support.configure_runtime_mode(agi_cls, env, 16) == 16


def test_resolve_install_worker_group_supports_sb3_alias_without_import():
    assert (
        runtime_misc_support.resolve_install_worker_group(
            "Sb3TrainerWorker",
            base_worker_module="sb3_trainer_worker",
        )
        == "dag-worker"
    )


def test_resolve_install_worker_group_walks_inherited_worker_mro():
    class DagWorker:
        pass

    class CustomWorker(DagWorker):
        pass

    fake_module = SimpleNamespace(CustomWorker=CustomWorker)

    assert (
        runtime_misc_support.resolve_install_worker_group(
            "CustomWorker",
            base_worker_module="custom_worker",
            import_module_fn=lambda _name: fake_module,
        )
        == "dag-worker"
    )


def test_configure_install_worker_group_sets_resolved_alias_on_agi_cls():
    agi_cls = SimpleNamespace()
    env = SimpleNamespace(
        base_worker_cls="Sb3TrainerWorker",
        _base_worker_module="sb3_trainer_worker",
    )

    worker_group = runtime_misc_support.configure_install_worker_group(agi_cls, env)

    assert worker_group == "dag-worker"
    assert agi_cls.install_worker_group == ["dag-worker"]
    assert agi_cls.agi_workers["DagWorker"] == "dag-worker"


def test_install_worker_group_helpers_cover_none_and_unresolved_inputs():
    class _BlankBase:
        pass

    _BlankBase.__name__ = ""

    class _CustomWorker(_BlankBase):
        pass

    fake_module = SimpleNamespace(CustomWorker=_CustomWorker)

    groups = runtime_misc_support.install_worker_groups()

    assert groups["DagWorker"] == "dag-worker"
    assert runtime_misc_support.resolve_install_worker_group(None) is None
    assert runtime_misc_support.resolve_install_worker_group("CustomWorker") is None
    assert (
        runtime_misc_support.resolve_install_worker_group(
            "CustomWorker",
            base_worker_module="custom_worker",
            import_module_fn=lambda _name: fake_module,
        )
        is None
    )


def test_hardware_supports_rapids_true_and_false(monkeypatch):
    monkeypatch.setattr(runtime_misc_support.subprocess, "run", lambda *_a, **_k: None)
    assert runtime_misc_support.hardware_supports_rapids() is True

    monkeypatch.setattr(
        runtime_misc_support.subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(
            FileNotFoundError("nvidia-smi missing")
        ),
    )
    assert runtime_misc_support.hardware_supports_rapids() is False


def test_should_install_pip_checks_user_and_scripts_path(tmp_path):
    assert (
        runtime_misc_support.should_install_pip(
            getuser_fn=lambda: "agi",
            sys_prefix=str(tmp_path),
        )
        is False
    )

    assert (
        runtime_misc_support.should_install_pip(
            getuser_fn=lambda: "T01234",
            sys_prefix=str(tmp_path),
        )
        is True
    )

    scripts_dir = tmp_path / "Scripts"
    scripts_dir.mkdir()
    (scripts_dir / "pip.exe").write_text("", encoding="utf-8")
    assert (
        runtime_misc_support.should_install_pip(
            getuser_fn=lambda: "T01234",
            sys_prefix=str(tmp_path),
        )
        is False
    )


def test_format_elapsed_uses_precisedelta_callback():
    text = runtime_misc_support.format_elapsed(
        12.5,
        precisedelta_fn=lambda delta: f"{delta.total_seconds():.1f}s",
    )

    assert text == "12.5s"
