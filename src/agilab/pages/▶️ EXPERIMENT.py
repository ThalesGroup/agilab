import logging
import os
import json
import webbrowser
from pathlib import Path
import importlib
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd
import streamlit as st
import mlflow
import tomli        # For reading TOML files
import tomli_w      # For writing TOML files

from code_editor import code_editor
from agilab.pagelib import (
    activate_mlflow,
    find_files,
    run_lab,
    load_df,
    get_custom_buttons,
    get_info_bar,
    get_about_content,
    get_css_text,
    export_df,
    scan_dir,
    on_df_change,
    render_logo,
)
from agi_env import AgiEnv, normalize_path

# Constants
STEPS_FILE_NAME = "lab_steps.toml"
DEFAULT_DF = "export.csv"
BUTTONS_PER_LINE = 20
JUPYTER_URL = "http://localhost:8888"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class JumpToMain(Exception):
    """Custom exception to jump back to the main execution flow."""
    pass


def convert_paths_to_strings(obj: Any) -> Any:
    """Recursively convert pathlib.Path objects to strings for serialization."""
    if isinstance(obj, dict):
        return {k: convert_paths_to_strings(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_paths_to_strings(item) for item in obj]
    elif isinstance(obj, Path):
        return str(obj)
    else:
        return obj


def on_page_change() -> None:
    """Set the 'page_broken' flag in session state."""
    st.session_state.page_broken = True


def on_step_change(
    module_dir: Path,
    steps_file: Path,
    index_step: int,
    index_page: str,
) -> None:
    """Update session state when a step is selected."""
    st.session_state[index_page][0] = index_step
    st.session_state.step_checked = False
    st.session_state.pop(f"{index_page}_q", None)
    st.session_state.pop(f"{index_page}_a_{index_step}", None)
    load_last_step(module_dir, steps_file, index_page)


def load_last_step(
    module_dir: Path,
    steps_file: Path,
    index_page: str,
) -> None:
    """Load the last step for a module into session state."""
    all_steps = load_all_steps(module_dir, steps_file, index_page)
    if all_steps:
        last_step = len(all_steps) - 1
        current_step = st.session_state[index_page][0]
        if current_step <= last_step:
            st.session_state[index_page][1:5] = list(all_steps[current_step].values())
        else:
            clean_query(index_page)


def clean_query(index_page: str) -> None:
    """Reset the query fields in session state."""
    st.session_state[index_page][1:-1] = [
        st.session_state.df_file,
        None,
        None,
        None,
    ]


def load_all_steps(
    module_path: Path,
    steps_file: Path,
    index_page: str,
) -> Optional[List[Dict[str, Any]]]:
    """Load all steps for a module from a TOML file."""
    if not module_path or not module_path.exists() or len(module_path.parts) < 2:
        return None
    module = module_path.stem
    filtered_entries: List[Dict[str, Any]] = []
    if steps_file.exists():
        try:
            with open(steps_file, "rb") as f:
                steps = tomli.load(f)
            if module in steps:
                filtered_entries = list(steps[module])
                if filtered_entries and not st.session_state[index_page][-1]:
                    st.session_state[index_page][-1] = len(filtered_entries)
                if not steps_file.with_suffix(".ipynb").exists():
                    toml_to_notebook(steps, steps_file)
        except tomli.TOMLDecodeError as e:
            st.error(f"Error decoding TOML file: {e}")
            logger.error(f"TOML decode error: {e}")
    return filtered_entries


def on_query_change(
    module: Path,
    step: int,
    steps_file: Path,
    df_file: Path,
    index_page: str,
    env: AgiEnv,
) -> None:
    """Handle the query action when user input changes."""
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
        st.session_state.pop(f"{index_page}_a_{step}", None)
        st.session_state.page_broken = True
    except JumpToMain:
        pass


def extract_code(gpt_message: str) -> Tuple[str, str]:
    """Extract Python code and details from GPT message."""
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


def chat_online(
    input_request: str,
    prompt: List[Dict[str, str]],
    envars: Dict[str, str],
) -> str:
    """Send a chat request to OpenAI API."""
    import openai

    prompt.append({"role": "user", "content": input_request})
    try:
        client = openai.OpenAI(api_key=envars.get("OPENAI_API_KEY", ""))
        response = client.chat.completions.create(
            model="gpt-5-nano", messages=prompt, max_tokens=500, temperature=0.0
        )
        prompt.pop()
        return response.choices[0].message.content.strip()
    except openai.OpenAIError as e:
        st.error(f"OpenAI API error: {e}")
        logger.error(f"OpenAI error: {e}")
        raise JumpToMain(e)
    except Exception as e:
        st.error(f"Error: {e}")
        logger.error(f"General error in chat_online: {e}")
        raise JumpToMain(e)


def ask_gpt(
    question: str,
    df_file: Path,
    index_page: str,
    envars: Dict[str, str],
) -> List[Any]:
    """Send a question to GPT and get the response."""
    prompt = st.session_state.get("lab_prompt", [])
    result = chat_online(question, prompt, envars)
    code, message = extract_code(result)
    return [df_file, question, code, message] if result else [df_file, None, None, None]


def is_query_valid(query: Any) -> bool:
    """Check if a query is valid."""
    return isinstance(query, list) and bool(query[2])


def get_steps_list(module: Union[str, Path], steps_file: Path) -> List[Any]:
    """Get the list of steps for a module from a TOML file."""
    try:
        with open(steps_file, "rb") as f:
            steps = tomli.load(f)
    except (FileNotFoundError, tomli.TOMLDecodeError):
        steps = {}
    return steps.get(str(module), [])


def get_steps_dict(module: Union[str, Path], steps_file: Path) -> Dict[str, Any]:
    """Get the steps dictionary from a TOML file."""
    try:
        with open(steps_file, "rb") as f:
            steps = tomli.load(f)
    except (FileNotFoundError, tomli.TOMLDecodeError):
        steps = {}
    return steps


def remove_step(
    module: Union[str, Path],
    step: str,
    steps_file: Path,
    index_page: str,
) -> int:
    """Remove a step from the steps file."""
    steps = get_steps_dict(module, steps_file)
    nsteps = len(steps.get(str(module), []))
    index_step = int(step)
    if 0 <= index_step < nsteps:
        del steps[str(module)][index_step]
        nsteps -= 1
        st.session_state[index_page][0] = max(0, nsteps - 1)
        st.session_state[index_page][-1] = nsteps
    else:
        st.session_state[index_page][0] = 0

    serializable_steps = convert_paths_to_strings(steps)
    try:
        with open(steps_file, "wb") as f:
            tomli_w.dump(serializable_steps, f)
    except Exception as e:
        st.error(f"Failed to save steps file: {e}")
        logger.error(f"Error writing TOML in remove_step: {e}")

    return nsteps


def toml_to_notebook(toml_data: Dict[str, Any], toml_path: Path) -> None:
    """Convert TOML steps data to a Jupyter notebook file."""
    notebook_data = {"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    for module, steps in toml_data.items():
        for step in steps:
            code_cell = {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": (step.get("C", "").splitlines(keepends=True) if step.get("C") else []),
            }
            notebook_data["cells"].append(code_cell)
    notebook_path = toml_path.with_suffix(".ipynb")
    try:
        with open(notebook_path, "w", encoding="utf-8") as nb_file:
            json.dump(notebook_data, nb_file, indent=2)
    except Exception as e:
        st.error(f"Failed to save notebook: {e}")
        logger.error(f"Error saving notebook in toml_to_notebook: {e}")


def save_query(module: Union[str, Path], query: List[Any], steps_file: Path) -> None:
    """Save the query to the steps file if valid."""
    if is_query_valid(query):
        query[-1], _ = save_step(module, query[1:5], query[0], query[-1], steps_file)
    export_df()


def save_step(
    module: Union[str, Path],
    query: List[Any],
    current_step: int,
    nsteps: int,
    steps_file: Path,
) -> Tuple[int, Dict[str, Any]]:
    """Save a step in the steps file."""
    entry = {field: query[i] for i, field in enumerate(["D", "Q", "C", "M"])}
    if steps_file.exists():
        with open(steps_file, "rb") as f:
            steps = tomli.load(f)
    else:
        os.makedirs(steps_file.parent, exist_ok=True)
        steps = {}

    module_str = str(module)
    steps.setdefault(module_str, [])
    nsteps_saved = len(steps[module_str])
    nsteps = max(nsteps, nsteps_saved)
    index_step = int(current_step)

    if index_step < nsteps_saved:
        steps[module_str][index_step] = entry
    else:
        steps[module_str].append(entry)

    serializable_steps = convert_paths_to_strings(steps)
    try:
        with open(steps_file, "wb") as f:
            tomli_w.dump(serializable_steps, f)
    except Exception as e:
        st.error(f"Failed to save steps file: {e}")
        logger.error(f"Error writing TOML in save_step: {e}")

    toml_to_notebook(steps, steps_file)
    return nsteps, entry


def on_nb_change(
    module: Union[str, Path],
    query: List[Any],
    file_step_path: Path,
    project: str,
    notebook_file: Path,
    env: AgiEnv,
) -> None:
    """Handle notebook interaction and run notebook if possible."""
    save_step(module, query[1:5], query[0], query[-1], file_step_path)
    project_path = env.apps_dir / project
    if notebook_file.exists():
        cmd = f"uv -q run jupyter notebook {notebook_file}"
        output = run_lab(cmd, venv=project_path, wait=True)
        if output is None:
            open_notebook_in_browser()
        else:
            st.info(output)
    else:
        st.info(f"No file named {notebook_file} found!")


def notebook_to_toml(
    uploaded_file: Any,
    toml_file_name: str,
    module_dir: Path,
) -> int:
    """Convert uploaded Jupyter notebook file to a TOML file."""
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
    try:
        with open(toml_path, "wb") as toml_file:
            tomli_w.dump(toml_content, toml_file)
    except Exception as e:
        st.error(f"Failed to save TOML file: {e}")
        logger.error(f"Error writing TOML in notebook_to_toml: {e}")
    return cell_count


def on_import_notebook(
    key: str,
    module_dir: Path,
    steps_file: Path,
    index_page: str,
) -> None:
    """Handle notebook file import via sidebar uploader."""
    uploaded_file = st.session_state.get(key)
    if uploaded_file and "ipynb" in uploaded_file.type:
        cell_count = notebook_to_toml(uploaded_file, steps_file.name, module_dir)
        st.session_state[index_page][-1] = cell_count
        st.session_state.page_broken = True


def on_lab_change(new_index_page: str) -> None:
    """Handle lab directory change event."""
    st.session_state.pop("steps_file", None)
    st.session_state.pop("df_file", None)
    key = str(st.session_state.get("index_page", "")) + "df"
    st.session_state.pop(key, None)
    st.session_state["lab_dir"] = new_index_page
    st.session_state.page_broken = True


def open_notebook_in_browser() -> None:
    """Inject JS to open the Jupyter Notebook URL in a new tab."""
    js_code = f"""
    <script>
    window.open("{JUPYTER_URL}", "_blank");
    </script>
    """
    st.components.v1.html(js_code, height=0, width=0)


def sidebar_controls() -> None:
    """Create sidebar controls for selecting modules and DataFrames."""
    env: AgiEnv = st.session_state["env"]
    Agi_export_abs = Path(env.AGILAB_EXPORT_ABS)
    modules = st.session_state.get("modules", scan_dir(Agi_export_abs))

    st.session_state["lab_dir"] = st.sidebar.selectbox(
        "Lab Directory",
        modules,
        index=modules.index(st.session_state.get("lab_dir", env.target)),
        on_change=lambda: on_lab_change(st.session_state.lab_dir_selectbox),
        key="lab_dir_selectbox",
    )

    steps_file_name = st.session_state["steps_file_name"]
    lab_dir = Agi_export_abs / st.session_state["lab_dir_selectbox"]
    st.session_state.df_dir = Agi_export_abs / lab_dir
    steps_file = env.app_abs / steps_file_name
    st.session_state["steps_file"] = steps_file

    steps_files = find_files(lab_dir, ".toml")
    st.session_state.steps_files = steps_files
    steps_files_path = [Path(file) for file in steps_files]
    steps_files_rel = [file.relative_to(Agi_export_abs) for file in steps_files_path]
    steps_file_rel = sorted(
        [file for file in steps_files_rel if file.parts[0].startswith(st.session_state["lab_dir"])]
    )

    if "index_page" not in st.session_state:
        index_page = steps_file_rel[0] if steps_file_rel else env.target
        st.session_state["index_page"] = index_page
    else:
        index_page = st.session_state["index_page"]

    index_page_str = str(index_page)

    if steps_file_rel:
        st.sidebar.selectbox("Steps", steps_file_rel, key="index_page", on_change=on_page_change)

    df_files = find_files(lab_dir)
    st.session_state.df_files = df_files

    if not steps_file.parent.exists():
        steps_file.parent.mkdir(parents=True, exist_ok=True)

    df_files_rel = sorted((Path(file).relative_to(Agi_export_abs) for file in df_files), key=str)
    key_df = index_page_str + "df"
    index = next((i for i, f in enumerate(df_files_rel) if f.name == DEFAULT_DF), 0)

    module_path = lab_dir.relative_to(Agi_export_abs)
    st.session_state["module_path"] = env.module_path

    st.sidebar.selectbox(
        "DataFrame",
        df_files_rel,
        key=key_df,
        index=index,
        on_change=on_df_change,
        args=(module_path, st.session_state.df_file, index_page_str, steps_file),
    )

    if st.session_state.get(key_df):
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


def mlflow_controls() -> None:
    """Display MLflow UI controls in sidebar."""
    if st.session_state.get("server_started") and st.sidebar.button("Open MLflow UI"):
        mlflow_port = st.session_state.get("mlflow_port", 5000)
        st.sidebar.info(f"MLflow UI is running on port {mlflow_port}.")
        webbrowser.open_new_tab(f"http://localhost:{mlflow_port}")
        st.sidebar.success("MLflow UI has been opened in a new browser tab.")
        st.sidebar.markdown(
            """
            <style>
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100%;
            </style>
            <div class="centered">
                <h1 style='font-size:50px;'>😄</h1>
            </div>
            """,
            unsafe_allow_html=True,
        )
    elif not st.session_state.get("server_started"):
        st.sidebar.error("MLflow UI server is not running. Please start it from Edit.")


def display_lab_tab(
    lab_dir: Path,
    index_page_str: str,
    steps_file: Path,
    module_path: Path,
    env: AgiEnv,
) -> None:
    """Display the ASSISTANT tab with steps and query input."""
    query = st.session_state[index_page_str]
    step = query[0]
    st.markdown(f"<h3 style='font-size:16px;'>Step {step + 1}</h3>", unsafe_allow_html=True)

    if query[-1]:
        cols = st.columns(BUTTONS_PER_LINE)
        for idx_button in range(query[-1]):
            col = cols[idx_button % BUTTONS_PER_LINE]
            str_button = str(idx_button + 1)
            col.button(
                str_button,
                use_container_width=True,
                on_click=on_step_change,
                args=(module_path, steps_file, idx_button, index_page_str),
                key=f"{index_page_str}_step_{str_button}",
            )

    st.text_area(
        "Ask chatGPT:",
        value=query[2],
        key=f"{index_page_str}_q",
        on_change=on_query_change,
        args=(lab_dir, step, steps_file, st.session_state.df_file, index_page_str, env),
        placeholder="Enter your snippet in natural language",
        label_visibility="collapsed",
    )

    if query[3]:
        snippet_dict = code_editor(
            query[3] if query[3].endswith("\n") else query[3] + "\n",
            height=(min(30, len(query[3])) if query[3] else 100),
            theme="contrast",
            buttons=get_custom_buttons(),
            info=get_info_bar(),
            component_props=get_css_text(),
            props={"style": {"borderRadius": "0px 0px 8px 8px"}},
            key=f"{index_page_str}_a_{step}",
        )
        if snippet_dict["type"] == "remove":
            if st.session_state[index_page_str][-1] > 0:
                query[-1] = remove_step(lab_dir, str(step), steps_file, index_page_str)
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
            if query[3] and not st.session_state.get("step_checked", False):
                run_lab(
                    query[1:-2],
                    st.session_state["snippet_file"],
                    env.copilot_file,
                )
                if isinstance(st.session_state.get("data"), pd.DataFrame) and not st.session_state["data"].empty:
                    st.session_state["data"].to_csv(
                        st.session_state["df_file_out"], index=False
                    )
                    st.session_state["df_file_in"] = st.session_state["df_file_out"]
                    st.session_state["step_checked"] = True

    if "loaded_df" not in st.session_state:
        st.session_state["loaded_df"] = load_df_cached(st.session_state.df_file)
    loaded_df = st.session_state["loaded_df"]
    if isinstance(loaded_df, pd.DataFrame) and not loaded_df.empty:
        st.dataframe(loaded_df)
    else:
        st.info("No data loaded yet. Click 'Run' to load dataset.")


def display_history_tab(steps_file: Path, module_path: Path) -> None:
    """Display the HISTORY tab with code editor for steps file."""
    if steps_file.exists():
        with open(steps_file, "rb") as f:
            code = f.read().decode("utf-8")
    else:
        code = ""
    action_onsteps = code_editor(
        code,
        height=min(30, len(code)),
        theme="contrast",
        buttons=get_custom_buttons(),
        info=get_info_bar(),
        component_props=get_css_text(),
        props={"style": {"borderRadius": "0px 0px 8px 8px"}},
        key=f"steps_{module_path}",
    )
    if action_onsteps["type"] == "save":
        try:
            with open(steps_file, "wb") as f:
                tomli_w.dump(json.loads(action_onsteps["text"]), f)
        except Exception as e:
            st.error(f"Failed to save steps file from editor: {e}")
            logger.error(f"Error saving steps file from editor: {e}")


def page() -> None:
    """Main page logic handler."""
    global df_file

    if 'env' not in st.session_state or not getattr(st.session_state["env"], "init_done", False):
        page_module = importlib.import_module("AGILAB")
        page_module.main()
        st.rerun()

    env: AgiEnv = st.session_state["env"]

    with open(Path(env.app_src) / "pre_prompt.json") as f:
        st.session_state["lab_prompt"] = json.load(f)

    sidebar_controls()

    lab_dir = Path(st.session_state["lab_dir"])
    index_page = st.session_state.get("index_page", lab_dir)
    index_page_str = str(index_page)
    steps_file = st.session_state["steps_file"]
    steps_file.parent.mkdir(parents=True, exist_ok=True)

    nsteps = len(get_steps_list(lab_dir, steps_file))
    st.session_state.setdefault(index_page_str, [nsteps, "", "", "", "", nsteps])

    module_path = st.session_state["module_path"]
    load_last_step(module_path, steps_file, index_page_str)

    df_file = st.session_state.get("df_file")
    if not df_file or not Path(df_file).exists():
        st.info(f"No DataFrame found in {lab_dir}")
        st.stop()

    mlflow_controls()

    lab_tab, history_tab = st.tabs(["ASSISTANT", "HISTORY"])
    with lab_tab:
        display_lab_tab(lab_dir, index_page_str, steps_file, module_path, env)
    with history_tab:
        display_history_tab(steps_file, module_path)


@st.cache_data
def get_df_files(export_abs_path: Path) -> List[Path]:
    return find_files(export_abs_path)


@st.cache_data
def load_df_cached(path: Path, nrows: int = 50, with_index: bool = True) -> Optional[pd.DataFrame]:
    return load_df(path, nrows, with_index)


def main() -> None:
    if 'env' not in st.session_state or not getattr(st.session_state["env"], "init_done", True):
        page_module = importlib.import_module("AGILAB")
        page_module.main()
        st.rerun()

    env: AgiEnv = st.session_state['env']

    try:
        st.set_page_config(
            layout="wide",
            menu_items=get_about_content(),
        )

        st.session_state.setdefault("steps_file_name", STEPS_FILE_NAME)
        st.session_state.setdefault("help_path", Path(env.agi_fwk) / "gui/help")
        st.session_state.setdefault("projects", env.apps_dir)
        st.session_state.setdefault("snippet_file", Path(env.AGILAB_LOG_ABS) / "lab_snippet.py")
        st.session_state.setdefault("server_started", False)
        st.session_state.setdefault("mlflow_port", 5000)

        df_dir_def = Path(env.AGILAB_EXPORT_ABS) / env.target
        st.session_state.setdefault("steps_file", Path(env.app_abs) / STEPS_FILE_NAME)
        st.session_state.setdefault(
            "df_file_out", df_dir_def / ("lab_" + DEFAULT_DF.replace(".csv", "_out.csv"))
        )
        st.session_state.setdefault("df_file", df_dir_def / DEFAULT_DF)

        df_file = Path(st.session_state["df_file"]) if st.session_state["df_file"] else None
        if df_file:
            render_logo("Experiment on DATA")
        else:
            render_logo("Experiment on APPS")

        if not st.session_state.get("server_started", False):
            activate_mlflow(env)

        # Initialize session defaults
        defaults = {
            "response_dict": {"type": "", "text": ""},
            "apps_abs": env.apps_dir,
            "page_broken": False,
            "step_checked": False,
            "virgin_page": True,
        }
        for key, value in defaults.items():
            st.session_state.setdefault(key, value)

        page()

    except Exception as e:
        st.error(f"An error occurred: {e}")
        import traceback

        st.code(f"```\n{traceback.format_exc()}\n```")


if __name__ == "__main__":
    main()
