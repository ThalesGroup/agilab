# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS France SAS, may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from pathlib import Path
from datetime import datetime
import streamlit as st
import importlib
import base64
import sys
import os
import argparse

# -------------------- Import Statements -------------------- #
# (Include any other necessary imports from your original code)
from agi_gui.pagelib import env, get_about_content, render_logo, open_docs, RESOURCE_PATH, get_base64_of_image

# -------------------- Import Statements -------------------- #
import ast
from datetime import datetime
import re
import json
import glob
from pathlib import Path, PurePosixPath, PureWindowsPath
from functools import lru_cache
import pandas as pd
import toml
import os
import io
import subprocess
import streamlit as st
import random
import socket
from PIL import Image
import base64
import runpy
from typing import List, Union, Optional, Dict
import sys
import importlib

def add_custom_css():
    """
    Loads and injects external CSS into the Streamlit app.
    """
    css_path = RESOURCE_PATH / "first_page.css"
    css_content = load_file_content(css_path)
    if css_content:
        st.markdown(f"<style>{css_content}</style>", unsafe_allow_html=True)


def display_landing_page():
    """
    Loads and displays the landing page Markdown content.
    """

    img_data = get_base64_of_image(RESOURCE_PATH / "agi_logo.png")
    img_src = f"data:image/png;base64,{img_data}"
    md_content = f"""
    <div style="background-color: #333333; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); max-width: 800px; margin: 20px auto;">
      <div style="display: flex; align-items: center; justify-content: center;">
        <h1 style="margin: 0; padding: 0 10px 0 0;">
          Welcome to AGILAB
        </h1>
        <img src="{img_src}" alt="AGI Logo" style="width:100px;">
      </div>
      <div style="text-align: center;">
        <strong style="color: black;">a step further toward AGI</strong>
      </div>
    </div>

    <div class="uvp-highlight">
      <strong>Founding Concept:</strong> AGILAB outlines a method for scaling into a project’s execution environment without the need for virtualization or containerization (such as Docker). The approach involves encapsulating an app's logic into two components: a worker (which is scalable and free from dependency constraints) and a manager (which is easily integrable due to minimal dependency requirements). This design enables seamless integration within a single app, contributing to the move toward Artificial General Intelligence (AGI).
    </div>

    <div class="uvp-highlight">
      <strong>AGILAB</strong>: Revolutionizing Data Science Experimentation with Zero Integration Hassles. As a comprehensive framework built on 50KLOC of pure Python and powered by Gen AI and ML, AGILAB scales effortlessly—from embedded systems to the cloud—empowering seamless collaboration on data insights and predictive modeling.
    </div>

    <p><strong>Key Features:</strong></p>
    <ul>
      <li><strong>Strong AI Enabler</strong>: Algos Integrations.</li>
      <li><strong>Engineering AI Enabler</strong>: Feature Engineering.</li>
      <li><strong>Availability</strong>: Works online and in standalone mode.</li>
      <li><strong>Enhanced Deployment Productivity</strong>: Automates virtual environment deployment.</li>
      <li><strong>Enhanced Coding Productivity</strong>: Seamless integration with openai-api.</li>
      <li><strong>Enhanced Scalability</strong>: Distributes both data and algorithms on a cluster.</li>
      <li><strong>User-Friendly Interface for Data Science</strong>: Integration of Jupyter-ai and ML Flow.</li>
      <li><strong>Advanced Execution Tools</strong>: Enables Map Reduce and Direct Acyclic Graph Orchestration.</li>
    </ul>

    <p>
      With AGILAB, there’s no need for additional integration—our all-in-one framework is ready to deploy, enabling you to focus on innovation rather than setup.
    </p>

    <div class="uvp-highlight">
      <strong>Tips:</strong> To benefit from AGI cluster automation functionality, all you need is <strong>agi-core</strong> and <strong>agi-env</strong>. This means you can remove the lab and view directories. Historically, AGILAB was developed as a playground for agi-core.
    </div>
    """

    st.markdown(md_content, unsafe_allow_html=True)


# -------------------- Additional Functions (e.g., logo rendering) -------------------- #
def render_logo_with_columns():
    """
    Renders the agi logo centered on the main page using columns.
    """
    logo_path = (
            RESOURCE_PATH / "agi_logo.png"
    )  # Adjust the path if necessary
    logo = Image.open(logo_path)

    # Create three columns with ratios: 1:2:1
    left_col, middle_col, right_col = st.columns([1, 2, 1])

    with middle_col:
        st.write("")
        st.write("")
        st.image(logo, width=200)  # Adjust width as needed


