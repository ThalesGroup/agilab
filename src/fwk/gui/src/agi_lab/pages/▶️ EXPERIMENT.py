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

from agi_lab.pagelib import env, render_logo
import streamlit as st

# ===========================
# Imports
# ===========================
import os
import toml
import json
import webbrowser
from pathlib import Path
import mlflow
import pandas as pd
from code_editor import code_editor

# Project Libraries:
from agi_lab.pagelib import (
    find_files,
    run_lab,
    load_df,
    get_custom_buttons,
    get_info_bar,
    get_about_content,
    get_css_text,
    default_df,
    export_df,
    scan_dir,
    on_df_change,
)

# Set page configuration
# Set page configuration
st.set_page_config(
    layout="wide",
    menu_items=get_about_content(),
)

steps_file_name = "lab_steps.toml"
default_df = "export.csv"
st.session_state.setdefault("steps_file_name", steps_file_name)

# load preprompt
pre_prompt_file = env.app_src_path / "pre_prompt.json"
with open(pre_prompt_file) as f:
    pre_prompt = json.load(f)

# Initialize session state variables if not present
st.session_state.setdefault("help_path", env.AGI_LAB_ABS / "src/gui/help")
st.session_state.setdefault("projects", env.projects)

st.session_state.setdefault("snippet_file", env.AGILAB_LOG_ABS / "lab_snippet.py")

# Initialize session state variables
st.session_state.setdefault("server_started", False)
st.session_state.setdefault("mlflow_port", 5000)

# Load custom components and styles
custom_buttons = get_custom_buttons()
info_bar = get_info_bar()
css_text = get_css_text()
css_style = {"style": {"borderRadius": "0px 0px 8px 8px"}}

df_dir_def = env.AGILAB_EXPORT_ABS / env.target

st.session_state.setdefault("steps_file", env.app_src_path / steps_file_name)

st.session_state.setdefault(
    "df_file_out", df_dir_def / ("lab_" + default_df.replace(".csv", "_out.csv"))
)

st.session_state.setdefault("df_file", df_dir_def / default_df)
df_file = Path(st.session_state["df_file"]) if st.session_state["df_file"] else None
if df_file:
    render_logo("Experiment on DATA")
else:
    render_logo("Experiment on APPS")
# Set session defaults
session_defaults = {
    "response_dict": {"type": "", "text": ""},
    "apps_abs": env.apps_root,
    "page_broken": False,
    "step_checked": False,
    "virgin_page": True,
}

for key, default in session_defaults.items():
    st.session_state.setdefault(key, default)


class JumpToMain(Exception):
    """
    Custom exception to jump back to the main execution flow.
    """

    pass


def on_page_change():
    """
    Set the 'page_broken' flag in the session_state when a page change event occurs.

    Args:
        None

    Returns:
        None
    """
    st.session_state.page_broken = True


def on_step_change(module_dir, steps_file, index_step: int, index_page: str):
    """
    Update session state when a step is selected.

    Args:
        index_step (int): The step index.
        index_page (str): The index page identifier.
    """
    st.session_state[index_page][0] = index_step
    st.session_state.step_checked = False
    key = f"{index_page}_q"
    if key in st.session_state:
        del st.session_state[key]
    key = f"{index_page}_a_{index_step}"
    if key in st.session_state:
        del st.session_state[key]
    load_last_step(module_dir, steps_file, index_page)


def load_last_step(module_dir, steps_file, index_page):
    """
    Load the last step for a module.

    Args:
        module_dir (Path): The module path.
        steps_file (Path): The steps file path.
        index_page (str): The index page identifier.
    """
    all_steps = load_all_steps(module_dir, steps_file, index_page)
    if all_steps:
        last_step = len(all_steps) - 1
        current_step = st.session_state[index_page][0]

        if current_step <= last_step:
            st.session_state[index_page][1:5] = list(all_steps[current_step].values())
        else:
            clean_query(index_page)


def clean_query(index_page):
    """
    Reset the query fields in session state.

    Args:
        index_page (str): The index page identifier.
    """
    st.session_state[index_page][1:-1] = [
        st.session_state.df_file,
        None,
        None,
        None,
    ]


