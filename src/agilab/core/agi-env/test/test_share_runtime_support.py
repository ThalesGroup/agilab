from pathlib import Path

import agi_env.share_runtime_support as share_runtime_module


def test_share_runtime_helpers_cover_target_path_modes_and_ip_validation(tmp_path: Path):
    share_root = tmp_path / "clustershare"
    share_root.mkdir()

    assert share_runtime_module.share_target_name("demo_project", "ignored_project") == "demo"
    assert share_runtime_module.share_target_name(None, "demo_worker") == "demo"
    assert share_runtime_module.share_target_name(None, None) == "app"

    assert share_runtime_module.resolve_share_path(None, share_root) == share_root
    assert share_runtime_module.resolve_share_path("demo/data", share_root) == share_root / "demo" / "data"
    assert share_runtime_module.resolve_share_path("/tmp/absolute", share_root) == Path("/tmp/absolute").resolve(strict=False)

    assert share_runtime_module.mode_to_str(0b0111, hw_rapids_capable=False) == "_dcp"
    assert share_runtime_module.mode_to_str(0b0111, hw_rapids_capable=True) == "rdcp"
    assert share_runtime_module.mode_to_int("pc") == 6

    assert share_runtime_module.is_valid_ip("192.168.20.130") is True
    assert share_runtime_module.is_valid_ip("999.1.1.1") is False


def test_python_supports_free_threading_prefers_runtime_probe(monkeypatch):
    monkeypatch.setattr(share_runtime_module.sys, "_is_gil_enabled", lambda: False, raising=False)

    assert share_runtime_module.python_supports_free_threading() is True


def test_python_supports_free_threading_falls_back_to_sysconfig(monkeypatch):
    monkeypatch.delattr(share_runtime_module.sys, "_is_gil_enabled", raising=False)
    monkeypatch.setattr(
        share_runtime_module.sysconfig,
        "get_config_var",
        lambda name: 1 if name == "Py_GIL_DISABLED" else None,
    )

    assert share_runtime_module.python_supports_free_threading() is True