def load_file_content(file_path: Path) -> str:
    """
    Reads the content of a file.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        st.error(f"Error loading {file_path}: {e}")
        return ""


# -------------------- Custom CSS Styling -------------------- #
def add_custom_css():
    """
    Add custom CSS styles to the Streamlit app.

    This function adds custom CSS styles to the Streamlit app to customize the appearance of the page.

    Args:
        None

    Returns:
        None

    Raises:
        None
    """
    custom_css = """
    <style>
    /* Set the background color for the entire page */
    .reportview-container {
        background-color: white; /* Light grey background for a clean look */
    }
    /* Set the background color for the sidebar */
    .sidebar .sidebar-content {
        background-color: white; /* White sidebar for contrast */
    }
    /* Style for header section */
    .header {
        background-color: #1E90FF; /* Primary Blue aligning with :one: emoji */
        padding: 40px 20px;
        text-align: left;
    }
    /* Style for main headers */
    .header h1 {
        color: white; /* White title */
        font-family: 'Helvetica', sans-serif;
        font-weight: bold;
        font-size: 48px;
        margin-bottom: 10px;
    }

    /* Style for footer */
    .footer {
        position: fixed;
        left: 0;
        bottom: 0;
        width: 100%;
        background-color: #1E90FF; /* Primary Blue */
        color: white;
        text-align: center;
        padding: 10px 0;
        font-family: 'Helvetica', sans-serif;
        font-size: 14px;
    }

    /* Hide Streamlit's default hamburger menu and footer */
    footer {visibility: hidden;}

    /* New CSS class for UVP highlighting */
    .uvp-highlight {
        background-color: #f0f8ff; /* Light Blue Background */
        color: #333333;            /* Dark Text for Contrast */
        padding: 20px;             /* Inner Padding */
        border-left: 5px solid #1E90FF; /* Blue Border on the Left */
        border-radius: 5px;        /* Rounded Corners */
        margin-top: 20px;          /* Top Margin */
        margin-bottom: 20px;       /* Bottom Margin */
        font-size: 18px;           /* Font Size */
        line-height: 1.6;          /* Line Height for Readability */
    }

    /* Optional: Adjust list styles within UVP */
    .uvp-highlight ul {
        list-style-type: disc;
        margin-left: 20px;
    }

    /* Optional: Enhance the visibility of strong tags within UVP */
    .uvp-highlight strong {
        color: #1E90FF; /* Blue Color for Emphasis */
    }
    </style>
    """
    st.markdown(custom_css, unsafe_allow_html=True)


# -------------------- Exception Class -------------------- #
class JumpToMain(Exception):
    """
    Custom exception to jump back to the main execution flow.
    """

    pass


# -------------------- Initialize Page Configuration -------------------- #

# Load your logo from a file
agi_logo = Image.open(RESOURCE_PATH / "agi_logo.png")

# Ensure this is the very first Streamlit command after imports and function definitions
st.set_page_config(
    menu_items=get_about_content(),  # Adjust if necessary
    layout="wide"
)

# -------------------- Inject Custom CSS -------------------- #
add_custom_css()


# -------------------- Render Logos -------------------- #
# Render the logo in the sidebar
# render_logo()


# -------------------- Streamlit Page Rendering -------------------- #
def page():
    # Override the default .block-container styling
    """
    Display a landing page for AGILAB.
    """
    # Display landing page content from external Markdown file
    display_landing_page()

    cols = st.columns(2)
    help_file = env.help_path / "index.html"
    if cols[0].button("Read Documentation", type="tertiary", use_container_width=True):
        open_docs(env, help_file, "project-editor")

    # Add a button to proceed
    if cols[1].button("Get Started", type="tertiary", use_container_width=True):
        st.write("Redirecting to the main application...")
        # Set the current page to '▶️ EDIT' and rerun the app
        st.session_state.current_page = "▶️ EDIT"
        st.query_params["current_page"] = "▶️ EDIT"
        st.rerun()

    # Footer with custom styling
    current_year = datetime.now().year
    st.markdown(
        f"""
    <div class='footer'>
        &copy; 2020-{current_year} Thales SIX GTS. All rights reserved.
    </div>
    """,
        unsafe_allow_html=True,
    )


# -------------------- Main Application Entry -------------------- #
import argparse
import sys
import os
from pathlib import Path
from datetime import datetime
import streamlit as st
import importlib

# -------------------- Import Statements -------------------- #
from agi_gui.pagelib import (
    env,
    get_about_content,
    render_logo,
    open_docs,
    RESOURCE_PATH,
    get_base64_of_image,
)

# Additional imports
import ast
import re
import json
import glob
from pathlib import PurePosixPath, PureWindowsPath
from functools import lru_cache
import pandas as pd
import toml
import io
import subprocess
import random
import socket
from PIL import Image
import base64
import runpy
from typing import List, Union, Optional, Dict

# -------------------- Helper Functions -------------------- #

def add_custom_css():
    """
    Loads and injects external CSS into the Streamlit app.
    """
    css_path = RESOURCE_PATH / "first_page.css"
    css_content = load_file_content(css_path)
    if css_content:
        st.markdown(f"<style>{css_content}</style>", unsafe_allow_html=True)

def load_file_content(file_path: Path) -> str:
    """
    Reads the content of a file.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        st.error(f"Error loading {file_path}: {e}")
        return ""

