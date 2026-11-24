from types import SimpleNamespace

import pytest

from test._native_form_zero_robot_support import (
    _matches_widget_action_response,
    _saved_action_messages,
)


@pytest.mark.parametrize(
    ("method", "url", "body", "expected"),
    [
        ("POST", "http://127.0.0.1/api/action", {"id": "nfile", "value": 2}, True),
        ("GET", "http://127.0.0.1/api/action", {"id": "nfile", "value": 2}, False),
        ("POST", "http://127.0.0.1/api/render", {"id": "nfile", "value": 2}, False),
        ("POST", "http://127.0.0.1/api/action", {"id": "other", "value": 2}, False),
        ("POST", "http://127.0.0.1/api/action", {"id": "nfile", "value": 1}, False),
        ("POST", "http://127.0.0.1/api/action", {"id": "nfile", "value": "2"}, False),
        ("POST", "http://127.0.0.1/api/action", None, False),
    ],
)
def test_action_match_requires_edited_widget_value_and_post(method, url, body, expected):
    response = SimpleNamespace(
        url=url, request=SimpleNamespace(method=method, post_data_json=body)
    )
    assert _matches_widget_action_response(response, "nfile", 2) is expected


def test_saved_status_is_bound_to_response_even_if_later_dom_has_no_changes():
    saved = {"nodes": {"main": [
        {"kind": "container", "props": {}, "children": [
            {"kind": "success", "props": {"body": "Saved to settings.toml"}, "children": []}
        ]}
    ], "sidebar": []}}
    later = {"nodes": {"main": [
        {"kind": "info", "props": {"body": "No changes to save."}, "children": []}
    ]}}
    assert _saved_action_messages(saved) == ["Saved to settings.toml"]
    assert _saved_action_messages(later) == []
    assert _saved_action_messages({"nodes": {"main": [
        {"kind": "code", "props": {"body": "Saved to is only example text"}, "children": []}
    ]}}) == []


@pytest.mark.parametrize("payload", [None, [], {}, {"nodes": None}])
def test_missing_saved_status_cannot_qualify_an_action(payload):
    assert _saved_action_messages(payload) == []