def load_all_steps(module_path, steps_file, index_page):
    """
    Load all steps for a module.

    Args:
        module_path (Path): The module path.
        steps_file (Path): The steps file path.
        index_page (str): The index page identifier.

    Returns:
        list: List of steps.
    """
    if not module_path or not module_path.exists() or len(module_path.parts) < 2:
        return None

    module = module_path.stem
    steps_file = Path(steps_file)
    filtered_entries = []
    if steps_file.exists():
        try:
            with open(steps_file, "r") as f:
                steps = toml.load(f)
                if module in steps:
                    filtered_entries = list(steps[module])
                    if filtered_entries and not st.session_state[index_page][-1]:
                        st.session_state[index_page][-1] = len(filtered_entries)
                    if not steps_file.with_suffix(".ipynb").exists():
                        toml_to_notebook(steps, steps_file)
        except toml.TomlDecodeError as e:
            st.error(f"Error decoding TOML file: {e}")
    return filtered_entries


def on_query_change(module, step, steps_file, df_file, index_page, env):
    """
    Handle the query action.

    Args:
        module (str): The module name.
        step (int): The step index.
        steps_file (Path): The steps file path.
        df_file (Path): The DataFrame file path.
        index_page (str): The index page identifier.
        env: The environment configuration object.
    """
    try:
        request_key = f"{index_page}_q"
        if st.session_state.get(request_key):
            answer = ask_gpt(
                st.session_state[request_key], df_file, index_page, env.envars
            )
            nstep, entry = save_step(module, answer, step, 0, steps_file)
            st.session_state[index_page][0] = step
            st.session_state[index_page][1:5] = entry.values()
            st.session_state[index_page][-1] = nstep
        del st.session_state[f"{index_page}_a_{step}"]
        st.session_state.page_broken = True
    except JumpToMain:
        pass


def extract_code(gpt_message):
    """
    Extract code and additional details from a GPT message.

    Args:
        gpt_message (str): The GPT response message.

    Returns:
        tuple: A tuple containing the code and additional details (code, detail).
    """
    if gpt_message:
        parts = gpt_message.split("```")
        code = ""
        if len(parts) > 1:
            code = parts[1].replace("`", "").strip()
            if code.startswith("python"):
                code = code[6:].strip()
        detail = parts[2] if len(parts) > 2 else ""
        return code, detail
    return "", ""


def chat_online(input_request, prompt, envars):
    """
    Send a chat request to the OpenAI API.

    Args:
        input_request (str): The user's input request.
        prompt (list): The conversation history.
        envars (dict): Environment variables containing API keys.

    Returns:
        str: The assistant's response.
    """
    import openai

    prompt.append({"role": "user", "content": input_request})
    try:
        client = openai.OpenAI(api_key=envars.get("OPENAI_API_KEY", ""))
        response = client.chat.completions.create(
            model="gpt-4o", messages=prompt, max_tokens=500, temperature=0.0
        )
        prompt.pop()
        return response.choices[0].message.content.strip()
    except openai.OpenAIError as e:
        st.error(f"OpenAI API error: {e}")
        raise JumpToMain(e)
    except Exception as e:
        st.error(f"Error: {e}")
        raise JumpToMain(e)


def ask_gpt(question, df_file, index_page, envars):
    """
    Send a question to GPT and get the response.

    Args:
        question (str): The question to ask.
        df_file (Path): The DataFrame file path.
        index_page (str): The index page identifier.
        envars (dict): Environment variables.

    Returns:
        list: A list containing [df_file, question, code, message].
    """
    prompt = st.session_state.get("lab_prompt", [])
    result = chat_online(question, prompt, envars)
    code, message = extract_code(result)
    return [df_file, question, code, message] if result else [df_file, None, None, None]


def is_query_valid(query):
    """
    Check if a query is valid.

    Args:
        query (list): The query data.

    Returns:
        bool: True if valid, False otherwise.
    """
    return isinstance(query, list) and query[2]


def get_steps_list(module, steps_file):
    """
    Get the list of steps for a specific module from a TOML file.

    Args:
        module (str): The name of the module to get steps for.
        steps_file (str): The path to the TOML file containing the steps.

    Returns:
        list: The list of steps for the specified module, or an empty list if not found.
    """
    try:
        with open(steps_file, "r") as f:
            steps = toml.load(f)
    except (FileNotFoundError, toml.TomlDecodeError):
        steps = {}

    return steps.get(module, [])


def get_steps_dict(module, steps_file):
    """
    Get the steps dictionary from a TOML file.

    Args:
        module (str): The module name.
        steps_file (str): The path to the TOML file containing steps data.

    Returns:
        dict: A dictionary containing the steps data.
    """
    try:
        with open(steps_file, "r") as f:
            steps = toml.load(f)
    except (FileNotFoundError, toml.TomlDecodeError):
        steps = {}

    return steps


