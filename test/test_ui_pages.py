from __future__ import annotations

import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from streamlit.testing.v1 import AppTest

from agi_env import AgiEnv

APP_ARGS_FORM = "src/agilab/apps/builtin/flight_project/src/app_args_form.py"

@pytest.fixture
def mock_ui_env(tmp_path):
    # Set up temporary directories for apps and config
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    
    # Create a dummy project structure
    project_dir = apps_dir / "flight_project"
    project_dir.mkdir()
    
    # Create src dir and app_settings.toml
    src_dir = project_dir / "src"
    src_dir.mkdir()
    settings_file = src_dir / "app_settings.toml"
    settings_file.write_text("[flight]\n") # Just some dummy TOML
    
    # Needs to be able to import flight
    (src_dir / "flight.py").write_text("""
from pydantic import BaseModel
from datetime import date
class FlightArgs(BaseModel):
    data_source: str = "file"
    data_in: str = ""
    data_out: str = ""
    files: str = "*"
    nfile: int = 1
    nskip: int = 0
    nread: int = 0
    sampling_rate: float = 1.0
    datemin: date = date(2020, 1, 1)
    datemax: date = date(2021, 1, 1)
    output_format: str = "parquet"
    reset_target: bool = False

    
    def to_toml_payload(self):
        return self.model_dump(mode="json")
        
def apply_source_defaults(args):
    return args
    
def dump_args_to_toml(args, path):
    pass
    
def load_args_from_toml(path):
        return FlightArgs()
""")
    
    # Create apps-pages directory structure (not strictly needed since AgiEnv falls back to builtin apps)
    pages_dir = project_dir / "apps-pages"
    pages_dir.mkdir(parents=True, exist_ok=True)


    # Mock CLI argv for AGILAB main page
    test_argv = ["AGILAB.py", "--apps-dir", str(apps_dir), "--active-app", "flight_project"]
    
    # Patch sys.argv and env variables
    with patch("sys.argv", test_argv):
        with patch.dict(os.environ, {
            "AGILAB_APP": "flight_project",
            "AGI_SHARE_DIR": str(tmp_path),
            "AGILAB_PAGES_ABS": str(pages_dir),
            "OPENAI_API_KEY": "dummy",
            "IS_SOURCE_ENV": "1",
        }):
            yield {"apps_dir": apps_dir, "project_dir": project_dir, "pages_dir": pages_dir}


def test_agilab_main_page_env_editor(mock_ui_env):
    """Test the main AGILAB page and interacting with the .env editor form."""
    at = AppTest.from_file("src/agilab/AGILAB.py")
    
    # Run the app to initialize
    at.run()
    assert not at.exception
    
    # Find the environment editor form
    # We expand the Environment Variables expander (Streamlit AppTest exposes them linearly, but we can look for the form)
    # Actually, we can just interact with the text inputs directly by key
    
    # Wait, the form might not be rendered unless the expander is open. By default it's expanded=False
    # However AppTest runs the whole script. In AppTest, expander contents are accessible
    assert "env_editor_new_key" in [ti.key for ti in at.text_input]
    assert "env_editor_new_value" in [ti.key for ti in at.text_input]
    
    # Set values in the text inputs
    at.text_input(key="env_editor_new_key").set_value("TEST_UI_VAR")
    at.text_input(key="env_editor_new_value").set_value("helloworld")
    
    # Submit the form
    # We find the button with label "Save .env"
    save_btn = None
    for btn in at.button:
        if btn.label == "Save .env":
            save_btn = btn
            break
            
    assert save_btn is not None
    save_btn.click().run()
    
    assert not at.exception
    # Check if the success message appeared
    # In AppTest, st.success is mapped to at.success
    success_msgs = [s.value for s in at.success]
    assert any("Environment variables updated" in msg for msg in success_msgs)


