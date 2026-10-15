"""Shared native-browser checks for saved zero parameters in public app forms."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import textwrap
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class NativeZeroFormCase:
    case_id: str
    app_name: str
    zero_values: dict[str, int | float]
    numeric_controls: dict[str, str]
    change_key: str = "nfile"
    change_label: str = "Number of files"
    initial_change_value: int = 1
    changed_value: int = 2


def native_chromium_executable() -> str:
    playwright = pytest.importorskip(
        "playwright.sync_api",
        reason="Native zero-parameter form robot requires Playwright",
    )
    # Resolve the cache before the root-test fixture isolates HOME.
    with playwright.sync_playwright() as engine:
        return engine.chromium.executable_path


def _write_form_view(view: Path, app_source: Path, settings: Path, share: Path) -> None:
    view.write_text(
        textwrap.dedent(
            f"""\
            import hashlib
            import inspect
            import json
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
            ui.title("Saved zero parameter form robot")
            form = runpy.run_path({str(app_source / "app_args_form.py")!r}, run_name="__main__")
            model = type(form["current_args"])
            model_source = Path(inspect.getsourcefile(model)).resolve()
            Path({str(settings.with_name("agilab-zero-parameter-executed-model-source.json"))!r}).write_text(
                json.dumps({{
                    "path": str(model_source),
                    "sha256": hashlib.sha256(model_source.read_bytes()).hexdigest(),
                    "module": model.__module__,
                    "qualname": model.__qualname__,
                }}),
                encoding="utf-8",
            )
            """
        ),
        encoding="utf-8",
    )


def assert_native_zero_form_roundtrip(
    case: NativeZeroFormCase, chromium_executable: str, test_source: Path
) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    from tools.agilab_web_robot import (
        ReactPythonServer,
        _free_port,
        wait_for_react_health,
    )
    from tools.agilab_widget_robot import _attach_browser_issue_capture

    repo = test_source.resolve().parents[1]
    app_source = repo / "src/agilab/apps/builtin" / case.app_name / "src"
    root = Path.home() / "agilab-native-zero-parameter-robot"
    root.mkdir(mode=0o700)
    share = root / "share"
    share.mkdir()
    settings = root / "app_settings.toml"
    seed = (app_source / "app_settings.toml").read_text(encoding="utf-8")
    assert case.zero_values and all(value == 0 for value in case.zero_values.values())
    assert case.zero_values.keys() <= case.numeric_controls.keys()
    for key, value in case.zero_values.items():
        seed, replacements = re.subn(rf"(?m)^{key}\s*=.*$", f"{key} = {value}", seed)
        assert replacements == 1, f"Expected one {key} field in the public app seed"
    settings.write_text(seed, encoding="utf-8")
    initial_bytes, initial_mtime = settings.read_bytes(), settings.stat().st_mtime_ns
    controls = {**case.numeric_controls, case.change_key: case.change_label}
    seeded_args = tomllib.loads(seed)["args"]
    expected = {key: seeded_args[key] for key in controls}
    assert expected[case.change_key] == case.initial_change_value
    view = root / "agilab_native_zero_parameter_robot_view.py"
    _write_form_view(view, app_source, settings, share)
    evidence = root / "agilab-native-zero-parameter-browser-evidence"
    evidence.mkdir()
    sources = (
        app_source / "app_args_form.py",
        app_source / case.app_name.removesuffix("_project") / "app_args.py",
        Path(__file__).resolve(),
        test_source.resolve(),
    )
    source_hashes = {
        str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sources
    }
    executed_model: dict[str, str] = {}
    stem = f"agilab-zero-parameters-{case.case_id}"
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
            browser = engine.chromium.launch(executable_path=chromium_executable)

            def open_form(stage: str):
                nonlocal page
                context = browser.new_context(viewport={"width": 1280, "height": 900})
                assert not context.cookies(), (
                    "The form must hydrate without a previous UI session"
                )
                page = context.new_page()
                entry = {
                    "stage": stage,
                    "issues": _attach_browser_issue_capture(page),
                    "console": [],
                }
                diagnostics.append(entry)
                page.on(
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
                page.goto(url)
                page.get_by_role(
                    "heading", name="Saved zero parameter form robot", exact=True
                ).wait_for(state="visible")
                errors = page.locator(".py-exception, .py-error").all_text_contents()
                assert not errors, errors
                return context

            def observe(stage: str) -> None:
                model_record = json.loads(
                    settings.with_name(
                        "agilab-zero-parameter-executed-model-source.json"
                    ).read_text(encoding="utf-8")
                )
                model_source = Path(model_record.pop("path")).resolve()
                assert model_source.is_relative_to(app_source), model_source
                model_key = str(model_source.relative_to(repo))
                assert (
                    model_record["sha256"]
                    == hashlib.sha256(model_source.read_bytes()).hexdigest()
                )
                model_record["source"] = model_key
                if executed_model:
                    assert model_record == executed_model
                executed_model.update(model_record)
                source_hashes[model_key] = model_record["sha256"]
                values = {
                    key: type(expected[key])(
                        page.get_by_label(label, exact=True).input_value()
                    )
                    for key, label in controls.items()
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
                page.screenshot(path=str(evidence / f"{stem}-{stage}.png"))
                assert values == expected
                assert all(persisted[key] == value for key, value in values.items())
                assert not page.locator(".py-exception, .py-error").count()
                assert all(
                    not item["issues"] and not item["console"] for item in diagnostics
                ), f"Browser diagnostics recorded in {evidence}"

            try:
                context = open_form("cold")
                observe("cold")
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
                    field = page.get_by_label(case.change_label, exact=True)
                    field.fill(str(case.changed_value))
                    field.press("Enter")
                playwright.expect(page.locator(".py-success")).to_contain_text(
                    "Saved to"
                )
                expected[case.change_key] = case.changed_value
                observe("saved")
                saved_bytes, saved_mtime = (
                    settings.read_bytes(),
                    settings.stat().st_mtime_ns,
                )
                context.close()

                open_form("fresh")
                observe("fresh")
                assert settings.read_bytes() == saved_bytes
                assert settings.stat().st_mtime_ns == saved_mtime, (
                    "Fresh hydration must not rewrite saved zero values"
                )
                playwright.expect(
                    page.get_by_text("No changes to save.", exact=True)
                ).to_be_visible()
                passed = True
            finally:
                if not passed and page is not None and not page.is_closed():
                    page.screenshot(path=str(evidence / f"{stem}-failure.png"))
                    (evidence / f"{stem}-failure-dom.html").write_text(
                        page.content(), encoding="utf-8"
                    )
                (evidence / f"{stem}-browser-evidence.json").write_text(
                    json.dumps(
                        {
                            "scenario": case.case_id,
                            "status": "passed" if passed else "failed",
                            "command": [sys.executable, "-m", "pytest", *sys.argv[1:]],
                            "source_sha256": source_hashes,
                            "executed_model": executed_model,
                            "observations": observations,
                            "browser_diagnostics": [
                                {
                                    "stage": item["stage"],
                                    "issues": item["issues"][:20],
                                    "omitted_issues": max(0, len(item["issues"]) - 20),
                                    "console": item["console"],
                                }
                                for item in diagnostics
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