def remove_step(module: str, step: str, steps_file, index_page) -> int:
    """
    Remove a step from the steps file.

    Args:
        module (str): The module name.
        step (str): The step index.
        steps_file (Path): The steps file path.
        index_page (str): The index page identifier.

    Returns:
        int: The remaining number of steps.
    """
    steps = get_steps_dict(module, steps_file)
    nsteps = len(steps)
    index_step = int(step)
    if 0 <= index_step < nsteps:
        del steps[module][index_step]
        nsteps -= 1
        st.session_state[index_page][0] = max(0, nsteps - 1)
        st.session_state[index_page][-1] = nsteps
    else:
        st.session_state[index_page][0] = 0

    with open(steps_file, "w") as f:
        toml.dump(steps, f)

    return nsteps


def toml_to_notebook(toml_data, toml_path):
    """
    Convert TOML data to a Jupyter notebook.

    Args:
        toml_data (dict): The TOML data.
        toml_path (Path): The TOML file path.
    """
    notebook_data = {"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}

    for module, steps in toml_data.items():
        for step in steps:
            code_cell = {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": (
                    step["C"].splitlines(keepends=True)
                    if "C" in step and step["C"]
                    else None
                ),
            }
            notebook_data["cells"].append(code_cell)

    notebook_path = toml_path.with_suffix(".ipynb")

    with open(notebook_path, "w", encoding="utf-8") as nb_file:
        json.dump(notebook_data, nb_file, indent=2)


def save_query(module: str, query, steps_file):
    """
    Save the query to the steps file.

    Args:
        module (str): The module name.
        query (list): The query data.
        steps_file (Path): The steps file path.
    """
    if is_query_valid(query):
        query[-1], entry = save_step(
            module, query[1:5], query[0], query[-1], steps_file
        )
    export_df()


def save_step(module: str, query, current_step, nsteps, steps_file) -> int:
    """
    Save a step in the steps file.

    Args:
        module (str): The module name.
        answer (list): The answer data.
        current_step (int): The current step index.
        nsteps (int): The number of steps.
        steps_file (Path): The steps file path.

    Returns:
        int: The updated number of steps.
    """
    entry = {field: query[i] for i, field in enumerate(["D", "Q", "C", "M"])}

    if steps_file.exists():
        with open(steps_file, "r") as f:
            steps = toml.load(f)
    else:
        os.makedirs(steps_file.parent, exist_ok=True)
        with open(steps_file, "w") as f:
            f.write("")
            steps = {}

    steps.setdefault(module, [])
    nsteps_saved = len(steps[module])
    nsteps = max(nsteps, nsteps_saved)

    index_step = int(current_step)
    if index_step < nsteps_saved:
        steps[module][index_step] = entry
    else:
        steps[module].append(entry)

    with open(steps_file, "w") as f:
        toml.dump(steps, f)
    toml_to_notebook(steps, steps_file)
    return nsteps, entry


def on_nb_change(module, query, file_step_path, project, notebook_file, env):
    """
    Handle the notebook action.

    Args:
        module (str): The module name.
        query (list): The query data.
        file_step_path (Path): The steps file path.
        project (str): The project name.
        notebook_file (Path): The notebook file path.
        env: The environment configuration object.
    """
    save_step(module, query[1:5], query[0], query[-1], file_step_path)
    project_path = env.apps_root / project

    if notebook_file.exists():
        cmd = f"uv run jupyter notebook {notebook_file}"
        output = run_agi(cmd, venv=project_path, wait=True)
        if output is None:
            open_notebook_in_browser()
        else:
            st.info(output)
    else:
        st.info(f"No file named {notebook_file} found!")


def notebook_to_toml(uploaded_file, toml_file_name, module_dir):
    """
    Convert a Jupyter notebook to a TOML file.

    Args:
        uploaded_file (UploadedFile): The uploaded notebook file.
        toml_file_name (str): The TOML file name.
        module_dir (Path): The module path.

    Returns:
        int: The number of code cells converted.
    """
    toml_path = module_dir / toml_file_name
    file_content = uploaded_file.read().decode("utf-8")
    notebook_content = json.loads(file_content)
    toml_content = {}
    module = module_dir.name
    toml_content[module] = []
    cell_count = 0
    for cell in notebook_content.get("cells", []):
        if cell.get("cell_type") == "code":
            step = {"D": "", "Q": "", "C": "".join(cell.get("source", [])), "M": ""}
            toml_content[module].append(step)
            cell_count += 1

    with open(toml_path, "w", encoding="utf-8") as toml_file:
        toml.dump(toml_content, toml_file)
    return cell_count


