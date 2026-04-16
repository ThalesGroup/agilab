# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

import argparse
from collections import Counter
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.colors import qualitative as plotly_qualitative
from plotly.subplots import make_subplots
import streamlit as st
import tomllib

try:
    import tomli_w as _toml_writer  # type: ignore[import-not-found]

    def _dump_toml(data: dict, handle) -> None:
        _toml_writer.dump(data, handle)

except ModuleNotFoundError:  # pragma: no cover
    try:
        from tomlkit import dumps as _tomlkit_dumps

        def _dump_toml(data: dict, handle) -> None:
            handle.write(_tomlkit_dumps(data).encode("utf-8"))

    except Exception as _toml_exc:  # pragma: no cover
        _tomlkit_dumps = None  # type: ignore[assignment]

        def _dump_toml(data: dict, handle) -> None:
            raise RuntimeError(
                "Writing settings requires the 'tomli-w' or 'tomlkit' package."
            ) from _toml_exc


PAGE_KEY = "view_training_analysis"
RUN_ROOTS_KEY = f"{PAGE_KEY}_run_roots"
TRAINERS_KEY = f"{PAGE_KEY}_trainers"
TAGS_KEY = f"{PAGE_KEY}_tags"
X_AXIS_KEY = f"{PAGE_KEY}_x_axis"


def _ensure_repo_on_path() -> None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "agilab"
        if candidate.is_dir():
            src_root = candidate.parent
            repo_root = src_root.parent
            for entry in (str(src_root), str(repo_root)):
                if entry not in sys.path:
                    sys.path.insert(0, entry)
            break


_ensure_repo_on_path()

from agi_env import AgiEnv
from agi_env.pagelib import render_logo


def _resolve_active_app() -> Path:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--active-app", dest="active_app", type=str, required=True)
    args, _ = parser.parse_known_args()
    active_app_path = Path(args.active_app).expanduser().resolve()
    if not active_app_path.exists():
        st.error(f"Provided --active-app path not found: {active_app_path}")
        st.stop()
    return active_app_path


def _ensure_app_settings_loaded(env: AgiEnv) -> None:
    if "app_settings" in st.session_state:
        return
    path = Path(env.app_settings_file)
    if path.exists():
        try:
            with path.open("rb") as handle:
                st.session_state["app_settings"] = tomllib.load(handle)
                return
        except Exception:
            pass
    st.session_state["app_settings"] = {}


def _persist_app_settings(env: AgiEnv) -> None:
    settings = st.session_state.get("app_settings")
    if not isinstance(settings, dict):
        return
    path = Path(env.app_settings_file)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            _dump_toml(settings, handle)
    except Exception:
        pass


def _get_page_state() -> dict[str, Any]:
    app_settings = st.session_state.setdefault("app_settings", {})
    page_settings = app_settings.get(PAGE_KEY)
    if not isinstance(page_settings, dict):
        page_settings = {}
        app_settings[PAGE_KEY] = page_settings
    return page_settings


def _get_page_defaults() -> dict[str, Any]:
    app_settings = st.session_state.setdefault("app_settings", {})
    pages = app_settings.get("pages")
    if not isinstance(pages, dict):
        return {}
    page_settings = pages.get(PAGE_KEY)
    return page_settings if isinstance(page_settings, dict) else {}


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = value.replace(";", ",").replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = [str(item) for item in value]
    else:
        raw_items = [str(value)]
    items: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        items.append(cleaned)
    return items


def _get_first_nonempty_setting(sources: list[dict[str, Any]], *keys: str) -> str:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _resolve_base_path(
    env: AgiEnv,
    base_choice: str,
    custom_base: str,
) -> Path:
    if base_choice == "AGI_SHARE_DIR":
        return Path(env.share_root_path())
    if base_choice == "AGILAB_EXPORT":
        path = Path(env.AGILAB_EXPORT_ABS)
        path.mkdir(parents=True, exist_ok=True)
        return path
    return Path(custom_base).expanduser()


