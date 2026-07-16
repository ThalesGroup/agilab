from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path
from types import ModuleType


APP_UI_PATH = Path(
    "src/agilab/apps-pages/app_ui/src/app_ui/app_ui.py"
)


def _load_app_ui_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "agilab_app_ui_concurrency_test_module",
        APP_UI_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_app_ui_serializes_and_restores_process_import_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_app_ui_module()
    coordination = ModuleType("agilab_app_ui_test_coordination")
    coordination.lock = threading.Lock()
    coordination.alpha_started = threading.Event()
    coordination.release_alpha = threading.Event()
    coordination.records = []
    coordination.active = 0
    coordination.max_active = 0

    def _enter(value: str, argv: list[str]) -> None:
        with coordination.lock:
            coordination.active += 1
            coordination.max_active = max(
                coordination.max_active,
                coordination.active,
            )
            coordination.records.append((value, list(argv)))
        if value == "alpha":
            coordination.alpha_started.set()
            assert coordination.release_alpha.wait(timeout=5)

    def _exit() -> None:
        with coordination.lock:
            coordination.active -= 1

    coordination.enter = _enter
    coordination.exit = _exit
    monkeypatch.setitem(sys.modules, coordination.__name__, coordination)

    apps: list[tuple[Path, Path]] = []
    for app_name in ("alpha", "beta"):
        active_app = tmp_path / f"{app_name}_project"
        source_root = active_app / "src"
        source_root.mkdir(parents=True)
        (source_root / "helper.py").write_text(
            f'VALUE = "{app_name}"\n',
            encoding="utf-8",
        )
        entrypoint = source_root / "app_ui_entry.py"
        entrypoint.write_text(
            "import sys\n"
            "import helper\n"
            "import agilab_app_ui_test_coordination as coordination\n\n"
            "def main():\n"
            "    coordination.enter(helper.VALUE, sys.argv)\n"
            "    coordination.exit()\n",
            encoding="utf-8",
        )
        apps.append((entrypoint, active_app))

    original_argv = list(sys.argv)
    original_path = list(sys.path)
    original_helper = sys.modules.get("helper")
    errors: list[BaseException] = []

    def _run(entrypoint: Path, active_app: Path) -> None:
        try:
            module._run_app_ui(entrypoint, active_app)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first = threading.Thread(target=_run, args=apps[0])
    second = threading.Thread(target=_run, args=apps[1])
    first.start()
    assert coordination.alpha_started.wait(timeout=5)
    second.start()
    time.sleep(0.05)
    assert coordination.max_active == 1
    coordination.release_alpha.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert errors == []
    assert [record[0] for record in coordination.records] == ["alpha", "beta"]
    for (entrypoint, active_app), (_value, argv) in zip(
        apps,
        coordination.records,
    ):
        assert argv == [str(entrypoint), "--active-app", str(active_app)]
    assert coordination.max_active == 1
    assert sys.argv == original_argv
    assert sys.path == original_path
    assert sys.modules.get("helper") is original_helper