def on_import_notebook(key, module_dir, steps_file, index_page):
    """
    Handle the import of a notebook file.

    Args:
        key (str): The session state key.
        module_dir (Path): The module path.
        steps_file (Path): The steps file path.
        index_page (str): The index page identifier.
    """
    uploaded_file = st.session_state.get(key)
    if uploaded_file and "ipynb" in uploaded_file.type:
        cell_count = notebook_to_toml(uploaded_file, steps_file.name, module_dir)
        st.session_state[index_page][-1] = cell_count
        st.session_state.page_broken = True


def on_lab_change(new_index_page):
    """
    Callback function to handle gui changes.
    """

    # del dataframe selection
    if "steps_file" in st.session_state:
        del st.session_state["steps_file"]
    if "df_file" in st.session_state:
        del st.session_state["df_file"]

    # del df_file selectbox
    key = str(st.session_state["index_page"]) + "df"
    if key in st.session_state:
        del st.session_state[key]

    st.session_state["lab_dir"] = new_index_page
    st.session_state.page_broken = True


def open_notebook_in_browser():
    """
    Inject JavaScript to open the Jupyter Notebook URL in a new browser tab.
    """
    # Replace with the actual URL and port where Jupyter Notebook is accessible
    jupyter_url = "http://localhost:8888"  # Adjust the port if necessary

    # JavaScript to open a new tab
    js_code = f"""
    <script>
    window.open("{jupyter_url}", "_blank");
    </script>
    """
    st.components.v1.html(js_code, height=0, width=0)


def sidebar_controls():
    """
    Create sidebar controls for selecting modules and DataFrames.

    Args:
        Agi_export_abs (Path): The export root path.
        module_dir (Path): The module path.
        steps_file_name (str): The steps file name.
        index_page (str): The index page identifier.
        default_df (str): The default DataFrame file name.
    """
    # Set module and paths
    Agi_export_abs = Path(env.AGILAB_EXPORT_ABS)
    modules = st.session_state.get(
        "modules", scan_dir(Agi_export_abs)
    )  # Use the target from Agienv
    # st.session_state.setdefault("index_page", str(module_path.relative_to(env.AGILAB_EXPORT_ABS)))
    # index_page = st.session_state.get("index_page", env.target)

    st.session_state["lab_dir"] = st.sidebar.selectbox(
        "Lab Directory",
        modules,
        index=modules.index(
            st.session_state["lab_dir"]
            if "lab_dir" in st.session_state
            else env.target
        ),
        on_change=lambda: on_lab_change(st.session_state.lab_dir_selectbox),
        key="lab_dir_selectbox",
    )

    steps_file_name = st.session_state["steps_file_name"]
    lab_dir = Agi_export_abs / st.session_state["lab_dir_selectbox"]
    st.session_state.df_dir = Agi_export_abs / lab_dir
    steps_file = env.app_src_path / steps_file_name
    st.session_state["steps_file"] = steps_file
    steps_files = find_files(lab_dir, ".toml")
    st.session_state.steps_files = steps_files

    steps_files_path = [Path(file) for file in steps_files]

    steps_files_rel = [file.relative_to(Agi_export_abs) for file in steps_files_path]

    steps_file_rel = sorted(
        [
            file
            for file in steps_files_rel
            if file.parts[0].startswith(st.session_state["lab_dir"])
        ]
    )

    if "index_page" not in st.session_state:
        index_page = steps_file_rel[0] if steps_file_rel else env.target
        st.session_state["index_page"] = index_page
    else:
        index_page = st.session_state["index_page"]
    index_page_str = str(index_page)
    if steps_file_rel:
        st.sidebar.selectbox(
            "Steps",
            steps_file_rel,
            key="index_page",
            on_change=on_page_change,
        )

    df_files = find_files(lab_dir)
    st.session_state.df_files = df_files
    if not steps_file.parent.exists():
        steps_file.parent.mkdir(parents=True, exist_ok=True)

    df_files_rel = sorted(
        (Path(file).relative_to(Agi_export_abs) for file in df_files),
        key=str,
    )

    key_df = index_page_str + "df"
    index = next(
        (i for i, f in enumerate(df_files_rel) if f.name == default_df),
        0,
    )
    module_path = lab_dir.relative_to(Agi_export_abs)
    st.session_state["module_path"] = env.module_path
    st.sidebar.selectbox(
        "DataFrame",
        df_files_rel,
        key=key_df,
        index=index,
        on_change=on_df_change,
        args=(
            module_path,
            st.session_state.df_file,
            index_page_str,
            steps_file,
        ),
    )
    if st.session_state[key_df]:
        st.session_state["df_file"] = Agi_export_abs / st.session_state[key_df]
    else:
        st.session_state["df_file"] = None
    key = index_page_str + "import_notebook"
    st.sidebar.file_uploader(
        "Import Notebook",
        type="ipynb",
        key=key,
        on_change=on_import_notebook,
        args=(key, module_path, index_page_str, steps_file),
    )


