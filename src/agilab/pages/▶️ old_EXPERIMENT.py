# ▶️ EXPERIMENT.py — Notebook UI (Query-first) with App selector as default venv for code cells
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import json, uuid, io, contextlib, importlib
import streamlit as st

# ---------- Optional code editor (pip install streamlit-code-editor) ----------
from code_editor import code_editor  # type: ignore

# ---------- Page helpers from pagelib (preferred) ----------
from agi_env.pagelib import inject_theme, render_logo, get_about_content  # your pagelib.py


# ---------- Constants ----------
DEFAULT_DF = "df.csv"
STEPS_FILE_NAME = "steps.toml"
UOAIC_PROVIDER = "uoaic"  # example offline key

# ---------- Small helpers ----------
def _get_env():
    """Return env if present; otherwise a tiny dummy so UI renders."""
    env = st.session_state.get("env")
    if env and getattr(env, "init_done", False):
        return env
    class _Dummy:
        AGILAB_EXPORT_ABS = "."
        target = "default"
        active_app = "."
        envars = {"LAB_LLM_PROVIDER": "openai"}
        apps_dir = Path(".")
        st_resources = {}
        init_done = False
    return _Dummy()

def _s(x: Any) -> str: return str(x) if x is not None else ""
def _norm(x: str) -> str: return str(x).strip() if x else ""

def _looks_like_code(s: str) -> bool:
    if not isinstance(s, str): return False
    s2 = s.strip()
    if not s2: return False
    keys = ("def ","import ","class ","print(","SELECT ","FROM ","JOIN ",
            "plt.","pd.","spark.","return ","{","}","=>")
    return any(k in s2 for k in keys) or "\n" in s2 or s2.endswith(":")

# ---------- Preprompt loader ----------
def _load_preprompt() -> Optional[str]:
    env = st.session_state.get("env")

    # 1) Session state
    for k in ("lab_preprompt", "preprompt"):
        v = st.session_state.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    # 2) Env fields
    if env:
        v = getattr(env, "envars", {}).get("LAB_PREPROMPT")
        if isinstance(v, str) and v.strip():
            return v.strip()
        v = getattr(env, "preprompt", None)
        if isinstance(v, str) and v.strip():
            return v.strip()
        v = getattr(env, "st_resources", {}).get("preprompt")
        if isinstance(v, str) and v.strip():
            return v.strip()
        # File next to active app
        try:
            app_dir = Path(getattr(env, "active_app", "."))
            for name in ("preprompt.md", "preprompt.txt", "system_prompt.md", "system_prompt.txt"):
                p = app_dir / name
                if p.exists():
                    t = p.read_text(encoding="utf-8").strip()
                    if t:
                        return t
        except Exception:
            pass

    # 3) pagelib provider (optional)
    try:
        from pagelib import get_preprompt  # type: ignore
        t = get_preprompt()
        if isinstance(t, str) and t.strip():
            return t.strip()
    except Exception:
        pass

    return None

# ---------- Notebook <-> Steps mapping ----------
Cell = Dict[str, Any]

def _current_module_key(env) -> str:
    app = Path(getattr(env, "active_app", "."))
    return app.name or "default"

# TOML I/O
try:
    import tomli as tomllib  # py<3.11
except Exception:
    try:
        import tomllib       # py>=3.11
    except Exception:
        tomllib = None

try:
    import tomli_w
except Exception:
    tomli_w = None

