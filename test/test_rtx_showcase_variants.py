"""RTX builds keep their own verified bundles, routes and session results."""
import hashlib
import importlib
import io
import json
import shutil
import zipfile

import pytest
from streamlit.testing.v1 import AppTest

from agilab.demos import notebook_showcase

VARIANTS = [('text', 'text', 'analysis_result'), ('forecast', 'forecast', 'analysis'),
            ('free_threading', 'threading', 'analysis'), ('milp_energy', 'milp', 'milp_energy_saved')]


@pytest.mark.parametrize('module_name,route,state_key', VARIANTS)
def test_rtx_bundle_has_distinct_execution_and_exact_download(module_name, route, state_key):
    module = importlib.import_module(f'agilab.demos.{module_name}_showcase')
    report = module.load_report(rtx=True)
    assert report['status'] == 'passed'
    assert report['run_id'] not in {module.load_report()['run_id'], module.load_report(astra=True)['run_id']}
    assert report['cluster_build']['model_message_count'] > 0
    assert report['cluster_build']['source_provenance_status'] == 'passed'
    assert report['cluster_build']['human_app_code_edits'] is False
    assert report['cluster_build']['cloud_codegen_fallback'] is False
    assert report['cluster_build']['node'] in {'rtx1', 'rtx4', 'rtx5'}
    assert report['cluster_build']['workflow_mode'] == 'hybrid_supervision_local_codegen'
    metrics = report['code_metrics']
    assert metrics['loc'] == metrics['application_loc'] + metrics['notebook_loc']
    assert metrics['kloc'] == metrics['loc'] / 1000
    for measured in metrics['files']:
        assert report['files'][measured['file']] == measured['sha256']
    with zipfile.ZipFile(io.BytesIO(module.download_bundle(rtx=True))) as archive:
        assert json.loads(archive.read('result.json')) == report
        for name, digest in report['files'].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest


@pytest.mark.parametrize('module_name,route,state_key', VARIANTS)
def test_rtx_tamper_is_rejected_without_affecting_other_flavours(module_name, route, state_key, monkeypatch, tmp_path):
    module = importlib.import_module(f'agilab.demos.{module_name}_showcase')
    original = module.load_report()['files']['app.py']
    destination = tmp_path / 'rtx'
    shutil.copytree(module.RTX_DEMO_ROOT, destination, ignore=shutil.ignore_patterns('__pycache__'))
    monkeypatch.setattr(module, 'RTX_DEMO_ROOT', destination)
    (destination / 'app.py').write_text("raise AssertionError('unverified RTX app')")
    with pytest.raises(ValueError, match='changed'):
        module.download_bundle(rtx=True)
    assert module.load_report()['files']['app.py'] == original
    assert module.load_report(astra=True)['status'] == 'passed'


@pytest.mark.parametrize('module_name,route,state_key', VARIANTS + [
    ('text', 'text', 'last_result'), ('forecast', 'forecast', 'result'), ('forecast', 'forecast', 'error'),
    ('free_threading', 'threading', 'last_results'), ('free_threading', 'threading', 'last_signature'),
    *[('milp_energy', 'milp', key) for key in (
        'result', 'ran_at', 'run_error', 'benchmark', 'benchmark_ran_at', 'benchmark_error',
    )],
])
def test_three_flavours_keep_results_separate_after_interrupted_rtx_app(module_name, route, state_key, monkeypatch):
    module = importlib.import_module(f'agilab.demos.{module_name}_showcase')
    state = {state_key: {'external': True}}
    monkeypatch.setattr(module.st, 'session_state', state)
    payload = {f'{name}.py': b'' for name in ('text_core', 'forecast_core', 'agilab_pool',
               'free_threading_core', 'benchmark', 'energy_core', 'energy_runner')}

    def run(flavour, expected, fail=False):
        root = {'astra':module.ASTRA_DEMO_ROOT, 'rtx':module.RTX_DEMO_ROOT, 'qwen':module.DEMO_ROOT}[flavour]
        payload['app.py'] = (
            'import streamlit as st\n'
            f'assert __file__ == {str(root / "app.py")!r}\n'
            f'assert st.session_state.get({state_key!r}, 0) == {expected}\n'
            f'st.session_state[{state_key!r}] = {expected + 1}\n'
            + ("raise RuntimeError('interrupted RTX app')\n" if fail else '')
        ).encode()
        module._run_verified_app(payload, astra=flavour == 'astra', rtx=flavour == 'rtx')

    for flavour in ('qwen', 'astra', 'rtx'):
        run(flavour, 0)
    with pytest.raises(RuntimeError, match='interrupted RTX'):
        run('rtx', 1, fail=True)
    run('astra', 1)
    run('qwen', 1)
    run('rtx', 2)
    assert state[state_key] == {'external': True}


