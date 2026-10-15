"""Exercise saved zero values through the real UAV forms and native browser host."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def uav_zero_chromium_executable() -> str:
    playwright = pytest.importorskip(
        "playwright.sync_api", reason="Native UAV form robot requires Playwright"
    )
    # Resolve the existing cache before the root-test fixture isolates HOME.
    with playwright.sync_playwright() as engine:
        return engine.chromium.executable_path


def _write_form_view(view: Path, app_source: Path, settings: Path, share: Path) -> None:
    view.write_text(
        textwrap.dedent(
            f"""\
            import runpy
            from pathlib import Path
            from types import SimpleNamespace
            from agi_web import python_ui as ui

            share = Path({str(share)!r})
            env = SimpleNamespace(
                app={app_source.parent.name!r}, target={app_source.parent.name!r},
                app_settings_file={str(settings)!r},
                home_abs=Path.home(), AGILAB_EXPORT_ABS=Path.home() / "export",
                agi_share_path=share, agi_share_path_abs=share,
                AGI_LOCAL_SHARE=str(share), AGI_CLUSTER_SHARE="", envars={{}},
                share_root_path=lambda: share,
                resolve_share_path=lambda value: (share / Path(value)).resolve(),
                resolve_share_input_path=lambda value: (share / Path(value)).resolve(),
            )
            ui.session_state.setdefault("env", env)
            ui.session_state.setdefault("_env", env)
            ui.title("UAV zero parameter preservation robot")
            runpy.run_path({str(app_source / "app_args_form.py")!r}, run_name="__main__")
            """
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("app_name", ["uav_queue_project", "uav_relay_queue_project"])
def test_uav_zero_parameters_survive_native_rerun_autosave_and_fresh_session(
    app_name: str, uav_zero_chromium_executable: str
) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    from tools.agilab_web_robot import (
        ReactPythonServer,
        _free_port,
        wait_for_react_health,
    )
    from tools.agilab_widget_robot import _attach_browser_issue_capture

    repo = Path(__file__).resolve().parents[1]
    app_source = repo / "src/agilab/apps/builtin" / app_name / "src"
    module_name = app_name.removesuffix("_project")
    root = Path.home() / "agilab-uav-zero-parameter-robot"
    root.mkdir(mode=0o700)
    share = root / "share"
    share.mkdir()
    settings = root / "app_settings.toml"
    seed = (app_source / "app_settings.toml").read_text(encoding="utf-8")
    for key, value in (("queue_weight", "0.0"), ("random_seed", "0")):
        seed, replacements = re.subn(rf"(?m)^{key}\s*=.*$", f"{key} = {value}", seed)
        assert replacements == 1, f"Expected one {key} field in the public app seed"
    settings.write_text(seed, encoding="utf-8")
    initial_bytes = settings.read_bytes()
    initial_mtime = settings.stat().st_mtime_ns
    assert tomllib.loads(seed)["args"]["nfile"] == 1
    view = root / "agilab_uav_zero_parameter_robot_view.py"
    _write_form_view(view, app_source, settings, share)
    evidence = root / "agilab-uav-zero-parameter-browser-evidence"
    evidence.mkdir()
    sources = (
        app_source / "app_args_form.py",
        app_source / module_name / "app_args.py",
        Path(__file__).resolve(),
    )
    source_hashes = {
        str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sources
    }
    url = f"http://127.0.0.1:{_free_port()}"
    command = [
        sys.executable,
        "-m",
        "agi_web.react_python_host",
        str(view),
        "--address",
        "127.0.0.1",
        "--port",
        url.rsplit(":", 1)[1],
        "--no-browser",
    ]
    observations: list[dict[str, object]] = []
    diagnostics: list[dict[str, object]] = []
    passed = False
    page = None
    with ReactPythonServer(command, env=dict(os.environ), url=url) as server:
        assert wait_for_react_health(url, timeout=30).success, server.output_tail()
        with playwright.sync_playwright() as engine:
            browser = engine.chromium.launch(
                executable_path=uav_zero_chromium_executable
            )

            def open_form(stage: str):
                nonlocal page
                context = browser.new_context(viewport={"width": 1280, "height": 900})
                assert not context.cookies(), (
                    "The form must hydrate without a previous UI session"
                )
                new_page = context.new_page()
                page = new_page
                entry = {
                    "stage": stage,
                    "issues": _attach_browser_issue_capture(new_page),
                    "console": [],
                }
                diagnostics.append(entry)
                new_page.on(
                    "console",
                    lambda message: (
                        entry["console"].append(
                            {"level": message.type, "detail": message.text[:1000]}
                        )
                        if message.type in {"warning", "error"}
                        and len(entry["console"]) < 20
                        else None
                    ),
                )
                new_page.goto(url)
                new_page.get_by_role(
                    "heading", name="UAV zero parameter preservation robot", exact=True
                ).wait_for(state="visible")
                errors = new_page.locator(
                    ".py-exception, .py-error"
                ).all_text_contents()
                assert not errors, errors
                return context, new_page

            def observe(stage: str, current_page, expected_nfile: int) -> None:
                values = {
                    "queue_weight": float(
                        current_page.get_by_label(
                            "Queue weight", exact=True
                        ).input_value()
                    ),
                    "random_seed": int(
                        current_page.get_by_label(
                            "Random seed", exact=True
                        ).input_value()
                    ),
                    "nfile": int(
                        current_page.get_by_label(
                            "Number of files", exact=True
                        ).input_value()
                    ),
                }
                persisted = tomllib.loads(settings.read_text(encoding="utf-8"))["args"]
                observations.append(
                    {
                        "stage": stage,
                        "widgets": values,
                        "saved_args": {key: persisted[key] for key in values},
                        "settings_sha256": hashlib.sha256(
                            settings.read_bytes()
                        ).hexdigest(),
                    }
                )
                current_page.screenshot(
                    path=str(evidence / f"agilab-uav-zero-{app_name}-{stage}.png")
                )
                assert values == {
                    "queue_weight": 0.0,
                    "random_seed": 0,
                    "nfile": expected_nfile,
                }
                assert all(persisted[key] == value for key, value in values.items())
                assert not current_page.locator(".py-exception, .py-error").count()
                assert all(
                    not entry["issues"] and not entry["console"]
                    for entry in diagnostics
                ), f"Browser diagnostics recorded in {evidence}"

            try:
                context, page = open_form("cold")
                observe("cold", page, 1)
                assert settings.read_bytes() == initial_bytes
                assert settings.stat().st_mtime_ns == initial_mtime, (
                    "Cold hydration must not rewrite saved parameters"
                )
                playwright.expect(
                    page.get_by_text("No changes to save.", exact=True)
                ).to_be_visible()
                with page.expect_response(
                    lambda response: response.url.endswith("/api/action")
                ):
                    field = page.get_by_label("Number of files", exact=True)
                    field.fill("2")
                    field.press("Enter")
                playwright.expect(page.locator(".py-success")).to_contain_text(
                    "Saved to"
                )
                observe("saved", page, 2)
                saved_bytes, saved_mtime = (
                    settings.read_bytes(),
                    settings.stat().st_mtime_ns,
                )
                context.close()

                context, page = open_form("fresh")
                observe("fresh", page, 2)
                assert settings.read_bytes() == saved_bytes
                assert settings.stat().st_mtime_ns == saved_mtime, (
                    "Fresh hydration must not rewrite the saved zero values"
                )
                playwright.expect(
                    page.get_by_text("No changes to save.", exact=True)
                ).to_be_visible()
                passed = True
            finally:
                if not passed and page is not None and not page.is_closed():
                    page.screenshot(
                        path=str(evidence / f"agilab-uav-zero-{app_name}-failure.png")
                    )
                    (
                        evidence / f"agilab-uav-zero-{app_name}-failure-dom.html"
                    ).write_text(page.content(), encoding="utf-8")
                (
                    evidence / f"agilab-uav-zero-{app_name}-browser-evidence.json"
                ).write_text(
                    json.dumps(
                        {
                            "scenario": f"uav-zero-parameters-{app_name}",
                            "status": "passed" if passed else "failed",
                            "command": [sys.executable, "-m", "pytest", *sys.argv[1:]],
                            "source_sha256": source_hashes,
                            "observations": observations,
                            "browser_diagnostics": [
                                {
                                    "stage": entry["stage"],
                                    "issues": entry["issues"][:20],
                                    "omitted_issues": max(0, len(entry["issues"]) - 20),
                                    "console": entry["console"],
                                }
                                for entry in diagnostics
                            ],
                            "screenshots": sorted(
                                path.name for path in evidence.glob("*.png")
                            ),
                            "view_errors": []
                            if page is None or page.is_closed()
                            else page.locator(
                                ".py-exception, .py-error"
                            ).all_text_contents()[:4],
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                browser.close()
