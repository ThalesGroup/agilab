# BSD 3-Clause License
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
"""Streamlit entry point for the AGILab interactive lab."""
from pathlib import Path
from datetime import datetime
import streamlit as st
import sys
import argparse


# ----------------- Fast-Loading Banner UI -----------------
def quick_logo(resources_path: Path):
    """Render a lightweight banner with the AGILab logo."""
    try:
        from agi_env.pagelib import get_base64_of_image
        img_data = get_base64_of_image(resources_path / "agilab_logo.png")
        img_src = f"data:image/png;base64,{img_data}"
        st.markdown(
            f"""<div style="background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 55%, #22d3ee 100%); padding: 24px; border-radius: 14px; box-shadow: 0 12px 24px rgba(15,23,42,0.25); max-width: 820px; margin: 28px auto;">
                    <div style="display: flex; align-items: center; justify-content: center; gap: 16px;">
                        <h1 style="margin: 0; padding: 0; color: #f8fafc; font-size: 2.8rem; letter-spacing: 0.05em; text-shadow: 0 6px 18px rgba(15,23,42,0.4);">Welcome to</h1>
                        <img src="{img_src}" alt="AGI Logo" style="width:170px; filter: drop-shadow(0 6px 18px rgba(15,23,42,0.45));">
                    </div>
                    <div style="text-align: center; margin-top: 12px;">
                        <strong style="color: #e0f2fe; font-size: 1.25rem; letter-spacing: 0.08em; text-transform: uppercase;">a step further toward AGI</strong>
                    </div>
                </div>""", unsafe_allow_html=True
        )
    except Exception as e:
        st.info(str(e))
        st.info("Welcome to AGILAB", icon="📦")


def display_landing_page(resources_path: Path):
    """Display the introductory copy describing AGILab's value proposition."""
    from agi_env.pagelib import get_base64_of_image
    # You can optionally show a small logo here if wanted.
    md_content = f"""
    <div class="uvp-highlight">
      <strong>Introduciton</strong>:
    <ul>
      AGILAB revolutionizing data Science experimentation with zero integration hassles. As a comprehensive framework built on pure Python and powered by Gen AI and ML, AGILAB scales effortlessly—from embedded systems to the cloud—empowering seamless collaboration on data insights and predictive modeling.
    </ul>
    </div>
    <div class="uvp-highlight">
      <strong>Founding Concept:</strong>
    <ul>
      AGILAB outlines a method for scaling into a project’s execution environment without the need for virtualization or containerization (such as Docker). The approach involves encapsulating an app's logic into two components: a worker (which is scalable and free from dependency constraints) and a manager (which is easily integrable due to minimal dependency requirements). This design enables seamless integration within a single app, contributing to the move toward Artificial General Intelligence (AGI).
      For infrastructure that required docker, there is an agilab docker script to generate a docker image in the docker directory under the project root.
    </ul>      
    </div>
      <strong>Key Features:</strong>
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
    """
    st.markdown(md_content, unsafe_allow_html=True)


def show_banner_and_intro(resources_path: Path):
    """Render the branding banner followed by the descriptive landing copy."""
    quick_logo(resources_path)
    display_landing_page(resources_path)


def page(env):
    """Render the main landing page controls and footer for the lab."""
    st.markdown(
        """
        <style>
        div[data-testid="stButton"] button {
            color: #4A90E2 !important;
            font-weight: 600;
            background: transparent !important;
            border: 1px solid #4A90E2 !important;
        }
        div[data-testid="stButton"] button:hover {
            background: #4A90E2 !important;
            color: #FFFFFF !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(4)
    help_file = Path(env.help_path) / "index.html"
    from agi_env.pagelib import open_docs
    if cols[0].button("Read Documentation", key="read_docs_btn", use_container_width=True):
        open_docs(env, help_file, "project-editor")

    current_year = datetime.now().year
    st.markdown(
        f"""
    <div class='footer' style="display: flex; justify-content: flex-end;">
                <span style="color:#64748b;">&copy; 2020-{current_year} Thales SIX GTS &middot; BSD 3-Clause Licensed.</span>
    </div>
    """,
        unsafe_allow_html=True,
    )
    if "TABLE_MAX_ROWS" not in st.session_state:
        st.session_state["TABLE_MAX_ROWS"] = env.TABLE_MAX_ROWS
    if "TABLE_SAMPLING" not in st.session_state:
        st.session_state["TABLE_SAMPLING"] = env.TABLE_SAMPLING


# ------------------------- Main Entrypoint -------------------------

def main():
    """Initialise the Streamlit app, bootstrap the environment and display the UI."""
    from agi_env.pagelib import get_about_content
    st.set_page_config(
        menu_items=get_about_content(),
        layout="wide"
    )
    resources_path = Path(__file__).parent / "resources"
    st.session_state.setdefault("first_run", True)

    # Always set background style
    st.markdown(
        """<style>
        body { background: #f6f8fa !important; }
        </style>""",
        unsafe_allow_html=True
    )

    # ---- Initialize if needed (on cold start, or if 'env' key lost) ----
    if st.session_state.get("first_run", True) or "env" not in st.session_state:
        with st.spinner("Initializing environment..."):
            from agi_env.pagelib import activate_mlflow
            from agi_env import AgiEnv
            parser = argparse.ArgumentParser(description="Run the AGI Streamlit App with optional parameters.")
            parser.add_argument("--cluster-ssh-credentials", type=str, help="Cluster credentials (username:password)",
                                default=None)
            parser.add_argument("--openai-api-key", type=str, help="OpenAI API key (mandatory)", default=None)
            parser.add_argument("--install-type", type=str, help="0:enduser(default)\n1:dev", default="0")
            parser.add_argument("--apps-dir", type=str, help="Where you store your apps (default is ./)",
                                default="apps")

            args, _ = parser.parse_known_args()

            if args.apps_dir is None:
                with open(Path("~/").expanduser() / ".local/share/agilab/.agilab-path", "r") as f:
                    agilab_path = f.read()
                    before, sep, after = agilab_path.rpartition(".venv")
                    args.apps_dir = Path(before) / "apps"

            if args.apps_dir is None:
                st.error("Error: Missing mandatory parameter: --apps-dir")
                sys.exit(1)

            st.session_state["apps_dir"] = args.apps_dir

            st.session_state["INSTALL_TYPE"] = args.install_type
            env = AgiEnv(install_type=int(args.install_type), verbose=1)
            env.init_done = True
            st.session_state['env'] = env

            if not st.session_state.get("server_started"):
                activate_mlflow(env)
                st.session_state["server_started"] = True

            openai_api_key = env.OPENAI_API_KEY if env.OPENAI_API_KEY else args.openai_api_key
            if not openai_api_key:
                st.error("Error: Missing mandatory parameter: --openai-api-key")
                sys.exit(1)

            cluster_credentials = env.CLUSTER_CREDENTIALS if env.CLUSTER_CREDENTIALS else args.cluster_ssh_credentials or ""
            AgiEnv.set_env_var("OPENAI_API_KEY", openai_api_key)
            AgiEnv.set_env_var("CLUSTER_CREDENTIALS", cluster_credentials)
            AgiEnv.set_env_var("INSTALL_TYPE", args.install_type)
            AgiEnv.set_env_var("APPS_DIR", args.apps_dir)

            st.session_state["first_run"] = False
            st.rerun()
        return  # Don't continue

    # ---- After init, always show banner+intro and then main UI ----
    env = st.session_state['env']
    show_banner_and_intro(resources_path)
    page(env)


# ----------------- Run App -----------------
if __name__ == "__main__":
    main()