def mlflow_controls():
    """
    Adds MLflow UI controls to the sidebar.
    """
    if st.session_state.get("server_started") and st.sidebar.button("Open MLflow UI"):
        mlflow_port = st.session_state.get("mlflow_port", 5000)
        st.sidebar.info(f"MLflow UI is running on port {mlflow_port}.")
        webbrowser.open_new_tab(f"http://localhost:{mlflow_port}")

        # Display success message and emoji
        st.sidebar.success("MLflow UI has been opened in a new browser tab.")
        st.sidebar.markdown(
            """
            <style>
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100%;
            }
            </style>
            <div class="centered">
                <h1 style='font-size:50px;'>😄</h1>
            </div>
            """,
            unsafe_allow_html=True,
        )
    elif not st.session_state.get("server_started"):
        st.sidebar.error("MLflow UI server is not running. Please start it from Edit.")


def page():
    """
    Render the main page of the Streamlit app.
    """
    st.session_state["lab_prompt"] = pre_prompt
    # Sidebar controls
    sidebar_controls()
    lab_dir = st.session_state["lab_dir"]
    index_page = st.session_state.get("index_page", lab_dir)
    index_page_str = str(index_page)

    # Ensure steps file directory exists
    steps_file = st.session_state["steps_file"]
    steps_file.parent.mkdir(parents=True, exist_ok=True)

    # Initialize or update the step count
    nsteps = len(get_steps_list(lab_dir, steps_file))
    st.session_state.setdefault(index_page_str, [nsteps, "", "", "", "", nsteps])

    module_path = st.session_state["module_path"]

    # Load the last step
    load_last_step(module_path, steps_file, index_page_str)

    # Display info if DataFrame is not found and stop execution
    if not df_file or not df_file.exists():
        st.info(f"No DataFrame found in {lab_dir}")
        st.stop()

    # Load custom components and styles
    custom_buttons = get_custom_buttons()
    info_bar = get_info_bar()
    css_text = get_css_text()
    css_style = {"style": {"borderRadius": "0px 0px 8px 8px"}}
    mlflow_controls()

    #####################################################
    # Page layout and tabs
    #####################################################
    lab_tab, history_tab = st.tabs(["ASSISTANT", "HISTORY"])

    with (lab_tab):
        query = st.session_state[index_page_str]
        step = query[0]

        # Render the steps' buttons
        st.subheader(f"Step {step + 1}")
        if query[-1]:
            buttons_per_line = 20
            cols = st.columns(buttons_per_line)
            for idx_button in range(query[-1]):
                col = cols[idx_button % buttons_per_line]
                str_button = str(idx_button + 1)
                col.button(
                    str_button,
                    use_container_width=True,
                    on_click=on_step_change,
                    args=(module_path, steps_file, idx_button, index_page_str),
                    key=f"{index_page_str}_step_{str_button}",
                )

                idx_button += 1

        # Render the chatGPT query input
        st.text_area(
            "Ask chatGPT:",
            value=query[2],
            key=f"{index_page_str}_q",
            on_change=on_query_change,
            args=(lab_dir, step, steps_file, df_file, index_page_str, env),
            placeholder="Enter your snippet in natural language",
            label_visibility="collapsed",
        )

        # Render the snippet code editor
        if query[3]:
            snippet_dict = code_editor(
                query[3] if query[3].endswith("\n") else query[3] + "\n",
                height=(min(30, len(query[3])) if query[3] else 100),
                theme="contrast",
                buttons=custom_buttons,
                info=info_bar,
                component_props=css_text,
                props=css_style,
                key=f"{index_page_str}_a_{step}",
            )

            if snippet_dict["type"] == "remove":
                if st.session_state[index_page_str][-1] > 0:
                    query[-1] = remove_step(lab_dir, step, steps_file, index_page_str)
            elif snippet_dict["type"] == "save":
                query[3] = snippet_dict["text"]
                save_query(lab_dir, query, steps_file)
            elif snippet_dict["type"] == "next":
                query[3] = snippet_dict["text"]
                save_query(lab_dir, query, steps_file)
                if query[0] < query[-1]:
                    query[0] += 1
                    clean_query(index_page_str)
            elif snippet_dict["type"] == "run":
                query[3] = snippet_dict["text"]
                save_query(lab_dir, query, steps_file)
                if query[3]:
                    if not st.session_state["step_checked"]:
                        run_lab(
                            query[1:-2],
                            st.session_state["snippet_file"],
                            env.copilot_file,
                        )
                        if (
                                isinstance(st.session_state.get("data"), pd.DataFrame)
                                and not st.session_state["data"].empty
                        ):
                            st.session_state["data"].to_csv(
                                st.session_state["df_file_out"], index=False
                            )
                            st.session_state["df_file_in"] = st.session_state[
                                "df_file_out"
                            ]
                            st.session_state["step_checked"] = True

        # Render the dataframe display
        if "loaded_df" not in st.session_state:
            st.session_state["loaded_df"] = load_df_cached(df_file)

        loaded_df = st.session_state["loaded_df"]
        if isinstance(loaded_df, pd.DataFrame) and not loaded_df.empty:
            st.dataframe(loaded_df)

        ###################
        # Sidebar rendering
        ####################
        # Steps file input
        file_step = st.sidebar.text_input("steps-file:", value=steps_file.name)
        file_step_path = steps_file.parent / file_step
        notebook_path = file_step_path.with_suffix(".ipynb")

        # Notebook file input
        notebook_file = st.sidebar.text_input(
            "notebook-file:", value=notebook_path.name
        )

        # Create columns to place widgets side by side

        st.sidebar.button(
            "apply on data",
            type="primary",
            on_click=save_query,
            args=(lab_dir, query, file_step_path),
            help="run on data",
        )
        col2, col3 = st.sidebar.columns(2)

        # Buttons in the third column

        col2.button(
            "save",
            type="primary",
            on_click=toml_to_notebook,
            args=(query, notebook_path.parent / notebook_file),
            help="save notebook",
        )

        col3.button(
            "open",
            type="primary",
            on_click=on_nb_change,
            args=(
                lab_dir,
                query,
                file_step_path,
                env.app,
                notebook_path.parent / notebook_file,
                env,
            ),
            help="open notebook",
        )

    with history_tab:
        # Add code editor component
        if steps_file.exists():
            with open(steps_file, "r") as f:
                code = f.read()
        else:
            code = ""

        action_onsteps = code_editor(
            code,
            height=min(30, len(code)),
            theme="contrast",
            buttons=custom_buttons,
            info=info_bar,
            component_props=css_text,
            props=css_style,
            key=f"steps_{module_path}",
        )

        if action_onsteps["type"] == "save":
            with open(steps_file, "w") as f:
                f.write(action_onsteps["text"])


@st.cache_data
def get_df_files(export_abs_path):
    """
    Get a list of DataFrame files from the export directory.

    Args:
        export_abs_path (Path): The absolute path to the export directory.

    Returns:
        list: List of DataFrame file paths.
    """
    return find_files(export_abs_path)


@st.cache_data
def load_df_cached(path: Path, nrows=50, with_index=True):
    """
    Load a DataFrame from a file, with caching.

    Args:
        path (Path): The path to the DataFrame file.
        nrows (int, optional): Number of rows to read.
        with_index (bool): Whether to use the first column as index.

    Returns:
        DataFrame or None: Loaded DataFrame or None if not found.
    """
    return load_df(path, nrows, with_index)


# -------------------- Main Application Entry -------------------- #


def main():
    """
    Main function to run the application.
    """
    try:
        page()

    except Exception as e:
        st.error(f"An error occurred: {e}")
        import traceback

        st.error(traceback.format_exc())


# -------------------- Main Entry Point -------------------- #

if __name__ == "__main__":
    main()