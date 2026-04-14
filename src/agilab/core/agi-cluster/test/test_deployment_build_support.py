from types import SimpleNamespace

import agi_cluster.agi_distributor.deployment_build_support as build_support_module


def test_project_uv_only_enables_free_threading_when_runtime_supports_it(monkeypatch):
    env = SimpleNamespace(
        is_free_threading_available=True,
        uv="uv --quiet",
        envars={"127.0.0.1_CMD_PREFIX": "export PATH=\"~/.local/bin:$PATH\";"},
    )

    monkeypatch.setattr(build_support_module, "python_supports_free_threading", lambda: False)
    assert build_support_module._project_uv(env) == "uv --quiet"

    monkeypatch.setattr(build_support_module, "python_supports_free_threading", lambda: True)
    assert build_support_module._project_uv(env) == (
        'export PATH="~/.local/bin:$PATH"; PYTHON_GIL=0 uv --quiet'
    )
