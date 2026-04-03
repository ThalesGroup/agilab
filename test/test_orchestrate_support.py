from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
import tomllib


def _load_module(module_name: str, relative_path: str):
    module_path = Path(relative_path)
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


orchestrate_support = _load_module("agilab.orchestrate_support", "src/agilab/orchestrate_support.py")


def test_write_app_settings_toml_sanitizes_none_and_paths(tmp_path):
    settings_file = tmp_path / "app_settings.toml"
    payload = {
        "args": {
            "data_in": Path("/tmp/input"),
            "unused": None,
            "items": [Path("/tmp/a"), None, "b"],
        }
    }

    sanitized = orchestrate_support.write_app_settings_toml(settings_file, payload)
    written = tomllib.loads(settings_file.read_text(encoding="utf-8"))

    assert sanitized == {"args": {"data_in": "/tmp/input", "items": ["/tmp/a", "b"]}}
    assert written == sanitized


def test_evaluate_service_health_gate_detects_restart_rate():
    code, message, details = orchestrate_support.evaluate_service_health_gate(
        {
            "status": "ok",
            "workers_unhealthy_count": 0,
            "workers_running_count": 2,
            "workers_restarted_count": 2,
        },
        allow_idle=False,
        max_unhealthy=0,
        max_restart_rate=0.5,
    )

    assert code == 5
    assert "restart rate" in message
    assert details["restart_rate"] == 1.0


def test_parse_and_validate_workers_reports_invalid_values():
    errors: list[str] = []

    result = orchestrate_support.parse_and_validate_workers(
        "{'127.0.0.1': 0, '192.168.0.10': 2}",
        is_valid_ip=lambda ip: True,
        on_error=errors.append,
    )

    assert result == {"127.0.0.1": 1}
    assert errors == [
        "All worker capacities must be positive integers. Invalid entries: 127.0.0.1: 0"
    ]


def test_parse_and_validate_scheduler_rejects_invalid_port():
    errors: list[str] = []

    result = orchestrate_support.parse_and_validate_scheduler(
        "127.0.0.1:99999",
        is_valid_ip=lambda ip: ip == "127.0.0.1",
        on_error=errors.append,
    )

    assert result is None
    assert errors == ["The scheduler port in '127.0.0.1:99999' is invalid."]


def test_sanitize_for_toml_recursively_drops_none_and_converts_tuples():
    payload = {
        "a": None,
        "b": (Path("/tmp/x"), None, {"nested": None, "kept": Path("/tmp/y")}),
    }

    assert orchestrate_support.sanitize_for_toml(payload) == {
        "b": ["/tmp/x", {"kept": "/tmp/y"}]
    }


def test_extract_result_dict_from_output_uses_last_valid_dict():
    raw_output = "\n".join(
        [
            "plain log line",
            "{'ignored': 'first'}",
            "not a dict",
            "{'result': 42, 'status': 'ok'}",
        ]
    )

    assert orchestrate_support.extract_result_dict_from_output(raw_output) == {
        "result": 42,
        "status": "ok",
    }


def test_extract_result_dict_from_output_returns_none_for_non_dict_payload():
    raw_output = "\n".join(["[]", "still no dict", "{invalid"])

    assert orchestrate_support.extract_result_dict_from_output(raw_output) is None


def test_parse_benchmark_normalizes_numeric_keys():
    parsed = orchestrate_support.parse_benchmark("{1: {'score': 2}, 'name': 'ok'}")

    assert parsed == {1: {"score": 2}, "name": "ok"}


def test_coerce_setting_helpers_cover_string_and_bounds():
    assert orchestrate_support.coerce_bool_setting("YES", False) is True
    assert orchestrate_support.coerce_bool_setting("off", True) is False
    assert orchestrate_support.coerce_int_setting("-5", 3, minimum=0) == 0
    assert orchestrate_support.coerce_int_setting("bad", 3, minimum=0) == 3
    assert orchestrate_support.coerce_float_setting("9.2", 0.3, maximum=1.0) == 1.0
    assert orchestrate_support.coerce_float_setting("-1", 0.3, minimum=0.0) == 0.0