def test_execute_page_cluster_settings(mock_ui_env):
    """Test the EXECUTE page cluster settings interactivity."""
    
    # For execute page we need an initialized env in session_state
    at = AppTest.from_file("src/agilab/pages/2_▶️ ORCHESTRATE.py", default_timeout=10)
    
    # Pre-inject environment into session state
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
    at.session_state["env"] = env
    
    at.run()
    assert not at.exception
    
    enabled_toggle_key = f"cluster_enabled__flight_project"
    
    # Enable cluster
    at.toggle(key=enabled_toggle_key).set_value(True).run()
    
    scheduler_key = f"cluster_scheduler__flight_project"
    # Find scheduler text input
    at.text_input(key=scheduler_key).set_value("127.0.0.1:8786")
    
    # Toggle some cluster settings
    at.checkbox(key="cluster_pool").set_value(True)
    
    at.run()
    
    assert not at.exception
    assert at.session_state["app_settings"]["cluster"]["cluster_enabled"] is True
    assert at.session_state["app_settings"]["cluster"]["pool"] is True
    assert at.session_state[scheduler_key] == "127.0.0.1:8786"


def test_flight_project_app_args_form_render(mock_ui_env):
    """Test that the flight_project UI data source form renders without errors."""
    project_src = str(mock_ui_env["project_dir"] / "src")
    sys.path.insert(0, project_src)
    try:
        at = AppTest.from_file(APP_ARGS_FORM)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)

        at.session_state["env"] = env
        at.run()

        assert not at.exception
    finally:
        if project_src in sys.path:
            sys.path.remove(project_src)

def test_flight_project_app_args_form(mock_ui_env):
    """Test the flight_project UI data source form interactions."""
    project_src = str(mock_ui_env["project_dir"] / "src")
    sys.path.insert(0, project_src)
    try:
        at = AppTest.from_file(APP_ARGS_FORM)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)

        # To avoid the 'not initialised' error
        at.session_state["env"] = env

        at.run()
        assert not at.exception

        # The default data source is 'file', we switch it to 'hawk'
        at.selectbox(key="flight_project:app_args_form:data_source").set_value("hawk").run()

        # Check if the text input labels changed
        # Text input for "Hawk cluster URI" should exist (it replaces "Data directory")
        # Actually, AppTest exposes text inputs but their labels might vary. Let's find it by key
        data_in_input = at.text_input(key="flight_project:app_args_form:data_in")
        assert data_in_input.label == "Hawk cluster URI"

        files_input = at.text_input(key="flight_project:app_args_form:files")
        assert files_input.label == "Pipeline name"

        # Let's set some values
        data_in_input.set_value("http://localhost:9200")
        files_input.set_value("test_pipeline")
        at.number_input(key="flight_project:app_args_form:nfile").set_value(5)

        at.run()

        if at.error:
            print("ERRORS:", [e.value for e in at.error])

        print("SUCCESS MSGS:", [m.value for m in at.success])
        print("INFO MSGS:", [m.value for m in at.info])
        print("WARNING MSGS:", [m.value for m in at.warning])
        print("ERROR MSGS:", [m.value for m in at.error])

        assert not at.exception

        # The current parameters are collected in the session state payload or validated structure
        # The UI saves to `settings_path` and updates `app_settings`
        assert "app_settings" in at.session_state, "app_settings was not saved!"
        assert at.session_state["app_settings"]["args"]["data_source"] == "hawk"
        assert at.session_state["app_settings"]["args"]["data_in"] == "http://localhost:9200"
        assert at.session_state["app_settings"]["args"]["files"] == "test_pipeline"
        assert at.session_state["app_settings"]["args"]["nfile"] == 5

        # Look for the success message containing "Saved to"
        success_msgs = [s.value for s in at.success]
        assert any("Saved to" in msg for msg in success_msgs)
    finally:
        if project_src in sys.path:
            sys.path.remove(project_src)

