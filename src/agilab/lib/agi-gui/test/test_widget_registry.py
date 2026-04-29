from __future__ import annotations

import pytest

from agi_gui import (
    WidgetRegistry,
    WidgetSpec,
    action_button,
    action_row,
    agi_file_picker,
    compact_choice,
    confirm_button,
    default_widget_registry,
    get_widget,
    widget_registry_rows,
)


def test_default_widget_registry_exposes_core_widgets() -> None:
    registry = default_widget_registry()

    assert registry.keys() == (
        "file_picker",
        "compact_choice",
        "action_button",
        "action_row",
        "confirm_button",
        "empty_state",
        "notice",
        "status_container",
        "toast",
    )
    assert registry.require("file_picker").widget is agi_file_picker
    assert registry.require("compact_choice").widget is compact_choice


def test_default_widget_registry_resolves_aliases() -> None:
    registry = default_widget_registry()

    assert registry.require("agi_file_picker").key == "file_picker"
    assert registry.require("path-picker").key == "file_picker"
    assert registry.require("choice").key == "compact_choice"
    assert registry.require("command button").key == "action_button"
    assert get_widget("notify") is registry.require("toast").widget


def test_default_widget_registry_groups_by_category() -> None:
    registry = default_widget_registry()

    assert registry.categories() == ("file", "choice", "action", "feedback")
    assert tuple(spec.key for spec in registry.by_category("action")) == (
        "action_button",
        "action_row",
        "confirm_button",
    )
    assert registry.by_category("missing") == ()


def test_widget_registry_rows_are_renderable_metadata() -> None:
    rows = widget_registry_rows()

    assert rows[0] == {
        "key": "file_picker",
        "label": "File picker",
        "category": "file",
        "qualified_name": "agi_gui.file_picker.agi_file_picker",
        "description": "Server-side Streamlit path picker with root validation.",
        "aliases": "agi_file_picker, picker, path_picker",
        "tags": "filesystem, upload, selection",
    }
    assert {row["key"] for row in rows} >= {"compact_choice", "action_button", "toast"}


def test_widget_registry_unknown_key_error_lists_available_widgets() -> None:
    registry = default_widget_registry()

    with pytest.raises(KeyError, match="Unknown agi-gui widget 'missing'"):
        registry.require("missing")


def test_widget_registry_can_register_custom_widgets() -> None:
    registry = WidgetRegistry()
    spec = WidgetSpec(
        key="custom_action",
        label="Custom action",
        widget=action_button,
        module="demo.widgets",
        category="action",
        aliases=("custom",),
    )

    updated = registry.register(spec)

    assert len(registry) == 0
    assert updated.require("custom_action") is spec
    assert updated.require("custom") is spec
    assert updated.as_rows()[0]["qualified_name"] == "demo.widgets.action_button"


def test_widget_registry_helpers_cover_lookup_and_call_edges() -> None:
    calls = []

    def custom_widget(*args, **kwargs):
        calls.append((args, kwargs))
        return "rendered"

    spec = WidgetSpec(
        key="custom",
        label="Custom",
        widget=custom_widget,
        module="demo.widgets",
        category="demo",
        aliases=("Alias Name",),
    )
    registry = WidgetRegistry((spec,))

    assert "alias-name" in registry
    assert object() not in registry
    assert tuple(registry) == (spec,)
    assert registry.widgets == (spec,)
    assert registry.get("missing", "fallback") == "fallback"
    assert spec("value", enabled=True) == "rendered"
    assert calls == [(("value",), {"enabled": True})]


@pytest.mark.parametrize(
    ("kwargs", "error_type", "match"),
    [
        ({"key": "  "}, ValueError, "Widget key"),
        ({"label": "  "}, ValueError, "Widget label"),
        ({"widget": "not callable"}, TypeError, "must be callable"),
        ({"module": "  "}, ValueError, "Widget module"),
        ({"category": "  "}, ValueError, "Widget category"),
    ],
)
def test_widget_spec_rejects_invalid_metadata(kwargs, error_type, match) -> None:
    payload = {
        "key": "custom",
        "label": "Custom",
        "widget": action_button,
        "module": "demo.widgets",
        "category": "demo",
    }
    payload.update(kwargs)

    with pytest.raises(error_type, match=match):
        WidgetSpec(**payload)


def test_widget_registry_rejects_duplicate_aliases() -> None:
    first = WidgetSpec(
        key="first",
        label="First",
        widget=action_row,
        module="demo.widgets",
        category="action",
        aliases=("duplicate",),
    )
    second = WidgetSpec(
        key="second",
        label="Second",
        widget=confirm_button,
        module="demo.widgets",
        category="action",
        aliases=("duplicate",),
    )

    with pytest.raises(ValueError, match="already registered"):
        WidgetRegistry((first, second))


def test_widget_registry_rejects_empty_alias() -> None:
    spec = WidgetSpec(
        key="custom",
        label="Custom",
        widget=action_button,
        module="demo.widgets",
        category="demo",
        aliases=("",),
    )

    with pytest.raises(ValueError, match="empty alias"):
        WidgetRegistry((spec,))