def display_landing_page():
    """
    Loads and displays the landing page Markdown content.
    """
    img_data = get_base64_of_image(RESOURCE_PATH / "agi_logo.png")
    img_src = f"data:image/png;base64,{img_data}"
    md_content = f"""
    <div style="background-color: #333333; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); max-width: 800px; margin: 20px auto;">
      <div style="display: flex; align-items: center; justify-content: center;">
        <h1 style="margin: 0; padding: 0 10px 0 0;">Welcome to AGILAB</h1>
        <img src="{img_src}" alt="AGI Logo" style="width:100px;">
      </div>
      <div style="text-align: center;">
        <strong style="color: black;">a step further toward AGI</strong>
      </div>
    </div>
    <div class="uvp-highlight">
      <strong>Founding Concept:</strong> AGILAB outlines a method for scaling into a project’s execution environment without the need for virtualization or containerization (such as Docker). The approach involves encapsulating an app's logic into two components: a worker (which is scalable and free from dependency constraints) and a manager (which is easily integrable due to minimal dependency requirements). This design enables seamless integration within a single app, contributing to the move toward Artificial General Intelligence (AGI).
    </div>
    <div class="uvp-highlight">
      <strong>AGILAB</strong>: Revolutionizing Data Science Experimentation with Zero Integration Hassles. As a comprehensive framework built on 50KLOC of pure Python and powered by Gen AI and ML, AGILAB scales effortlessly—from embedded systems to the cloud—empowering seamless collaboration on data insights and predictive modeling.
    </div>
    <p><strong>Key Features:</strong></p>
    <ul>
      <li><strong>Strong AI Enabler</strong>: Algos Integrations.</li>
      <li><strong>Engineering AI Enabler</strong>: Feature Engineering.</li>
      <li><strong>Availability</strong>: Works online and in standalone mode.</li>
      <li><strong>Enhanced Deployment Productivity</strong>: Automates virtual environment deployment.</li>
      <li><strong>Enhanced Coding Productivity</strong>: Seamless integration with openai-api.</li>
      <li><strong>Enhanced Scalability</strong>: Distributes both data and algorithms on a cluster.</li>
      <li><strong>User-Friendly Interface for Data Science</strong>: Integration of Jupyter-ai and ML Flow.</li>
      <li><strong>Advanced Execution Tools</strong>: Enables Map Reduce and Direct Acyclic Graph Orchestration.</li>
    </ul>
    <p>
      With AGILAB, there’s no need for additional integration—our all-in-one framework is ready to deploy, enabling you to focus on innovation rather than setup.
    </p>
    <div class="uvp-highlight">
      <strong>Tips:</strong> To benefit from AGI cluster automation functionality, all you need is <strong>agi-core</strong> and <strong>agi-env</strong>. This means you can remove the lab and view directories. Historically, AGILAB was developed as a playground for agi-core.
    </div>
    """
    st.markdown(md_content, unsafe_allow_html=True)

def page():
    """
    Display the landing page for AGILAB.
    """
    display_landing_page()
    cols = st.columns(2)
    help_file = st.session_state["env"].help_path / "index.html"
    if cols[0].button("Read Documentation", type="tertiary", use_container_width=True):
        open_docs(st.session_state["env"], help_file, "project-editor")
    if cols[1].button("Get Started", type="tertiary", use_container_width=True):
        st.write("Redirecting to the main application...")
        st.session_state.current_page = "▶️ EDIT"
        st.rerun()
    current_year = datetime.now().year
    st.markdown(
        f"""
    <div class='footer'>
        &copy; 2020-{current_year} Thales SIX GTS. All rights reserved.
    </div>
    """,
        unsafe_allow_html=True,
    )