def test_explore_page_multiselect(mock_ui_env):
    """Test the EXPLORE page multiselect and button rendering."""
    at = AppTest.from_file("src/agilab/pages/4_▶️ ANALYSIS.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
    
    at.session_state["env"] = env
    at.run()
    assert not at.exception
    
    # Check that 'dummy_view' is an option in the multiselect
    selection_key = f"view_selection__flight_project"
    ms = at.multiselect(key=selection_key)
    
    assert "view_maps" in ms.options
    
    # Select it
    ms.select("view_maps").run()
    assert not at.exception
    
    # Ensure that the button was created for it
    btns = [b.label for b in at.button]
    assert "view_maps" in btns

def test_experiment_page_load(mock_ui_env):
    """Test that the EXPERIMENT page loads without exceptions."""
    at = AppTest.from_file("src/agilab/pages/3_▶️ PIPELINE.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
    
    # We must ensure there is a lab_steps file to not throw exceptions, or handling it safely
    # In mock env we just pass env
    at.session_state["env"] = env
    # Mock some expected session_states for the page
    at.session_state["flight_project"] = [0, "", "", "", "", ""]
    at.session_state["flight_project__venv_map"] = {}
    
    at.run()
    assert not at.exception

def test_edit_page_load(mock_ui_env):
    """Test that the EDIT page loads without exceptions."""
    at = AppTest.from_file("src/agilab/pages/1_▶️ SETUP.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
    
    at.session_state["env"] = env
    
    at.run()
    assert not at.exception


def test_execute_page_cython_toggle(mock_ui_env):
    """Test toggling the Cython checkbox on the EXECUTE page."""
    at = AppTest.from_file("src/agilab/pages/2_▶️ ORCHESTRATE.py", default_timeout=10)
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
    at.session_state["env"] = env

    at.run()
    assert not at.exception

    # Enable cython
    at.checkbox(key="cluster_cython").set_value(True).run()
    assert not at.exception
    assert at.session_state["app_settings"]["cluster"]["cython"] is True

    # Disable cython
    at.checkbox(key="cluster_cython").set_value(False).run()
    assert not at.exception
    assert at.session_state["app_settings"]["cluster"]["cython"] is False


def test_execute_page_workers_data_path(mock_ui_env):
    """Test setting the workers data path when cluster is enabled."""
    at = AppTest.from_file("src/agilab/pages/2_▶️ ORCHESTRATE.py", default_timeout=10)
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
    at.session_state["env"] = env

    at.run()
    assert not at.exception

    # Enable cluster first
    enabled_key = f"cluster_enabled__flight_project"
    at.toggle(key=enabled_key).set_value(True).run()
    assert not at.exception

    # Set workers data path
    wdp_key = f"cluster_workers_data_path__flight_project"
    at.text_input(key=wdp_key).set_value("/data/shared").run()
    assert not at.exception
    assert at.session_state["app_settings"]["cluster"]["workers_data_path"] == "/data/shared"


def test_explore_page_multiple_views_selected(mock_ui_env):
    """Test selecting multiple views and verifying a button is rendered for each."""
    at = AppTest.from_file("src/agilab/pages/4_▶️ ANALYSIS.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
    at.session_state["env"] = env
    at.run()
    assert not at.exception

    selection_key = "view_selection__flight_project"
    ms = at.multiselect(key=selection_key)

    # Select two views
    ms.select("view_maps").select("view_barycentric").run()
    assert not at.exception

    btns = [b.label for b in at.button]
    assert "view_maps" in btns
    assert "view_barycentric" in btns


def test_explore_page_deselect_view(mock_ui_env):
    """Test selecting then deselecting a view removes its button."""
    at = AppTest.from_file("src/agilab/pages/4_▶️ ANALYSIS.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
    at.session_state["env"] = env
    at.run()
    assert not at.exception

    selection_key = "view_selection__flight_project"
    ms = at.multiselect(key=selection_key)

    # Select two views
    ms.select("view_maps").select("view_barycentric").run()
    assert not at.exception

    # Now deselect view_maps
    ms.unselect("view_maps").run()
    assert not at.exception

    btns = [b.label for b in at.button]
    assert "view_maps" not in btns
    assert "view_barycentric" in btns


def test_app_args_form_no_changes(mock_ui_env):
    """Test that submitting the form with no changes shows 'No changes to save.'."""
    project_src = str(mock_ui_env["project_dir"] / "src")
    sys.path.insert(0, project_src)
    try:
        at = AppTest.from_file(APP_ARGS_FORM)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
        at.session_state["env"] = env

        at.run()
        assert not at.exception

        # Run again without changing anything
        at.run()
        assert not at.exception

        info_msgs = [m.value for m in at.info]
        assert any("No changes" in msg for msg in info_msgs)
    finally:
        if project_src in sys.path:
            sys.path.remove(project_src)


def test_app_args_form_switch_back_to_file(mock_ui_env):
    """Test switching data source from file -> hawk -> file and verifying labels revert."""
    project_src = str(mock_ui_env["project_dir"] / "src")
    sys.path.insert(0, project_src)
    try:
        at = AppTest.from_file(APP_ARGS_FORM)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
        at.session_state["env"] = env
        at.run()
        assert not at.exception

        # Switch to hawk
        at.selectbox(key="flight_project:app_args_form:data_source").set_value("hawk").run()
        assert not at.exception
        assert at.text_input(key="flight_project:app_args_form:data_in").label == "Hawk cluster URI"

        # Switch back to file
        at.selectbox(key="flight_project:app_args_form:data_source").set_value("file").run()
        assert not at.exception
        assert at.text_input(key="flight_project:app_args_form:data_in").label == "Data directory"
        assert at.text_input(key="flight_project:app_args_form:files").label == "Files filter"
    finally:
        if project_src in sys.path:
            sys.path.remove(project_src)


def test_agilab_main_page_theme_injection(mock_ui_env):
    """Test that the main page injects theme CSS on load."""
    at = AppTest.from_file("src/agilab/AGILAB.py")
    at.run()
    assert not at.exception

    # The page injects CSS via st.markdown with unsafe_allow_html=True
    # In AppTest, these show up as at.markdown elements
    md_values = [m.value for m in at.markdown]
    assert any("<style>" in val or "style" in val.lower() for val in md_values if isinstance(val, str)), \
        "Expected theme CSS to be injected via st.markdown"


def test_experiment_page_missing_openai_key(mock_ui_env):
    """Test that EXPERIMENT page handles a missing OpenAI API key gracefully."""
    at = AppTest.from_file("src/agilab/pages/3_▶️ PIPELINE.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)

    at.session_state["env"] = env
    at.session_state["flight_project"] = [0, "", "", "", "", ""]
    at.session_state["flight_project__venv_map"] = {}

    # Remove the API key from the environment
    with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
        at.run()

    # The page should still load without crashing
    assert not at.exception


def test_edit_page_project_selectbox(mock_ui_env):
    """Test that the EDIT page has a project selectbox with available projects."""
    at = AppTest.from_file("src/agilab/pages/1_▶️ SETUP.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    env.projects = ["flight_project"]
    env.get_projects = MagicMock(return_value=["flight_project"])
    at.session_state["env"] = env
    at.session_state["sidebar_selection"] = "Edit"

    at.run()
    assert not at.exception

    main_selectboxes = list(at.selectbox)
    sidebar_selectboxes = list(at.sidebar.selectbox)
    selectbox_keys = [sb.key for sb in main_selectboxes] + [sb.key for sb in sidebar_selectboxes]
    assert selectbox_keys, (
        "EDIT page should have at least one selectbox "
        f"(main={len(main_selectboxes)}, sidebar={len(sidebar_selectboxes)}, "
        f"errors={[e.value for e in at.error]})"
    )
    assert "project_selectbox" in selectbox_keys
