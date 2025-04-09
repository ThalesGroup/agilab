# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the
# following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS France SAS, may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
# INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY,
# OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import streamlit as st

# ===========================
# Imports
# ===========================
from pathlib import Path
import sys
import importlib
# Use modern TOML libraries instead of toml
import tomli         # For reading TOML files
import tomli_w       # For writing TOML files
from agi_gui.pagelib import list_views, get_about_content, render_logo, select_project

from agi_env import AgiEnv

# Set page configuration - Must be the first Streamlit command
st.set_page_config(
    layout="wide",
    menu_items=get_about_content()
)

def main():
    # Use query parameters to handle navigation
    """
    Main function to handle the navigation between different pages of the application.

    This function retrieves the current page from the query parameters and stores it in the session state.
    Based on the current page, it sets the page title accordingly and renders the appropriate content.
    """
    global env
    env = st.session_state['env']

    current_page = st.query_params.get("current_page", "main")
    st.session_state["current_page"] = current_page

    # Determine the page title based on the current view
    if st.session_state["current_page"] == "main":
        page_title = "Select Views for Your Project"
    else:
        # Extract the view name from the path
        view_path = Path(st.session_state["current_page"])
        page_title = view_path.stem

    # Use Streamlit's title or header for dynamic titles
    render_logo(page_title, env)

    if not st.session_state.get("server_started"):
        activate_mlflow(env)
        st.session_state["server_started"] = True

    if st.session_state["current_page"] == "main":
        render_main_page()
    else:
        render_view_page(Path(st.session_state["current_page"]))


def render_main_page():
    # Sidebar setup
    # Load projects
    """
    Render the main page of the application.

    This function retrieves the list of projects, sets the current project, loads the app settings, allows the user to select views, and updates the configuration file accordingly.
    """
    global env
    projects = env.projects
    st.session_state["projects"] = projects

    # Determine current project
    current_project = env.app
    if current_project not in projects:
        current_project = projects[0] if projects else None
        st.session_state["project"] = current_project

    # Sidebar project selection
    env = select_project(projects, current_project)

    project = env.app
    # Define paths
    app_settings = Path(env.apps_dir) / project / "src" / "app_settings.toml"
    all_views = [Path(view) for view in list_views(env.AGILAB_VIEWS_ABS)]

    if not all_views:
        st.write("No views found")
        return

    # Load configuration using tomli (read in binary mode)
    try:
        with open(app_settings, "rb") as f:
            config = tomli.load(f)
    except Exception as e:
        st.error(f"Error loading configuration: {e}")
        return

    # Ensure 'views' key exists in config
    if "views" not in config:
        config["views"] = {}

    # Retrieve selected views
    project_views = config.get("views", {}).get("view_module", [])

    # Use multiselect for selecting views
    view_names = [view.stem for view in all_views]
    selected_views = st.multiselect(
        "Select Views", view_names, default=project_views
    )

    # Update app settings with selected views
    config["views"]["view_module"] = selected_views

    try:
        with open(app_settings, "wb") as file:
            tomli_w.dump(config, file)
    except Exception as e:
        st.error(f"Error updating configuration: {e}")

    # Display selected views as buttons
    if selected_views:
        for view_name in selected_views:
            view_path = next(
                (view for view in all_views if view.stem == view_name), None
            )
            if view_path:
                if st.button(view_name):
                    # Update the query parameter 'current_page' to navigate to the selected view
                    st.session_state["current_page"] = str(view_path.resolve())
                    st.query_params['current_page'] = str(view_path.resolve())
                    st.rerun()
            else:
                st.error(f"View '{view_name}' not found.")
    else:
        st.write("No views selected.")


def render_view_page(view_path):
    # Back button at the top
    """
    Render a view page based on the view path provided.

    :param view_path: The path to the view page.
    :type view_path: Path

    :returns: None

    :raises: None
    """
    if st.button("Back to Views"):
        st.session_state["current_page"] = "main"
        st.query_params["current_page"] = "main"
        st.rerun()

    # Validate the view path
    if not view_path.exists():
        st.error("View not found!")
        return

    # Add the directory containing the file to the system path
    view_dir = str(view_path.parent)
    if view_dir not in sys.path:
        sys.path.insert(0, view_dir)

    try:
        # Dynamically import and render the view
        page_module = importlib.import_module(view_path.stem)
        page_module.main()
    except Exception as e:
        st.error(f"Error loading view: {e}")
    finally:
        if view_dir in sys.path:
            sys.path.remove(view_dir)


if __name__ == "__main__":
    main()