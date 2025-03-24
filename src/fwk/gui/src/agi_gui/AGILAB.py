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

# -------------------- Additional Imports -------------------- #
import ast
import re
import json
import glob
from pathlib import Path, PurePosixPath, PureWindowsPath
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
    help_file = Path(st.session_state["env"].help_path) / "index.html"
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


def main():

    from agi_env.agi_env import AgiEnv
    env = AgiEnv("flight", with_lab=True, verbose=True)
    # Global resource path

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

    # --- Retrieve OpenAI API Key ---
    openai_api_key = env.OPENAI_API_KEY if env.OPENAI_API_KEY else args.openai_api_key
    if not openai_api_key:
        # Prompt only if no value exists in the environment or CLI.
        openai_api_key = input("Enter OpenAI API key: ").strip()
        if not openai_api_key:
            print("Error: Missing mandatory parameter: --openai-api-key")
            sys.exit(1)
    else:
        print("Found OpenAI API key; skipping prompt.")

    # --- Retrieve Cluster Credentials ---
    cluster_credentials = env.AGI_CREDENTIALS if env.AGI_CREDENTIALS else args.cluster_credentials
    if cluster_credentials is None:
        # Prompt only if no cluster credentials exist.
        cluster_enabled = input("Is cluster available? [N/y]: ").strip().lower() or "n"
        if cluster_enabled == "y":
            ssh_key_set = input("Is SSH key set? [N/y]: ").strip().lower() or "n"
            if ssh_key_set == "y":
                cluster_credentials = input("Enter user (SSH key is set): ").strip()
            else:
                cluster_credentials = input("Enter cluster credentials (user:password): ").strip()
        else:
            cluster_credentials = ""
    else:
        print("Found cluster credentials; skipping prompt.")


    # -------------------- Setup AgiEnv -------------------- #
    env.set_openai_api_key(openai_api_key)
    env.set_agi_credentials(cluster_credentials)

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
    # Set page configuration before any Streamlit commands.
    st.set_page_config(
        menu_items=get_about_content(),  # Adjust if necessary
        layout="wide"
    )
    add_custom_css()
    main()
