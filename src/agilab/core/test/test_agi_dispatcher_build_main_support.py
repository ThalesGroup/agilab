from pathlib import Path

from agi_node.agi_dispatcher import build as build_mod


def test_resolve_main_inputs_uses_explicit_app_path_and_normalizes_windows_style_outdirs(tmp_path):
    app_dir = tmp_path / "demo_project"
    app_dir.mkdir(parents=True, exist_ok=True)
    chdir_calls = []

    prog_name, active_app, opts, quiet, cmd, packages, raw_outdir = build_mod._resolve_main_inputs(
        [
            "--app-path",
            str(app_dir),
            "build_ext",
            "-b",
            "C:exports\\demo_worker",
            "--packages",
            "pkg_a,pkg_b",
            "--quiet",
        ],
        argv0="build.py",
        chdir_fn=lambda path: chdir_calls.append(path),
    )

    assert prog_name == "build.py"
    assert active_app == app_dir.resolve()
    assert chdir_calls == [app_dir.resolve()]
    assert cmd == "build_ext"
    assert quiet is True
    assert packages == ["pkg_a", "pkg_b"]
    assert str(opts.build_dir) == build_mod._fix_windows_drive("C:exports\\demo_worker")
    assert raw_outdir == opts.build_dir


def test_resolve_main_inputs_defaults_to_script_dir_for_bdist_egg(tmp_path):
    script_dir = tmp_path / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    chdir_calls = []

    prog_name, active_app, opts, quiet, cmd, packages, raw_outdir = build_mod._resolve_main_inputs(
        [
            "bdist_egg",
            "-d",
            str(tmp_path / "dist-out"),
            "--packages",
            "agi_env.tools",
        ],
        file_path=script_dir / "build.py",
        argv0="build.py",
        chdir_fn=lambda path: chdir_calls.append(path),
    )

    assert prog_name == "build.py"
    assert active_app == script_dir.resolve()
    assert chdir_calls == [script_dir.resolve()]
    assert cmd == "bdist_egg"
    assert quiet is False
    assert packages == ["agi_env.tools"]
    assert Path(opts.dist_dir) == tmp_path / "dist-out"
    assert raw_outdir == opts.dist_dir