def _event_files(base: Path) -> list[Path]:
    if not base.exists():
        return []
    return sorted(
        [path.resolve() for path in base.rglob("events.out.tfevents.*") if path.is_file()],
        key=lambda path: path.as_posix(),
    )


def _discover_tensorboard_roots(data_root: Path) -> list[Path]:
    if not data_root.exists():
        return []
    trainer_roots: set[Path] = set()
    tensorboard_dirs = []
    if data_root.is_dir() and data_root.name == "tensorboard":
        tensorboard_dirs.append(data_root.resolve())
    tensorboard_dirs.extend(path.resolve() for path in data_root.rglob("tensorboard") if path.is_dir())
    for tensorboard_dir in tensorboard_dirs:
        if _event_files(tensorboard_dir):
            trainer_roots.add(tensorboard_dir.parent.resolve())
    return sorted(trainer_roots, key=lambda path: path.as_posix())


def _discover_run_directories(tensorboard_dir: Path) -> list[Path]:
    if not tensorboard_dir.exists():
        return []
    run_dirs = {path.parent.resolve() for path in _event_files(tensorboard_dir)}
    return sorted(run_dirs, key=lambda path: path.as_posix())


def _relative_parts(path: Path, base: Path) -> tuple[str, ...]:
    relative = _relative_label(path, base)
    parts = tuple(part for part in relative.split("/") if part and part != ".")
    return parts or (path.name,)


def _shared_trainer_prefix_length(parts_by_path: dict[Path, tuple[str, ...]]) -> int:
    if not parts_by_path:
        return 0

    paths = sorted(parts_by_path, key=lambda path: path.as_posix())
    parts_list = [parts_by_path[path] for path in paths]
    shortest = min(len(parts) for parts in parts_list)
    shared_length = 0
    while shared_length < shortest:
        segment = parts_list[0][shared_length]
        if any(parts[shared_length] != segment for parts in parts_list[1:]):
            break
        shared_length += 1

    # Keep at least two path levels when possible so the retained prefix stays at the
    # experiment-group level instead of collapsing to the trainer folder itself.
    max_shared_length = max(shortest - 2, 0)
    return min(shared_length, max_shared_length)


def _initial_trainer_group_labels(
    trainer_roots: list[Path],
    data_root: Path,
) -> dict[Path, str]:
    if not trainer_roots:
        return {}

    parts_by_path = {
        trainer_root: _relative_parts(trainer_root, data_root)
        for trainer_root in sorted(trainer_roots, key=lambda path: path.as_posix())
    }
    shared_prefix_length = _shared_trainer_prefix_length(parts_by_path)
    return {
        trainer_root: parts_by_path[trainer_root][shared_prefix_length]
        for trainer_root in parts_by_path
    }


def _discover_run_labels(
    trainer_roots: list[Path],
    data_root: Path,
) -> dict[str, Path]:
    include_trainer_prefix = len(trainer_roots) > 1
    trainer_labels = _initial_trainer_group_labels(trainer_roots, data_root)
    run_entries: list[tuple[Path, Path, str]] = []
    for trainer_root in sorted(trainer_roots, key=lambda path: path.as_posix()):
        tensorboard_dir = trainer_root / "tensorboard"
        for run_dir in _discover_run_directories(tensorboard_dir):
            run_label = _relative_label(run_dir, tensorboard_dir)
            run_entries.append((trainer_root, run_dir, run_label))

    if not include_trainer_prefix:
        return {run_label: run_dir for _, run_dir, run_label in run_entries}

    primary_counts = Counter(
        f"{trainer_labels.get(trainer_root, trainer_root.name)}/{run_label}"
        for trainer_root, _, run_label in run_entries
    )
    secondary_counts = Counter(
        f"{trainer_labels.get(trainer_root, trainer_root.name)}/{trainer_root.name}/{run_label}"
        for trainer_root, _, run_label in run_entries
    )

    labeled_runs: dict[str, Path] = {}
    for trainer_root, run_dir, run_label in run_entries:
        trainer_label = trainer_labels.get(trainer_root, trainer_root.name)
        primary_label = f"{trainer_label}/{run_label}"
        if primary_counts[primary_label] == 1:
            display_label = primary_label
        else:
            secondary_label = f"{trainer_label}/{trainer_root.name}/{run_label}"
            if secondary_counts[secondary_label] == 1:
                display_label = secondary_label
            else:
                display_label = f"{_relative_label(trainer_root, data_root)}/{run_label}"
        labeled_runs[display_label] = run_dir
    return labeled_runs