def test_safe_eval_reports_type_mismatch():
    errors: list[str] = []

    result = orchestrate_support.safe_eval(
        "['not', 'a', 'dict']",
        dict,
        "bad type",
        on_error=errors.append,
    )

    assert result is None
    assert errors == ["bad type"]


def test_parse_and_validate_workers_rejects_invalid_ips():
    errors: list[str] = []

    result = orchestrate_support.parse_and_validate_workers(
        "{'bad-host': 2}",
        is_valid_ip=lambda ip: ip == "127.0.0.1",
        on_error=errors.append,
        default_workers={"127.0.0.1": 1},
    )

    assert result == {"127.0.0.1": 1}
    assert errors == ["The following worker IPs are invalid: bad-host"]


def test_looks_like_shared_path_uses_shared_filesystem_hint(monkeypatch, tmp_path):
    share_path = tmp_path / "share"
    project_root = tmp_path / "project"

    monkeypatch.setattr(orchestrate_support, "fstype_for_path", lambda path: "nfs")

    assert orchestrate_support.looks_like_shared_path(share_path, project_root=project_root) is True


def test_looks_like_shared_path_rejects_paths_under_project_root(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    candidate = project_root / "data"
    candidate.mkdir(parents=True)

    monkeypatch.setattr(orchestrate_support, "fstype_for_path", lambda path: None)

    assert orchestrate_support.looks_like_shared_path(candidate, project_root=project_root) is False


def test_mount_table_darwin_parses_and_sorts(monkeypatch):
    orchestrate_support.mount_table.cache_clear()
    monkeypatch.setattr(orchestrate_support.sys, "platform", "darwin")
    monkeypatch.setattr(
        orchestrate_support.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="\n".join(
                [
                    "map -hosts on /net (autofs, nosuid, automounted, nobrowse)",
                    "demo:/share on /Volumes/share (nfs, nodev, nosuid, mounted by agi)",
                    "/dev/disk3s1 on / (apfs, local, read-only)",
                ]
            )
        ),
    )

    entries = orchestrate_support.mount_table()

    assert entries[0] == ("/Volumes/share", "nfs")
    assert orchestrate_support.fstype_for_path(Path("/Volumes/share/demo/file.csv")) == "nfs"
    orchestrate_support.mount_table.cache_clear()


def test_mount_table_linux_and_error_fallback(monkeypatch, tmp_path):
    orchestrate_support.mount_table.cache_clear()
    mounts = tmp_path / "mounts"
    mounts.write_text(
        "server:/share /mnt/share nfs rw 0 0\n/dev/disk1 / ext4 rw 0 0\n",
        encoding="utf-8",
    )
    real_path = Path

    def _fake_path(raw):
        if str(raw) == "/proc/mounts":
            return mounts
        return real_path(raw)

    monkeypatch.setattr(orchestrate_support.sys, "platform", "linux")
    monkeypatch.setattr(orchestrate_support, "Path", _fake_path)

    entries = orchestrate_support.mount_table()
    assert entries[0] == ("/mnt/share", "nfs")
    assert orchestrate_support.fstype_for_path(Path("/mnt/share/demo/file.csv")) == "nfs"

    orchestrate_support.mount_table.cache_clear()
    monkeypatch.setattr(orchestrate_support, "Path", lambda _raw: (_ for _ in ()).throw(OSError("boom")))
    assert orchestrate_support.mount_table() == []
    orchestrate_support.mount_table.cache_clear()


