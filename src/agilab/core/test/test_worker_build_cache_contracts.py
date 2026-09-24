"""Cython cache and headless packaging contracts without compiling extensions."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_node.agi_dispatcher import build


@pytest.fixture
def worker_build(tmp_path, monkeypatch):
    monkeypatch.delenv(build.CYTHON_DISABLE_BUILD_CACHE_ENV, raising=False)
    source = tmp_path / "worker.py"
    source.write_text("value = 1\n")
    source.with_suffix(".pyx").write_text("value = 1\n")
    output = tmp_path / "output/dist"
    output.mkdir(parents=True)
    (output / "worker_cy.so").write_bytes(b"synthetic compiled artifact")
    env = SimpleNamespace(
        home_abs=tmp_path, worker_path=source, pyvers_worker="3.13", active_app=tmp_path
    )
    return env, {"env": env, "out_arg": "output", "worker_module": "worker"}


def test_cython_stamp_round_trip_and_source_change_invalidation(worker_build):
    env, args = worker_build
    assert build._cython_build_stamp_hit(**args) is False
    build._record_cython_build_stamp(**args)
    assert build._cython_build_stamp_hit(**args) is True
    stamp = build._cython_build_stamp_path(home_abs=env.home_abs, out_arg="output")
    assert json.loads(stamp.read_text())["schema"] == "agilab-cython-build-stamp-v1"
    env.worker_path.write_text("value = 2\n")
    assert build._cython_build_stamp_hit(**args) is False


@pytest.mark.parametrize(
    "condition", ["disabled", "no-home", "no-output", "no-source", "no-pyx", "bad-path"]
)
def test_cython_stamp_never_authorizes_build_without_required_evidence(
    worker_build, monkeypatch, condition
):
    env, args = worker_build
    if condition == "disabled":
        monkeypatch.setenv(build.CYTHON_DISABLE_BUILD_CACHE_ENV, "yes")
    elif condition == "no-home":
        del env.home_abs
    elif condition == "no-output":
        (env.home_abs / "output/dist/worker_cy.so").unlink()
    elif condition == "no-source":
        env.worker_path.unlink()
    elif condition == "no-pyx":
        env.worker_path.with_suffix(".pyx").unlink()
    else:
        env.worker_path = object()
    assert build._cython_build_stamp_hit(**args) is False
    build._record_cython_build_stamp(**args)
    if hasattr(env, "home_abs"):
        assert not build._cython_build_stamp_path(
            home_abs=env.home_abs, out_arg="output"
        ).exists()


@pytest.mark.parametrize("payload", ["broken json", "[]", '{"schema":"obsolete"}'])
def test_cython_stamp_malformed_or_obsolete_payload_is_cache_miss(
    worker_build, payload
):
    env, args = worker_build
    stamp = build._cython_build_stamp_path(home_abs=env.home_abs, out_arg="output")
    stamp.write_text(payload)
    assert build._cython_build_stamp_hit(**args) is False


def test_cython_stamp_unreadable_file_is_cache_miss(worker_build, monkeypatch):
    env, args = worker_build
    build._record_cython_build_stamp(**args)
    stamp = build._cython_build_stamp_path(home_abs=env.home_abs, out_arg="output")
    original = Path.read_text

    def read(path, *values, **kwargs):
        if path == stamp:
            raise PermissionError("stamp inaccessible")
        return original(path, *values, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    assert build._cython_build_stamp_hit(**args) is False


def test_headless_cache_cleanup_preserves_nested_apps_and_unrelated_bytecode(tmp_path):
    app_root = tmp_path / "project"
    locations = [app_root / "build/lib", app_root / "build/bdist.test/egg"]
    expected = set()
    for location in locations:
        location.mkdir(parents=True)
        ui = location / "app_args_form.py"
        ui.write_text("import streamlit")
        expected.add(ui)
        cache = location / "__pycache__"
        cache.mkdir()
        stale = cache / "app_args_form.cpython-313.pyc"
        stale.write_bytes(b"stale UI")
        expected.add(stale)
        (cache / "worker.cpython-313.pyc").write_bytes(b"keep worker")
        nested = location / "nested/app_args_form.py"
        nested.parent.mkdir()
        nested.write_text("preserve nested package")
    assert set(build._purge_top_level_ui_build_artifacts(app_root)) == expected
    for location in locations:
        assert (
            location / "__pycache__/worker.cpython-313.pyc"
        ).read_bytes() == b"keep worker"
        assert (
            location / "nested/app_args_form.py"
        ).read_text() == "preserve nested package"
    assert build._purge_top_level_ui_build_artifacts(app_root) == []


def test_headless_cleanup_removes_empty_bytecode_directory(tmp_path):
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "app_args_form.cpython-313.pyc").write_bytes(b"UI")
    assert build._remove_top_level_ui_modules(tmp_path)
    assert not cache.exists()


@pytest.mark.parametrize("links", [False, True])
def test_egg_postprocess_fresh_source_skips_regeneration_and_cleans_owned_links(
    worker_build, tmp_path, monkeypatch, links
):
    from agi_env.cython_build_config import add_cython_pyx_stamp, cython_pyx_stamp_line

    env, _ = worker_build
    import logging

    monkeypatch.setattr(
        build.AgiEnv, "logger", logging.getLogger("build-contract-test")
    )
    source = Path(env.worker_path).read_text()
    Path(env.worker_path).with_suffix(".pyx").write_text(
        add_cython_pyx_stamp(
            source, stamp_line=cython_pyx_stamp_line(source, type_preprocess=True)
        )
    )
    monkeypatch.setenv("AGILAB_CYTHON_TYPE_PREPROCESS", "1")
    owned = tmp_path / "owned.py"
    owned.symlink_to(env.worker_path)
    calls = []
    build._postprocess_bdist_egg_output(
        env=env,
        out_dir=tmp_path / "output",
        links_created=[owned] if links else [],
        subprocess_run_fn=lambda *a, **k: calls.append((a, k)),
    )
    assert calls == []
    assert owned.is_symlink() is (not links)


def test_egg_postprocess_regeneration_failure_preserves_link_for_diagnostics(
    worker_build, tmp_path
):
    import subprocess

    env, _ = worker_build
    owned = tmp_path / "owned.py"
    owned.symlink_to(env.worker_path)

    def fail(command, *, check):
        assert check is True
        assert "remove_decorators" in command
        raise subprocess.CalledProcessError(7, command)

    with pytest.raises(subprocess.CalledProcessError) as exc:
        build._postprocess_bdist_egg_output(
            env=env,
            out_dir=tmp_path / "output",
            links_created=[owned],
            subprocess_run_fn=fail,
        )
    assert exc.value.returncode == 7
    assert owned.is_symlink()


def test_cython_freshness_cannot_trust_unreadable_source(worker_build, monkeypatch):
    env, _ = worker_build
    source = Path(env.worker_path)
    original = Path.read_text

    def read(path, *args, **kwargs):
        if path == source:
            raise PermissionError("source denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    assert not build._worker_cython_source_is_fresh(
        source, source.with_suffix(".pyx"), type_preprocess=False
    )