def _relative_label(path: Path, base: Path) -> str:
    try:
        relative = path.resolve().relative_to(base.resolve())
        return "." if not relative.parts else relative.as_posix()
    except Exception:
        return path.name


def _grid_shape(count: int) -> tuple[int, int]:
    if count <= 1:
        return 1, 1
    cols = min(3, count)
    rows = math.ceil(count / cols)
    return rows, cols


def _default_selected_tags(available_tags: list[str], saved_tags: list[str]) -> list[str]:
    if saved_tags:
        selected = [tag for tag in saved_tags if tag in available_tags]
        if selected:
            return selected
    return available_tags[: min(4, len(available_tags))]


def _load_event_accumulator():
    try:
        from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError(
            "TensorBoard support is not installed for this page environment. "
            "Install the page dependencies so 'tensorboard' is available."
        ) from exc
    return EventAccumulator


@st.cache_data(show_spinner=False)
def _load_scalar_frame(run_dir_str: str) -> pd.DataFrame:
    EventAccumulator = _load_event_accumulator()
    accumulator = EventAccumulator(run_dir_str)
    accumulator.Reload()

    rows: list[dict[str, Any]] = []
    for tag in sorted(accumulator.Tags().get("scalars", [])):
        for event in accumulator.Scalars(tag):
            rows.append(
                {
                    "tag": tag,
                    "step": int(event.step),
                    "wall_time": float(event.wall_time),
                    "value": float(event.value),
                }
            )

    df = pd.DataFrame(rows, columns=["tag", "step", "wall_time", "value"])
    if df.empty:
        return df

    df = df.sort_values(["tag", "step", "wall_time"], kind="stable").reset_index(drop=True)
    df["relative_time_s"] = df["wall_time"] - float(df["wall_time"].min())
    df["timestamp"] = pd.to_datetime(df["wall_time"], unit="s", utc=True).dt.tz_convert(None)
    return df


def _build_scalar_figure(
    scalar_df: pd.DataFrame,
    selected_tags: list[str],
    x_column: str,
) -> go.Figure:
    rows, cols = _grid_shape(len(selected_tags))
    fig = make_subplots(
        rows=rows,
        cols=cols,
        subplot_titles=selected_tags,
        vertical_spacing=0.1 if rows > 1 else 0.14,
    )

    x_title = {
        "step": "step",
        "relative_time_s": "relative time (s)",
        "timestamp": "wall time",
    }.get(x_column, x_column)
    run_labels = sorted(scalar_df["run_label"].dropna().unique().tolist())
    palette = (
        plotly_qualitative.Safe
        + plotly_qualitative.Plotly
        + plotly_qualitative.D3
    )
    run_colors = {
        run_label: palette[index % len(palette)]
        for index, run_label in enumerate(run_labels)
    }

    for index, tag in enumerate(selected_tags):
        row = index // cols + 1
        col = index % cols + 1
        tag_df = scalar_df[scalar_df["tag"] == tag]
        for run_index, run_label in enumerate(sorted(tag_df["run_label"].dropna().unique().tolist())):
            run_df = tag_df[tag_df["run_label"] == run_label]
            if run_df.empty:  # pragma: no cover - defensive guard; run labels come from tag_df itself
                continue
            fig.add_trace(
                go.Scatter(
                    x=run_df[x_column],
                    y=run_df["value"],
                    mode="lines+markers",
                    name=run_label,
                    legendgroup=run_label,
                    showlegend=index == 0,
                    marker={"size": 5},
                    line={"color": run_colors[run_label], "width": 2},
                    marker_color=run_colors[run_label],
                ),
                row=row,
                col=col,
            )
        fig.update_xaxes(title_text=x_title, row=row, col=col)
        fig.update_yaxes(title_text="value", row=row, col=col)

    fig.update_layout(
        height=max(360, 320 * rows),
        margin={"l": 20, "r": 20, "t": 50, "b": 20},
    )
    return fig