@pytest.mark.parametrize('route', ['iris', 'text', 'forecast', 'threading', 'milp'])
def test_gallery_routes_rtx_and_displays_size_metric(route, monkeypatch, tmp_path):
    from agilab.demos import forecast_showcase
    monkeypatch.setattr(forecast_showcase, '_prepare_model', lambda _: tmp_path)
    monkeypatch.setattr(forecast_showcase, '_validate_model', lambda p: p)
    monkeypatch.setattr(forecast_showcase, '_run_verified_app', lambda *args, **kwargs: None)
    at = AppTest.from_file(notebook_showcase.__file__, default_timeout=60)
    at.query_params['demo'] = route + '_rtx'
    at.run()
    assert not at.exception and not at.error
    assert at.segmented_control(key='demo').value == route + '_rtx'
    assert at.title[0].value == 'Built by OpenCode with local Qwen'
    assert len([m for m in at.main.metric if m.label == 'Generated Python · KLOC']) == 1
    rates = [m for m in at.main.metric if m.label == 'Build output · lines/min']
    if route == 'iris':
        report = notebook_showcase.load_report(notebook_showcase.RTX_DEMO_ROOT)
    else:
        name = {'threading':'free_threading', 'milp':'milp_energy'}.get(route, route)
        report = importlib.import_module(f'agilab.demos.{name}_showcase').load_report(rtx=True)
    assert len(rates) == 1
    assert rates[0].value == f"{report['code_metrics']['loc'] * 60 / report['seconds']:.1f}"
    assert any('RTX' in caption.value for caption in at.caption)
    assert any('OpenCode used local Qwen' in caption.value and 'Codex supervised' in caption.value
               for caption in at.caption)


def test_rtx_milp_ui_helpers_do_not_import_the_solver():
    """Rendering controls must not load PyPSA/PROJ into the shared UI process."""
    import subprocess
    import sys

    from agilab.demos import milp_energy_showcase

    result = subprocess.run(
        [sys.executable, "-c",
         "import sys, energy_core, energy_runner; "
         "assert 'pypsa' not in sys.modules, 'UI helpers eagerly imported PyPSA'"],
        cwd=milp_energy_showcase.RTX_DEMO_ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_rtx_benchmark_does_not_shadow_its_functions():
    import ast

    from agilab.demos import free_threading_showcase

    source = (free_threading_showcase.RTX_DEMO_ROOT / "benchmark.py").read_text()
    definitions = [
        node.name for node in ast.parse(source).body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    ]
    assert len(definitions) == len(set(definitions))


def test_rtx_analysis_keeps_downloaded_source_immutable(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys

    from agilab.demos import free_threading_showcase

    interpreter = os.environ.get("AGILAB_FREE_THREADING_PYTHON")
    if not interpreter or not Path(interpreter).is_file():
        pytest.skip("Set AGILAB_FREE_THREADING_PYTHON to run the real free-threaded UI regression")
    _, payload = free_threading_showcase._read_verified_bundle(rtx=True)
    names = ("app.py", "benchmark.py", "free_threading_core.py", "agilab_pool.py")
    project = tmp_path / "bundle"
    project.mkdir()
    for name in names:
        (project / name).write_bytes(payload[name])
    code = (
        "from streamlit.testing.v1 import AppTest; "
        "a=AppTest.from_file('app.py', default_timeout=90); a.run(); "
        "assert not a.exception and not a.error; "
        "next(b for b in a.button if b.label=='Run analysis').click().run(); "
        "assert not a.exception and not a.error, "
        "([e.value for e in a.exception], [e.value for e in a.error])"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=project,
        env={**os.environ, "PYTHONPATH": str(project)},
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    delivered = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert delivered == {name: payload[name] for name in names}


def test_rtx_milp_attributes_measurements_to_its_generated_runner(monkeypatch):
    import ast

    from agilab.demos import milp_energy_showcase

    report, payload = milp_energy_showcase._read_verified_bundle(rtx=True)
    assert report["engine"]["role"] == "bundled_reference_only"
    assert report["benchmark_runtime"]["agilab_pool_execution_measured"] is False
    assert report["benchmark_runtime"]["entrypoint"] == "energy_runner.py"
    for name in ("energy_core.py", "energy_runner.py"):
        imports = [
            alias.name for node in ast.walk(ast.parse(payload[name]))
            if isinstance(node, ast.Import) for alias in node.names
        ]
        imports.extend(
            node.module for node in ast.walk(ast.parse(payload[name]))
            if isinstance(node, ast.ImportFrom)
        )
        assert "agilab_pool" not in imports
    monkeypatch.setattr(milp_energy_showcase, "_run_verified_app", lambda *a, **k: None)
    app = AppTest.from_string(
        "from agilab.demos.milp_energy_showcase import render; render(rtx=True)"
    ).run()
    assert not app.exception and not app.error
    assert any("not the measured executor" in caption.value for caption in app.caption)
