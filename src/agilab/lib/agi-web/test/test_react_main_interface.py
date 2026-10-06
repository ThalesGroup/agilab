"""Verify native workspace mounting and rerun action delivery."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agi_web import react_main_interface as main


@pytest.mark.parametrize("runtime_kind", ["missing", "stopped", "running"])
def test_workspace_mount_keeps_manager_registry_and_forwards_controlled_data(runtime_kind):
    main._asset.cache_clear()
    main._mount.cache_clear()
    registrations, renders = [], []

    def factory(name, **options):
        registrations.append((name, options))
        def mounted(**kwargs):
            renders.append(kwargs)
            return {"action": "selected"}
        return mounted

    manager = object()
    ui = SimpleNamespace(components=SimpleNamespace(v2=SimpleNamespace(component=factory)))
    if runtime_kind != "missing":
        ui.runtime = SimpleNamespace(
            exists=lambda: runtime_kind == "running",
            get_instance=lambda: SimpleNamespace(bidi_component_registry=manager),
        )
    data = {"project": "example", "views": ["map", "curves"]}
    assert main.render_main_interface(ui, data, key="workspace") == {"action": "selected"}
    assert main.render_main_interface(ui, data, key="workspace") == {"action": "selected"}
    assert len(registrations) == 1
    name, options = registrations[0]
    assert name == "agilab_react_main_interface"
    assert options["isolate_styles"] is True
    assert options["js"] and options["css"]
    assert renders[0]["data"] == data and renders[0]["data"] is not data
    assert renders[0]["key"] == "workspace"
    assert renders[0]["height"] == "content" and renders[0]["width"] == "stretch"
    assert renders[0]["on_action_change"]() is None
    main._asset.cache_clear()
    main._mount.cache_clear()


def test_workspace_registry_replacement_mounts_again():
    main._mount.cache_clear()
    registrations = []
    def factory(name, **options):
        registrations.append(name)
        return lambda **kwargs: None
    registry = [object()]
    ui = SimpleNamespace(
        components=SimpleNamespace(v2=SimpleNamespace(component=factory)),
        runtime=SimpleNamespace(
            exists=lambda: True,
            get_instance=lambda: SimpleNamespace(bidi_component_registry=registry[0]),
        ),
    )
    main.render_main_interface(ui, {})
    registry[0] = object()
    main.render_main_interface(ui, {})
    assert registrations == ["agilab_react_main_interface"] * 2
    main._mount.cache_clear()
