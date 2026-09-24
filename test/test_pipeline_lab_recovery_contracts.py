"""Observable WORKFLOW recovery and rejected deletion contracts."""
from types import SimpleNamespace

import pytest

from test import test_pipeline_lab as support

pipeline_lab = support.pipeline_lab


@pytest.fixture
def lab_ui(monkeypatch, tmp_path):
    state = {"demo": [0, "", "", "", "", "", 0], "demo__run_sequence": [0]}
    fake = support._FakeStreamlit(state, multiselects={"demo_run_sequence_widget": [0]})
    monkeypatch.setattr(pipeline_lab, "st", fake)
    for name, value in {
        "get_available_virtualenvs": lambda _env: [],
        "normalize_runtime_path": lambda raw: str(raw) if raw else "",
        "_is_valid_runtime_root": bool,
        "get_existing_snippets": lambda *a, **k: {},
        "get_custom_buttons": lambda: [],
        "get_info_bar": lambda: {},
        "get_css_text": lambda: {},
        "code_editor": lambda *a, **k: None,
    }.items():
        monkeypatch.setattr(pipeline_lab, name, value)
    entries = [{"D":"", "Q":"question", "M":"model", "C":"print('stage')", "E":""}]
    deps = support._make_lab_deps(
        load_all_stages=lambda *a, **k: entries,
        load_pipeline_conceptual_dot=lambda *a, **k: (None, None),
        render_pipeline_view=lambda *a, **k: None,
        inspect_pipeline_run_lock=lambda *a, **k: None)
    env = SimpleNamespace(active_app=tmp_path / "demo_project", envars={}, app="demo_project")
    def render():
        pipeline_lab.display_lab_tab(tmp_path, "demo", tmp_path / "lab_stages.toml",
                                     tmp_path / "demo_project", env, deps)
    return fake, render, entries


def test_recovered_run_evidence_is_visible_and_corrupt_preferences_fall_back(lab_ui, monkeypatch, tmp_path):
    fake, render, entries = lab_ui
    fake.session_state.update({
        "demo__pipeline_profile": "removed-profile",
        "demo__run_state_hydrated_notice": "Recovered previous run from disk.",
        "demo__last_pipeline_manifest_file": str(tmp_path / "run.json"),
        "demo__last_pipeline_waves": [[1], [2, 3]],
    })
    rendered = []
    monkeypatch.setattr(pipeline_lab, "_load_automation_preferences",
                        lambda *a, **k: {"max_workers": "corrupt"})
    monkeypatch.setattr(pipeline_lab, "_render_pipeline_automation_manifest_summary",
                        lambda path, **kwargs: rendered.append(path))
    render()
    assert fake.session_state["demo__pipeline_profile"] == "balanced"
    assert fake.session_state["demo__pipeline_max_workers"] == 3
    assert ("info", "Recovered previous run from disk.") in fake.messages
    assert "demo__run_state_hydrated_notice" not in fake.session_state
    assert rendered == [str(tmp_path / "run.json")]
    assert any("Last execution waves: 1 -> 2 + 3" in message for _, message in fake.messages)


@pytest.mark.parametrize("bulk", [False, True])
def test_delete_rejection_displays_reason_and_preserves_stages(lab_ui, monkeypatch, bulk):
    fake, render, entries = lab_ui
    name = "delete_all_pipeline_stages_command" if bulk else "delete_pipeline_stage_command"
    key = "demo_delete_all_confirm" if bulk else "demo_delete_confirm_0"
    confirm = "demo_confirm_delete_all" if bulk else "demo_confirm_delete_0"
    fake._buttons[key] = True
    fake.session_state[confirm] = True
    calls = []
    def rejected(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(ok=False, message="Stage contract changed; reload before deleting.")
    monkeypatch.setattr(pipeline_lab, name, rejected)
    render()
    assert len(calls) == 1
    assert ("warning", "Stage contract changed; reload before deleting.") in fake.messages
    assert calls[0]["persisted_stages"] == entries
    assert entries[0]["C"] == "print('stage')"
