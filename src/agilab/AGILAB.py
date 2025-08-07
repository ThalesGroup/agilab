# BSD 3-Clause License
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
from pathlib import Path
from datetime import datetime
import streamlit as st
import sys
import argparse

# ----------------- Fast-Loading Minimal UI -----------------
def quick_logo(resources_path: Path):
    try:
        from agilab.pagelib import get_base64_of_image
        img_data = get_base64_of_image(resources_path / "agilab_logo.png")
        img_src = f"data:image/png;base64,{img_data}"
        st.markdown(
            f"""<div style='text-align:center; margin-top:40px;'>
                   <img src="{img_src}" width="120" alt="AGILAB logo"/>
                   <h1 style="color:#333;margin-top:16px">Welcome to AGILAB</h1>
                   <p>Loading environment, please wait...</p>
               </div>""", unsafe_allow_html=True
        )
    except Exception as e:
        st.info(str(e))
        st.info("Welcome to AGILAB", icon="📦")

def fast_landing(resources_path: Path):
    st.markdown(
        """<style>
        body { background: #f6f8fa !important; }
        </style>""",
        unsafe_allow_html=True)
    quick_logo(resources_path)

# ----------- Heavy Initialization & Full Landing Page -----------

def display_landing_page(resources_path: Path):
    from agilab.pagelib import get_base64_of_image
    img_data = get_base64_of_image(resources_path / "agilab_logo.png")
    img_src = f"data:image/png;base64,{img_data}"
    md_content = f"""
    <div style="background-color: #333333; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); max-width: 800px; margin: 20px auto;">
      <div style="display: flex; align-items: center; justify-content: center;">
        <h1 style="margin: 0; padding: 0 10px 0 0;">Welcome to</h1>
        <img src="{img_src}" alt="AGI Logo" style="width:160px; margin-bottom: 20px;">
      </div>
      <div style="text-align: center;">
        <strong style="color: black;">a step further toward AGI</strong>
      </div>
    </div>
    <div class="uvp-highlight">
      <strong>AGILAB</strong>:
    <ul>
      Revolutionizing Data Science Experimentation with Zero Integration Hassles. As a comprehensive framework built on 50KLOC of pure Python and powered by Gen AI and ML, AGILAB scales effortlessly—from embedded systems to the cloud—empowering seamless collaboration on data insights and predictive modeling.
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
    <div class="uvp-highlight">
      <strong>Tips:</strong> To benefit from AGI cluster automation functionality, all you need is <strong>agi-core</strong> and <strong>agi-env</strong>. This means you can remove the lab and view directories. Historically, AGILAB was developed as a playground for agi-core.
    </div>
    """
    st.markdown(md_content, unsafe_allow_html=True)

def page(env):
    display_landing_page(env.resource_path)
    cols = st.columns(2)
    help_file = Path(env.help_path) / "index.html"
    from agilab.pagelib import open_docs
    if cols[0].button("Read Documentation", type="tertiary", use_container_width=True):
        open_docs(env, help_file, "project-editor")
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
    if "GUI_NROW" not in st.session_state:
        st.session_state["GUI_NROW"] = env.GUI_NROW
    if "GUI_SAMPLING" not in st.session_state:
        st.session_state["GUI_SAMPLING"] = env.GUI_SAMPLING

# ------------------------- Main Entrypoint -------------------------

def main():
    # ----- Show fast first display -----
    resources_path = Path(__file__).parent / "resources"
    fast_landing(resources_path)
    st.session_state.setdefault("first_run", True)

    # --------- Heavy init under spinner ---------
    with st.spinner("Initializing environment..."):
        if st.session_state["first_run"]:
            from agilab.pagelib import activate_mlflow, get_about_content
            from agi_env import AgiEnv

            # --- Argument parsing (fast, but let's keep outside render loop) ---
            parser = argparse.ArgumentParser(description="Run the AGI Streamlit App with optional parameters.")
            parser.add_argument("--cluster-ssh-credentials", type=str, help="Cluster credentials (username:password)", default=None)
            parser.add_argument("--openai-api-key", type=str, help="OpenAI API key (mandatory)", default=None)
            parser.add_argument("--apps-dir", type=str, help="Where you store your apps (default is ./)", default="apps")
            parser.add_argument("--install-type", type=str, help="0:enduser(default)\n1:dev", default="0")
            args, _ = parser.parse_known_args()

            st.session_state["apps_dir"] = args.apps_dir
            st.session_state["INSTALL_TYPE"] = args.install_type
            env = AgiEnv(apps_dir=Path(args.apps_dir), install_type=int(args.install_type), verbose=1)
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

            # --------- Page config (just once) ---------
            st.set_page_config(
                menu_items=get_about_content(),
                layout="wide"
            )

            # Indicate init is done; next rerun will show the real landing page
            st.session_state["first_run"] = False
            st.rerun()

    # ------------ Full landing, once ready ------------
    if not st.session_state["first_run"]:
        env = st.session_state['env']
        # Page navigation: you can keep your page logic here
        if "current_page" not in st.session_state:
            st.session_state.current_page = "AGILAB"
        if st.session_state.current_page == "AGILAB":
            page(env)
        elif st.session_state.current_page == "▶️ EDIT":
            import importlib
            page_module = importlib.import_module("pages.▶️ EDIT")
            page_module.main()
        else:
            page(env)

# ----------------- Run App -----------------
if __name__ == "__main__":
    main()