def main() -> None:
    st.set_page_config(layout="wide")

    if "env" not in st.session_state:
        active_app_path = _resolve_active_app()
        env = AgiEnv(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)
        env.init_done = True
        st.session_state["env"] = env
    else:
        env = st.session_state["env"]

    _ensure_app_settings_loaded(env)

    render_logo("Training Analysis")
    st.title("Training analysis")
    st.caption(
        "Browse TensorBoard scalar logs from one or more trainer outputs and plot the metrics you need."
    )

    page_state = _get_page_state()
    page_defaults = _get_page_defaults()
    setting_sources = [page_state, page_defaults]

    base_options = ["AGI_SHARE_DIR", "AGILAB_EXPORT", "Custom"]
    base_seed = _get_first_nonempty_setting(setting_sources, "base_dir_choice", "dataset_base_choice")
    if base_seed not in base_options:
        base_seed = "AGI_SHARE_DIR"
    custom_seed = _get_first_nonempty_setting(setting_sources, "input_datadir", "dataset_custom_base")
    rel_seed = _get_first_nonempty_setting(setting_sources, "datadir_rel", "dataset_subpath")

    if "base_dir_choice" not in st.session_state:
        st.session_state["base_dir_choice"] = base_seed
    if "input_datadir" not in st.session_state:
        st.session_state["input_datadir"] = custom_seed
    if "datadir_rel" not in st.session_state:
        st.session_state["datadir_rel"] = rel_seed
    if X_AXIS_KEY not in st.session_state:
        st.session_state[X_AXIS_KEY] = page_state.get("x_axis") or "step"

    base_choice = st.sidebar.radio("Base directory", base_options, key="base_dir_choice")
    if base_choice == "Custom":
        st.sidebar.text_input("Custom data directory", key="input_datadir")

    st.sidebar.text_input("Relative data subpath", key="datadir_rel")

    base_path = _resolve_base_path(env, base_choice, st.session_state.get("input_datadir", ""))
    data_root = (base_path / st.session_state.get("datadir_rel", "")).resolve()
    st.sidebar.caption(f"Resolved data root: `{data_root}`")

    if not data_root.exists():
        st.warning(f"Data root does not exist yet: {data_root}")
        page_state.update(
            {
                "base_dir_choice": base_choice,
                "input_datadir": st.session_state.get("input_datadir", ""),
                "datadir_rel": st.session_state.get("datadir_rel", ""),
                "x_axis": st.session_state.get(X_AXIS_KEY, "step"),
            }
        )
        _persist_app_settings(env)
        st.stop()

    trainer_roots = _discover_tensorboard_roots(data_root)
    if not trainer_roots:
        st.warning(f"No TensorBoard trainers found under {data_root}.")
        page_state.update(
            {
                "base_dir_choice": base_choice,
                "input_datadir": st.session_state.get("input_datadir", ""),
                "datadir_rel": st.session_state.get("datadir_rel", ""),
                "x_axis": st.session_state.get(X_AXIS_KEY, "step"),
            }
        )
        _persist_app_settings(env)
        st.stop()

    trainer_labels = {_relative_label(path, data_root): path for path in trainer_roots}
    trainer_options = list(trainer_labels.keys())
    saved_trainer_labels = _coerce_str_list(page_state.get("trainer_rels"))
    if not saved_trainer_labels:
        saved_trainer_labels = _coerce_str_list(page_state.get("trainer_rel"))
    default_trainer_labels = [label for label in saved_trainer_labels if label in trainer_options]
    if not default_trainer_labels and trainer_options:
        default_trainer_labels = [trainer_options[0]]
    selected_trainer_labels = st.sidebar.multiselect(
        "Trainer outputs",
        options=trainer_options,
        default=default_trainer_labels,
        key=TRAINERS_KEY,
    )
    selected_trainers = [trainer_labels[label] for label in selected_trainer_labels]

    if not selected_trainers:
        st.info("Select at least one Trainer output in the sidebar.")
        st.stop()

    run_labels = _discover_run_labels(selected_trainers, data_root)
    if not run_labels:
        selected_trainers_display = ", ".join(selected_trainer_labels)
        st.warning(
            "No TensorBoard run folders found under the selected trainer outputs"
            + (f": {selected_trainers_display}." if selected_trainers_display else ".")
        )
        st.stop()

    run_options = list(run_labels.keys())
    saved_run_labels = _coerce_str_list(page_state.get("run_rels"))
    if not saved_run_labels:
        saved_run_labels = _coerce_str_list(page_state.get("run_rel"))
    default_run_labels = [label for label in saved_run_labels if label in run_options]
    if not default_run_labels and run_options:
        default_run_labels = [run_options[-1]]
    selected_run_labels = st.sidebar.multiselect(
        "TensorBoard run folders",
        options=run_options,
        default=default_run_labels,
        key=RUN_ROOTS_KEY,
    )
    selected_run_dirs = [run_labels[label] for label in selected_run_labels]

    x_axis_option = st.sidebar.selectbox(
        "X axis",
        options=["step", "relative_time_s", "timestamp"],
        format_func=lambda value: {
            "step": "step",
            "relative_time_s": "relative time (s)",
            "timestamp": "wall time",
        }[value],
        key=X_AXIS_KEY,
    )

    if not selected_run_dirs:
        st.info("Select at least one TensorBoard run folder in the sidebar.")
        st.stop()

    try:
        run_frames = []
        for run_label, run_dir in zip(selected_run_labels, selected_run_dirs, strict=False):
            run_df = _load_scalar_frame(str(run_dir))
            if run_df.empty:
                continue
            run_df = run_df.copy()
            run_df["run_label"] = run_label
            run_frames.append(run_df)
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

    if not run_frames:
        st.warning("No scalar metrics were found in the selected run folders.")
        st.stop()

    scalar_df = pd.concat(run_frames, ignore_index=True)
    available_tags = sorted(scalar_df["tag"].dropna().unique().tolist())
    selected_tags = st.sidebar.multiselect(
        "TensorBoard variables",
        options=available_tags,
        default=_default_selected_tags(available_tags, _coerce_str_list(page_state.get("selected_tags"))),
        key=TAGS_KEY,
    )

    if not selected_tags:
        st.info("Select at least one TensorBoard variable in the sidebar to draw the charts.")
    else:
        st.subheader("Scalar plots")
        st.plotly_chart(
            _build_scalar_figure(scalar_df, selected_tags, x_axis_option),
            width="stretch",
        )

    page_state.update(
        {
            "base_dir_choice": base_choice,
            "input_datadir": st.session_state.get("input_datadir", ""),
            "datadir_rel": st.session_state.get("datadir_rel", ""),
            "trainer_rel": selected_trainer_labels[0] if selected_trainer_labels else "",
            "trainer_rels": selected_trainer_labels,
            "run_rel": selected_run_labels[0] if selected_run_labels else "",
            "run_rels": selected_run_labels,
            "selected_tags": selected_tags,
            "x_axis": x_axis_option,
        }
    )
    _persist_app_settings(env)


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    main()
