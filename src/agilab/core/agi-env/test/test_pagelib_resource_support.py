from __future__ import annotations

import json

import pytest

from agi_env import pagelib_resource_support as resource_support


def test_load_json_resource_reads_object_payload(tmp_path):
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "custom_buttons.json").write_text(
        json.dumps({"buttons": ["run"]}),
        encoding="utf-8",
    )

    assert resource_support.load_json_resource(resources, "custom_buttons.json") == {
        "buttons": ["run"]
    }


def test_load_json_resource_rejects_non_object_payload(tmp_path):
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "info_bar.json").write_text(json.dumps(["bad"]), encoding="utf-8")

    with pytest.raises(TypeError, match="info_bar.json must contain a JSON object"):
        resource_support.load_json_resource(resources, "info_bar.json")


def test_about_content_payload_contains_expected_message():
    payload = resource_support.about_content_payload()

    assert "About" in payload
    assert "AGILab" in payload["About"]
    assert "Data Science in Engineering" in payload["About"]