def read_env_key(key: str) -> str:
    """
    Look for the given key in os.environ, then in ~/.agilab/.env.
    Return the value if found (and non-empty), otherwise return an empty string.
    """
    # 1. Check os.environ
    value = os.environ.get(key, "").strip()
    if value:
        return value

    # 2. Check ~/.agilab/.env file if it exists
    env_file = Path.home() / ".agilab" / ".env"
    if env_file.exists():
        with env_file.open("r") as f:
            for line in f:
                if '=' in line:
                    k, v = line.strip().split('=', 1)
                    if k == key and v.strip():
                        return v.strip()
    return ""

# -------------------- Main Application Entry -------------------- #
def main():
    """
    Main function to run the application.
    """
    # --- Command-Line Argument Parsing ---
    parser = argparse.ArgumentParser(
        description="Run the AGI Streamlit App with optional parameters."
    )
    parser.add_argument(
        "--cluster-credentials",
        type=str,
        help="Cluster credentials (username:password)",
        default=None
    )
    parser.add_argument(
        "--openai-api-key",
        type=str,
        help="OpenAI API key (mandatory)",
        default=None
    )
    args, unknown = parser.parse_known_args()

    # Try to get the values from os.environ or the .env file first.
    openai_api_key = read_env_key("OPENAI_API_KEY")
    if not openai_api_key:
        # If not found in environment or .env, override with CLI argument if provided.
        openai_api_key = args.openai_api_key
    if not openai_api_key:
        openai_api_key = input("Enter OpenAI API key: ").strip()
        if not openai_api_key:
            print("Error: Missing mandatory parameter: --openai-api-key")
            sys.exit(1)

    cluster_credentials = read_env_key("CLUSTER_CREDENTIALS")
    if not cluster_credentials:
        cluster_credentials = args.cluster_credentials
    if not cluster_credentials:
        # Prompt for cluster info only if not found
        cluster_enabled = input("Is cluster available? [N/y]: ").strip().lower() or "n"
        if cluster_enabled == "y":
            ssh_key_set = input("Is SSH key set? [N/y]: ").strip().lower() or "n"
            if ssh_key_set == "y":
                cluster_credentials = input("Enter user (SSH key is set): ").strip()
            else:
                cluster_credentials = input("Enter cluster credentials (user:password): ").strip()
        else:
            cluster_credentials = ""

    # Store the final values in the environment
    os.environ["OPENAI_API_KEY"] = openai_api_key
    os.environ["CLUSTER_CREDENTIALS"] = cluster_credentials

    # Update or create the .agilab/.env file if the keys are not already present
    env_file = Path.home() / ".agilab" / ".env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    current = {}
    if env_file.exists():
        with env_file.open("r") as f:
            for line in f:
                if '=' in line:
                    k, v = line.strip().split('=', 1)
                    current[k] = v
    with env_file.open("a") as f:
        if "OPENAI_API_KEY" not in current or not current["OPENAI_API_KEY"]:
            f.write(f"OPENAI_API_KEY={openai_api_key}\n")
        if "CLUSTER_CREDENTIALS" not in current or not current["CLUSTER_CREDENTIALS"]:
            f.write(f"CLUSTER_CREDENTIALS={cluster_credentials}\n")

    # Adjust sys.path to include agi_env if needed.
    path_agi_env = Path("fwk/env/src").resolve()
    path_agi = str(path_agi_env)
    if path_agi not in sys.path:
        sys.path.insert(0, path_agi)
    from agi_env.agi_env import AgiEnv

    # -------------------- Global Configurations -------------------- #
    treshold = 1
    snippet_run_error = "fail to run your python snippet"
    env_obj = AgiEnv("flight", with_lab=True, verbose=True)
    st.session_state["env"] = env_obj
    default_steps_file = "steps.toml"
    default_df = "export.csv"
    st.session_state["rapids_default"] = True


    # -------------------- Navigation and Page Rendering -------------------- #
    try:
        if "current_page" not in st.session_state:
            st.session_state.current_page = "AGILAB"

        if st.session_state.current_page == "AGILAB":
            st.session_state.current_page = None
            page()
        elif st.session_state.current_page == "▶️ EDIT":
            st.session_state.current_page = None
            page_module = importlib.import_module("pages.▶️ EDIT")
            page_module.main()
        else:
            page()
    except Exception as e:
        st.error(f"An error occurred: {e}")
        import traceback
        st.error(traceback.format_exc())

# -------------------- Run the App -------------------- #
if __name__ == "__main__":
    main()