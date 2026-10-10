from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("worker_dynamic_import_contract_tests", ROOT / "tools/worker_dynamic_import_contract.py")
assert SPEC is not None and SPEC.loader is not None
guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = guard
SPEC.loader.exec_module(guard)


def seed_worker(root: Path, name: str, class_name: str, dependencies: tuple[str, ...] = ()) -> Path:
    project = root / "apps" / f"{name}_project"
    worker = project / "src" / f"{name}_worker"
    worker.mkdir(parents=True)
    (project / "src/app_settings.toml").write_text("", encoding="utf-8")
    (project / "pyproject.toml").write_text(
        f'[project]\nname = "{name}_project"\ndependencies = {list(dependencies)!r}\n', encoding="utf-8"
    )
    (worker / "pyproject.toml").write_text(f'[project]\nname = "{name}_worker"\n', encoding="utf-8")
    (worker / f"{name}_worker.py").write_text(f"class {class_name}:\n    pass\n", encoding="utf-8")
    return worker


@pytest.fixture
def app_repo(tmp_path):
    seed_worker(tmp_path, "parent", "ParentWorker")
    child = seed_worker(tmp_path, "child", "ChildWorker", ("parent-worker>=1",))
    return tmp_path, child


def inspect(app_repo, source: str, *, worker: bool = False, filename: str = "consumer.py"):
    root, child = app_repo
    path = child / filename if worker else root / "apps" / filename
    path.write_text(source, encoding="utf-8")
    return guard.inspect_source(path, guard.discover_workers([root / "apps"]))


@pytest.mark.parametrize("source", [
    "from parent_worker.parent_worker import ParentWorker\nParentWorker()\n",
    "def run():\n    from parent_worker.parent_worker import ParentWorker as Fixed\n    return Fixed()\n",
    "import parent_worker.parent_worker as fixed\nfixed.ParentWorker.__new__(fixed.ParentWorker)\n",
    "from parent_worker import parent_worker as fixed\nfixed.ParentWorker()\n",
    "from parent_worker_cy import ParentWorker\nParentWorker()\n",
    "import parent_worker_cy as fixed\ngetattr(fixed, 'ParentWorker')()\n",
    "from importlib import import_module as load\nfixed = load('parent_worker_cy')\nfixed.ParentWorker()\n",
    "import importlib\nimportlib.import_module('parent_worker.parent_worker').ParentWorker()\n",
    "import parent_worker.parent_worker as fixed\nreturn_worker = fixed\n",
    "import parent_worker.parent_worker as fixed\ngetattr(fixed, name)()\n",
    "from parent_worker.parent_worker import *\n",
    "import parent_worker.parent_worker as fixed\nfixed.__dict__['ParentWorker']()\n",
    "import importlib\nimportlib.import_module('parent_worker.parent_worker').__dict__['ParentWorker']()\n",
])
def test_rejects_fixed_worker_dispatch(app_repo, source):
    assert inspect(app_repo, source)


@pytest.mark.parametrize("source", [
    "from agi_node.agi_dispatcher import BaseWorker\nclass ChildWorker(BaseWorker):\n    pass\n",
    "from agi_node.agi_dispatcher.workers import base_worker\nclass ChildWorker(base_worker.BaseWorker):\n    pass\n",
    "from parent_worker.parent_worker import ParentWorker\nclass ChildWorker(ParentWorker):\n    pass\n",
    "import parent_worker.parent_worker as base\nclass ChildWorker(base.ParentWorker):\n    pass\n",
    "from parent_worker.parent_worker import MILP, Demand, Flyenv\nsolver = MILP(Demand(), Flyenv())\n",
    "from parent_worker import parent_worker as helpers\nhelpers._require_sb3()\nhelpers._ensure_saved_routing_model_support()\nhelpers.PPO.load('model')\n",
    "import importlib\nimportlib.import_module('parent_worker_cy')\n",
    "import importlib\nhelpers = importlib.import_module('parent_worker_cy')\nhelpers.PPO.load('model')\n",
    "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from parent_worker.parent_worker import ParentWorker\n",
    "import parent_worker.parent_worker as helpers\nhelpers.PPO.load('model')\ndef unrelated(helpers):\n    return helpers.ParentWorker()\n",
    "from importlib import import_module as load\ndef unrelated(load):\n    return load('parent_worker.parent_worker').ParentWorker()\n",
    "import importlib as lib\ndef unrelated(lib):\n    return lib.import_module('parent_worker.parent_worker').ParentWorker()\n",
])
def test_preserves_sdk_bases_inheritance_helpers_and_checkpoint_providers(app_repo, source):
    assert inspect(app_repo, source, worker=True) == []


def test_own_relative_package_export_is_allowed(app_repo):
    assert inspect(app_repo, "from .child_worker import ChildWorker\n", worker=True, filename="__init__.py") == []


def test_sdk_base_class_alias_breaks_real_ast_discovery_and_is_rejected(app_repo):
    from agi_env.project.worker_source_support import get_base_worker_cls

    _root, child = app_repo
    source = "from agi_node.polars_worker import PolarsWorker as Engine\nclass ChildWorker(Engine):\n    pass\n"
    findings = inspect(app_repo, source, worker=True, filename="child_worker.py")
    assert get_base_worker_cls(child / "child_worker.py", "ChildWorker") == (None, None)
    assert findings and "Renamed" in findings[0].message

    source = "import agi_node.polars_worker as engine\nclass ChildWorker(engine.PolarsWorker):\n    pass\n"
    assert inspect(app_repo, source, worker=True, filename="child_worker.py") == []
    assert get_base_worker_cls(child / "child_worker.py", "ChildWorker") == ("PolarsWorker", "agi_node.polars_worker")


def test_inherited_worker_must_declare_parent_and_keep_original_class_name(app_repo):
    root, child = app_repo
    (child.parents[1] / "pyproject.toml").write_text('[project]\nname = "child_project"\n', encoding="utf-8")
    findings = inspect(app_repo, "from parent_worker.parent_worker import ParentWorker\nclass ChildWorker(ParentWorker):\n    pass\n", worker=True)
    assert "declared parent" in findings[0].message
    findings = inspect(app_repo, "from parent_worker.parent_worker import ParentWorker as Renamed\nclass ChildWorker(Renamed):\n    pass\n", worker=True)
    assert "Renamed" in findings[0].message


def test_cli_fails_on_bypass_and_empty_inventory(app_repo, capsys):
    root, _ = app_repo
    assert guard.main(["--repo-root", str(root)]) == 0
    inspect(app_repo, "from parent_worker_cy import ParentWorker\n")
    assert guard.main(["--repo-root", str(root)]) == 1
    with pytest.raises(SystemExit) as exc:
        guard.main(["--repo-root", str(root / "missing")])
    assert exc.value.code == 2
    capsys.readouterr()


def test_real_production_sources_obey_worker_dispatch_contract():
    report = guard.inspect_roots(ROOT)
    assert report["worker_packages_checked"] >= 14
    assert report["passed"], report["findings"]