def test_macos_autofs_hint_covers_missing_map_and_static_directive(monkeypatch, tmp_path):
    monkeypatch.setattr(orchestrate_support.sys, "platform", "darwin")
    real_path = Path
    auto_master = tmp_path / "auto_master"
    auto_nfs = tmp_path / "auto_nfs"

    def _fake_path(raw):
        text = str(raw)
        if text == "/etc/auto_master":
            return auto_master
        if text == "/etc/auto_nfs":
            return auto_nfs
        return real_path(raw)

    monkeypatch.setattr(orchestrate_support, "Path", _fake_path)

    auto_master.write_text("/- -static\n", encoding="utf-8")
    auto_nfs.write_text("", encoding="utf-8")
    hint = orchestrate_support.macos_autofs_hint(Path("/mnt/agilab/share"))
    assert "replace `/- -static` with `/- auto_nfs`" in hint

    auto_master.write_text("/mnt auto_nfs\n", encoding="utf-8")
    auto_nfs.write_text("/Volumes\t-fstype=nfs demo:/Volumes\n", encoding="utf-8")
    hint = orchestrate_support.macos_autofs_hint(Path("/mnt/agilab/share"))
    assert "does not mention `/mnt`" in hint


def test_macos_autofs_hint_covers_non_darwin_and_missing_master(monkeypatch, tmp_path):
    monkeypatch.setattr(orchestrate_support.sys, "platform", "linux")
    assert orchestrate_support.macos_autofs_hint(Path("/mnt/agilab/share")) is None

    monkeypatch.setattr(orchestrate_support.sys, "platform", "darwin")
    real_path = Path

    def _fake_path(raw):
        if str(raw) == "/etc/auto_master":
            return tmp_path / "missing-auto-master"
        if str(raw) == "/etc/auto_nfs":
            return tmp_path / "missing-auto-nfs"
        return real_path(raw)

    monkeypatch.setattr(orchestrate_support, "Path", _fake_path)
    hint = orchestrate_support.macos_autofs_hint(Path("/mnt/agilab/share"))
    assert "/etc/auto_master" in hint


def test_parse_benchmark_and_safe_eval_cover_error_paths():
    with pytest.raises(ValueError, match="Input must be a string"):
        orchestrate_support.parse_benchmark(12)
    with pytest.raises(ValueError, match="Failed to decode JSON"):
        orchestrate_support.parse_benchmark("{bad json")

    errors: list[str] = []
    assert orchestrate_support.safe_eval("{", dict, "bad syntax", on_error=errors.append) is None
    assert errors == ["bad syntax"]


def test_parse_and_validate_scheduler_and_workers_cover_valid_and_fallback_paths():
    errors: list[str] = []
    assert (
        orchestrate_support.parse_and_validate_scheduler(
            "192.168.20.1:8786",
            is_valid_ip=lambda ip: ip == "192.168.20.1",
            on_error=errors.append,
        )
        == "192.168.20.1:8786"
    )
    assert (
        orchestrate_support.parse_and_validate_scheduler(
            "bad-host",
            is_valid_ip=lambda ip: False,
            on_error=errors.append,
        )
        is None
    )
    assert "invalid" in errors[-1]

    errors.clear()
    workers = orchestrate_support.parse_and_validate_workers(
        "not-a-dict",
        is_valid_ip=lambda ip: True,
        on_error=errors.append,
        default_workers={"127.0.0.1": 2},
    )
    assert workers == {"127.0.0.1": 2}
    assert errors == [
        "Workers must be provided as a dictionary of IP addresses and capacities (e.g., {'192.168.0.1': 2})."
    ]


def test_looks_like_shared_path_detects_mount_hint_under_home(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    candidate = fake_home / "clustershare" / "demo"
    candidate.mkdir(parents=True)

    monkeypatch.setattr(orchestrate_support, "fstype_for_path", lambda _path: None)
    monkeypatch.setattr(orchestrate_support.Path, "home", staticmethod(lambda: fake_home))
    monkeypatch.setattr(
        orchestrate_support.os.path,
        "ismount",
        lambda path: Path(path) == fake_home / "clustershare",
    )

    assert orchestrate_support.looks_like_shared_path(candidate, project_root=tmp_path / "project") is True