def _cells_from_toml(steps_file: Path, module_key: Optional[str] = None) -> List[Cell]:
    # If no steps file, start with a QUERY cell (Query-first UX)
    if not (tomllib and steps_file.exists()):
        return [{
            "id": str(uuid.uuid4()),
            "type": "query",
            "content": "",
            "meta": {"provider": st.session_state.get("lab_llm_provider", "openai")}
        }]
    try:
        with open(steps_file, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return [{
            "id": str(uuid.uuid4()),
            "type": "query",
            "content": "",
            "meta": {"provider": st.session_state.get("lab_llm_provider", "openai")}
        }]

    if not isinstance(data, dict) or not data:
        return [{
            "id": str(uuid.uuid4()),
            "type": "query",
            "content": "",
            "meta": {"provider": st.session_state.get("lab_llm_provider", "openai")}
        }]

    key = module_key or list(data.keys())[0]
    steps = data.get(key, [])
    cells: List[Cell] = []
    for step in steps:
        d = _s(step.get("D")).strip()
        q = _s(step.get("Q")).strip()
        c = _s(step.get("C")).strip()
        prov = _s(step.get("M"))
        env_path = _s(step.get("E"))
        # Re-ordered: Query -> Code -> Markdown
        if q:
            cells.append({"id": str(uuid.uuid4()), "type": "query", "content": q, "meta": {"provider": prov}})
        if c:
            meta = {"lang": "python"}
            if env_path:
                meta["env"] = env_path
            cells.append({"id": str(uuid.uuid4()), "type": "code", "content": c, "meta": meta})
        if d:
            cells.append({"id": str(uuid.uuid4()), "type": "markdown", "content": d, "meta": {}})
    if not cells:
        cells.append({"id": str(uuid.uuid4()), "type": "query", "content": "", "meta": {"provider": st.session_state.get("lab_llm_provider", "openai")}})
    return cells

def _cells_to_toml(
    cells: List[Cell],
    steps_file: Path,
    module_key: str,
    *,
    carry_markdown_across_codes: bool
) -> None:
    # PURE serialization — no Streamlit UI here.
    steps: List[Dict[str, Any]] = []
    carry_d, carry_q, carry_m = "", "", ""
    for cell in cells:
        ctype = cell.get("type")
        text = _s(cell.get("content"))
        if ctype == "markdown":
            carry_d = text
        elif ctype == "query":
            carry_q = text
            carry_m = _s(cell.get("meta", {}).get("provider", ""))
        elif ctype == "code":
            env_path = _s(cell.get("meta", {}).get("env", ""))
            steps.append({"D": carry_d, "Q": carry_q, "M": carry_m, "C": text, "E": env_path})
            if not carry_markdown_across_codes:
                carry_d = carry_q = carry_m = ""
        # outputs not persisted
    content = {module_key: steps}
    if tomli_w:
        try:
            with open(steps_file, "wb") as f:
                tomli_w.dump(content, f)
        except Exception as e:
            st.error(f"Failed to save steps TOML: {e}")
    else:
        steps_file.with_suffix(".json").write_text(json.dumps(content, indent=2))

def _save_cells(cells: List[Cell], steps_file: Path, module_key: str) -> None:
    _cells_to_toml(
        cells, steps_file, module_key,
        carry_markdown_across_codes=st.session_state.get("__opt_carry_md_across_codes", True)
    )

def _load_cells(steps_file: Path, module_key: Optional[str] = None) -> List[Cell]:
    return _cells_from_toml(steps_file, module_key)

# ---------- App discovery ----------
def _list_available_apps(env) -> List[Path]:
    root = Path(getattr(env, "apps_dir", "."))
    if not root.exists():
        return []
    items = []
    try:
        for p in root.iterdir():
            if p.is_dir():
                items.append(p)
    except Exception:
        pass
    active = Path(getattr(env, "active_app", ""))
    if active and active.exists():
        items = [active] + [p for p in items if p.resolve() != active.resolve()]
    return items

# ---------- Execution (prefer page/env functions) ----------
def _run_query(prompt: str, provider: str, d_context: str = "") -> dict:
    """
    1) Prefer local run_lab / env.run_lab (NO copilot_file passed)
    2) OpenAI >=1.0 client with preprompt in system
    3) Local exec fallback for 'gpt-oss'
    """
    # 1) Local/ENV runner first
    try:
        env = st.session_state.get("env")

        # make preprompt visible for potential pipeline usage
        st.session_state["lab_preprompt"] = _load_preprompt() or st.session_state.get("lab_preprompt")
        env.run_lab([d_context, prompt, ""], snippet_file=None)
        return st.session_state.get("response_dict", {}) or {}


    except Exception as e:
        st.session_state["response_dict"] = {"text": f"⚠️ run_lab error: {e}"}
        return st.session_state["response_dict"]

    # 2) OpenAI >= 1.0 branch (preprompt restored)
    if provider == "openai":
        try:
            from openai import OpenAI  # pip install -U openai
            client = OpenAI()

            system = _load_preprompt()
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            resp = client.chat.completions.create(
                model="gpt-4o-mini",  # change if needed
                messages=messages,
                temperature=0.2,
            )
            text = (resp.choices[0].message.content or "").strip()
            st.session_state["response_dict"] = {"text": text}
            return st.session_state["response_dict"]
        except Exception as e:
            st.session_state["response_dict"] = {"text": f"⚠️ OpenAI error: {e}"}
            return st.session_state["response_dict"]

    # 3) Local fallback for OSS/dev
    if provider == "gpt-oss":
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                exec(prompt, {}, {})
            out = buf.getvalue() or "(no output)"
            st.session_state["response_dict"] = {"text": out}
            return st.session_state["response_dict"]
        except Exception as e:
            st.session_state["response_dict"] = {"text": f"⚠️ Local error: {e}"}
            return st.session_state["response_dict"]

    st.session_state["response_dict"] = {"text": prompt}
    return st.session_state["response_dict"]

def _run_code(code: str, venv_path: str = "") -> str:
    """
    Prefer local run_agi / env.run_agi; else run_lab; else local exec.
    NO copilot_file passed to run_lab.
    """
    try:
        env = st.session_state.get("env")
        return env.run_agi(code, path=Path(venv_path).expanduser()) or ""

    except Exception as e:
        return f"⚠️ run_agi/lab error: {e}"

    # Last resort: local exec
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            exec(code, {}, {})
        except Exception as e:
            print(f"Error: {e}")
    return buf.getvalue()

# ---------- Sidebar ----------
def sidebar_controls() -> None:
    env = _get_env()

    lab_dir_default = Path(env.AGILAB_EXPORT_ABS) / env.target
    st.session_state.setdefault("lab_dir", str(lab_dir_default))
    st.session_state.setdefault("Agi_export_abs", str(Path(env.AGILAB_EXPORT_ABS)))
    st.session_state.setdefault("steps_file", Path(env.active_app) / STEPS_FILE_NAME)
    st.session_state.setdefault("index_page", Path(st.session_state["lab_dir"]))

    lab_dir = Path(st.session_state["lab_dir"])
    Agi_export_abs = Path(st.session_state["Agi_export_abs"])

    # Assistant engine (kept in sidebar)
    provider_options = {"OpenAI (online)": "openai", "GPT-OSS (local)": "gpt-oss", "Mistral (offline)": UOAIC_PROVIDER}
    labels = list(provider_options.keys())
    cur = st.session_state.get("lab_llm_provider", env.envars.get("LAB_LLM_PROVIDER", "openai"))
    try:
        idx = labels.index(next(lbl for lbl, v in provider_options.items() if v == cur))
    except StopIteration:
        idx = 0
    sel_label = st.sidebar.selectbox("Assistant engine", labels, index=idx)
    sel_provider = provider_options[sel_label]
    st.session_state["lab_llm_provider"] = sel_provider
    env.envars["LAB_LLM_PROVIDER"] = sel_provider

    # DataFrame picker (optional)
    def _find_files(root: Path) -> List[Path]:
        try: return sorted(root.glob("**/*.csv"))
        except Exception: return []
    df_files = _find_files(lab_dir)
    df_files_rel = sorted((Path(f).relative_to(Agi_export_abs) for f in df_files), key=str) if df_files else []
    key_df = "notebook_df_picker"
    index = next((i for i, f in enumerate(df_files_rel) if f.name == DEFAULT_DF), 0) if df_files_rel else 0
    st.sidebar.selectbox(
        "DataFrame",
        df_files_rel or ["(none found)"],
        key=key_df,
        index=index if df_files_rel else 0,
    )
    if st.session_state.get(key_df) and df_files_rel:
        st.session_state["df_file"] = str(Agi_export_abs / st.session_state[key_df])
    else:
        st.session_state["df_file"] = str(Path(env.AGILAB_EXPORT_ABS) / env.target / DEFAULT_DF)

    # Notebook options
    st.sidebar.markdown("### Notebook options")
    st.session_state.setdefault("__opt_autosave", True)
    st.session_state.setdefault("__opt_auto_code_after_query", True)
    st.session_state.setdefault("__opt_show_provider_selector", False)  # moved off toolbar
    st.session_state.setdefault("__opt_carry_md_across_codes", True)

    st.session_state["__opt_autosave"] = st.sidebar.checkbox("Auto-save on edit", value=st.session_state["__opt_autosave"])
    st.session_state["__opt_auto_code_after_query"] = st.sidebar.checkbox("Auto-insert code cell after query", value=st.session_state["__opt_auto_code_after_query"])
    st.session_state["__opt_carry_md_across_codes"] = st.sidebar.checkbox("Carry markdown/query across multiple code cells", value=st.session_state["__opt_carry_md_across_codes"])

# ---------- Notebook UI ----------
def _new_cell(cell_type="markdown", content="", meta=None) -> Cell:
    return {"id": str(uuid.uuid4()), "type": cell_type, "content": content, "meta": (meta or {})}

def render_notebook(steps_file: Path, provider: str):
    env = _get_env()
    module_key = _current_module_key(env)

    if "cells" not in st.session_state:
        st.session_state["cells"] = _load_cells(steps_file, module_key)
    cells: List[Cell] = st.session_state["cells"]

    def persist():
        _save_cells(cells, steps_file, module_key)

    autosave = st.session_state.get("__opt_autosave", True)
    auto_code = st.session_state.get("__opt_auto_code_after_query", True)

    # Discover available apps and set page-level default runtime (venv)
    apps_list: List[Path] = _list_available_apps(env)
    app_labels = ["Use AGILAB environment"] + [p.name for p in apps_list]
    app_paths = [""] + [str(p.resolve()) for p in apps_list]
    label_to_path = dict(zip(app_labels, app_paths))
    st.session_state.setdefault("default_app_runtime", app_paths[0])


    for i, cell in enumerate(list(cells)):
        cid = cell.get("id") or f"cell_{i}"
        ctype = cell.get("type", "query")

        # --- compute app choices once (used by code cells) ---
        is_code = (ctype == "code")
        current_env_path = _norm(cell.setdefault("meta", {}).get("env", "")) if is_code else ""
        try:
            env_idx = app_paths.index(current_env_path) if current_env_path in app_paths else 0
        except ValueError:
            env_idx = 0


        with st.container(border=True):
            # --- toolbar ---
            # If this is a CODE cell, add a 6th column for the App selector (aligned with buttons)
            if is_code:
                cols = st.columns([0.40, 0.08, 0.08, 0.08, 0.08, 0.06, 0.22])
            else:
                cols = st.columns([0.62, 0.08, 0.08, 0.08, 0.08, 0.06])

            with cols[0]:
                st.caption(f"{str(ctype).upper()} — {cid[:8]}")

            with cols[1]:
                if st.button("↑", key=f"up_{cid}_{i}") and i > 0:
                    cells[i - 1], cells[i] = cells[i], cells[i - 1]
                    persist();
                    st.rerun()

            with cols[2]:
                if st.button("↓", key=f"down_{cid}_{i}") and i < len(cells) - 1:
                    cells[i + 1], cells[i] = cells[i], cells[i + 1]
                    persist();
                    st.rerun()

            with cols[3]:
                if st.button("+", key=f"add_{cid}_{i}"):
                    cells.insert(i + 1, _new_cell("query", "", meta={"provider": provider}))
                    persist();
                    st.rerun()

            with cols[4]:
                if st.button("⌫", key=f"del_{cid}_{i}"):
                    cells.pop(i)
                    persist();
                    st.rerun()

            # --- App selector IN the toolbar (only for code cells) ---
            if is_code:
                with cols[5]:
                    chosen_label = st.selectbox(
                        "Active app (venv)",
                        options=app_labels or ["(no apps)"],
                        index=env_idx if app_labels else 0,
                        key=f"envsel_toolbar_{cid}_{i}",
                    )
                    # persist per-cell venv path
                    cell["meta"]["env"] = label_to_path.get(chosen_label, "") if app_labels else ""

            # --- body follows as usual...
            if ctype == "markdown":
                txt = st.text_area("Markdown", value=cell.get("content", ""), key=f"md_{cid}_{i}",
                                   height=120, label_visibility="collapsed")
                if txt != cell.get("content", ""):
                    cell["content"] = txt
                    if autosave: persist()
                st.markdown(cell["content"])

            elif ctype == "query":
                prompt = st.text_area("Prompt", value=cell.get("content", ""), key=f"q_{cid}_{i}",
                                      height=120, label_visibility="collapsed")
                if prompt != cell.get("content", ""):
                    cell["content"] = prompt
                    if autosave: persist()
                run_col, _ = st.columns([0.2, 0.8])
                with run_col:
                    if st.button("Run", key=f"runq_{cid}_{i}"):
                        ctx = ""
                        for j in range(i - 1, -1, -1):
                            if cells[j]["type"] == "markdown":
                                ctx = cells[j]["content"];
                                break
                        resp = _run_query(prompt, provider, ctx)
                        text = (resp.get("text", "") if isinstance(resp, dict) else _s(resp)).strip()
                        if text:
                            cells.insert(i + 1, _new_cell("output", text))
                            if auto_code and _looks_like_code(text):
                                guess_lang = "python" if ("def " in text or "import " in text) else "text"
                                cells.insert(i + 2, _new_cell("code", text, meta={"lang": guess_lang}))
                        persist();
                        st.rerun()

            elif ctype == "code":
                meta = cell["meta"]
                lang = meta.get("lang", "python")

                # NOTE: remove any OLD per-cell selector from the body if you had one

                # Editor + Run (uses per-cell env chosen in the toolbar)
                if code_editor is None:
                    st.info("Tip: `pip install streamlit-code-editor` for a full code editor.")
                    code_txt = st.text_area("Code", value=cell.get("content", ""), key=f"code_{cid}_{i}",
                                            height=200, label_visibility="collapsed")
                    if code_txt != cell.get("content", ""):
                        cell["content"] = code_txt
                        if autosave: persist()
                    run_col, _ = st.columns([0.2, 0.8])
                    with run_col:
                        if st.button("Run", key=f"runc_{cid}_{i}"):
                            venv_path = _norm(meta.get("env", ""))  # <-- uses toolbar selection
                            out = _run_code(cell["content"], venv_path)
                            cells.insert(i + 1, _new_cell("output", out or "(no output)"))
                            persist();
                            st.rerun()
                else:
                    result = code_editor(
                        code=cell.get("content", ""),
                        lang=lang,
                        theme="default",
                        height=[300, 600],
                        buttons=["run", "save", "clear"],
                        key=f"code_editor_{cid}_{i}",
                    )
                    new_text = result.get("text", "")
                    if new_text != cell.get("content", ""):
                        cell["content"] = new_text
                        if autosave: persist()
                    if result.get("type") == "run":
                        venv_path = _norm(meta.get("env", ""))  # <-- uses toolbar selection
                        out = _run_code(cell["content"], venv_path)
                        cells.insert(i + 1, _new_cell("output", out or "(no output)"))
                        persist();
                        st.rerun()

            elif ctype == "output":
                st.markdown(cell.get("content", "") or "_(empty output)_")

    st.divider()
    add1, add2, add3, add4, save_col = st.columns([0.2,0.2,0.2,0.2,0.2])
    with add1:
        if st.button("➕ Markdown"): cells.append(_new_cell("markdown","")); persist(); st.rerun()
    with add2:
        if st.button("➕ Query"): cells.append(_new_cell("query","", meta={"provider": st.session_state.get("lab_llm_provider","openai")})); persist(); st.rerun()
    with add3:
        if st.button("➕ Code"): cells.append(_new_cell("code","", meta={"lang":"python"})); persist(); st.rerun()
    with add4:
        if st.button("➕ Output"): cells.append(_new_cell("output","")); persist(); st.rerun()
    with save_col:
        if st.button("💾 Save"): persist(); st.success("Saved")

# ---------- Page & Main ----------
def page() -> None:
    env = st.session_state['env']

    # Session init (single lines, no wraps)
    lab_dir_default = Path(env.AGILAB_EXPORT_ABS) / env.target
    st.session_state.setdefault("lab_dir", str(lab_dir_default))
    st.session_state.setdefault("Agi_export_abs", str(Path(env.AGILAB_EXPORT_ABS)))
    st.session_state.setdefault("steps_file", Path(env.active_app) / STEPS_FILE_NAME)
    st.session_state.setdefault("index_page", Path(st.session_state["lab_dir"]))
    df_dir_def = Path(env.AGILAB_EXPORT_ABS) / env.target
    st.session_state.setdefault("df_file_out", str(df_dir_def / ("lab_" + DEFAULT_DF.replace(".csv", "_out.csv"))))
    st.session_state.setdefault("df_file", str(DEFAULT_DF if DEFAULT_DF in str(df_dir_def) else df_dir_def / DEFAULT_DF))

    # Sidebar & notebook
    sidebar_controls()
    provider = st.session_state.get("lab_llm_provider", env.envars.get("LAB_LLM_PROVIDER", "openai"))
    steps_file = Path(st.session_state["steps_file"])
    steps_file.parent.mkdir(parents=True, exist_ok=True)
    render_notebook(steps_file, provider)

def main() -> None:

    if 'env' not in st.session_state or not getattr(st.session_state["env"], "init_done", True):
        # Redirect back to the landing page and rerun immediately
        page_module = importlib.import_module("AGILAB")
        page_module.main()
        st.rerun()
    else:
        env = st.session_state['env']
        st.session_state['_env'] = env

    st.set_page_config(layout="wide", menu_items=get_about_content())
    inject_theme(env.st_resources)
    render_logo()

    # 4) render page
    page()

# Always run main
main()