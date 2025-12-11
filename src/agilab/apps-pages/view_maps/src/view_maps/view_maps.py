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

import argparse
import math
import os
from pathlib import Path
import sys

import pandas as pd
from pandas.api.types import is_integer_dtype, is_numeric_dtype
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import tomllib as _toml

try:
    import tomli_w as _toml_writer  # type: ignore[import-not-found]

    def _dump_toml_payload(data: dict, handle) -> None:
        _toml_writer.dump(data, handle)

except ModuleNotFoundError:  # pragma: no cover - fallback for lightweight envs
    try:
        from tomlkit import dumps as _tomlkit_dumps

        def _dump_toml_payload(data: dict, handle) -> None:
            handle.write(_tomlkit_dumps(data).encode("utf-8"))

    except Exception as _toml_exc:

        def _dump_toml_payload(data: dict, handle) -> None:
            raise RuntimeError(
                "Writing settings requires the 'tomli-w' or 'tomlkit' package"
            ) from _toml_exc


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

def _default_app() -> Path | None:
    apps_path = Path(__file__).resolve().parents[4] / "apps"
    if not apps_path.exists():
        return None
    for candidate in sorted(apps_path.iterdir()):
        if (
            candidate.is_dir()
            and candidate.name.endswith("_project")
            and not candidate.name.startswith(".")
        ):
            return candidate
    return None


from agi_env import AgiEnv
from agi_env.pagelib import find_files, load_df, update_datadir, initialize_csv_files

var = ["discrete", "continuous", "lat", "long"]
var_default = [0, None]

st.title(":world_map: Cartography Visualisation")


def continuous():
    """Set coltype to 'continuous'."""
    st.session_state["coltype"] = "continuous"


def discrete():
    """Set coltype to 'discrete'."""
    st.session_state["coltype"] = "discrete"

  # Default to 'discrete'


def downsample_df_deterministic(df: pd.DataFrame, ratio: int) -> pd.DataFrame:
    """
    Return a new DataFrame containing every `ratio`-th row from the original df.

    Parameters
    ----------
    df : pd.DataFrame
        The original DataFrame to down-sample.
    ratio : int
        Keep one row every `ratio` rows. E.g. ratio=20 → rows 0, 20, 40, …

    Returns
    -------
    pd.DataFrame
        The down-sampled DataFrame, re-indexed from 0.
    """
    if ratio <= 0:
        raise ValueError("`ratio` must be a positive integer.")
    # Ensure a clean integer index before slicing
    df_reset = df.reset_index(drop=True)
    # Take every ratio-th row
    sampled = df_reset.iloc[::ratio].copy()
    # Reset index for the result
    return sampled.reset_index(drop=True)


def _compute_zoom_from_span(span_deg: float) -> float:
    """Approximate a mapbox zoom level based on the largest lat/lon span."""
    thresholds = [
        (160, 1),
        (80, 2),
        (40, 3),
        (20, 4),
        (10, 5),
        (5, 6),
        (2.5, 7),
        (1.2, 8),
        (0.6, 9),
        (0.3, 10),
        (0.15, 11),
        (0.075, 12),
        (0.035, 13),
        (0.018, 14),
    ]
    for threshold, zoom in thresholds:
        if span_deg > threshold:
            return zoom
    return 15


def _compute_viewport(df: pd.DataFrame, lat_col: str, lon_col: str) -> dict[str, float] | None:
    """Return center/zoom settings that fit the current dataset."""
    try:
        latitudes = pd.to_numeric(df[lat_col], errors="coerce").dropna()
        longitudes = pd.to_numeric(df[lon_col], errors="coerce").dropna()
    except Exception:
        return None
    if latitudes.empty or longitudes.empty:
        return None
    lat_min, lat_max = latitudes.min(), latitudes.max()
    lon_min, lon_max = longitudes.min(), longitudes.max()
    center_lat = float((lat_min + lat_max) / 2)
    center_lon = float((lon_min + lon_max) / 2)
    span_lat = abs(lat_max - lat_min)
    span_lon = abs(lon_max - lon_min)
    span = max(span_lat, span_lon)
    zoom = _compute_zoom_from_span(span if span > 0 else 0.01)
    return {"center_lat": center_lat, "center_lon": center_lon, "default_zoom": zoom}


def _load_map_defaults(env: AgiEnv) -> dict[str, float]:
    """Read custom map settings from app_settings.toml when available."""

    try:
        with open(env.app_settings_file, "rb") as fh:
            data = _toml.load(fh)
    except FileNotFoundError:
        data = {}
    map_cfg = data.get("ui", {}).get(
        "map",
        {"center_lat": 0.0, "center_lon": 0.0, "default_zoom": 2.5},
    )
    return {
        "center_lat": float(map_cfg.get("center_lat", 0.0)),
        "center_lon": float(map_cfg.get("center_lon", 0.0)),
        "default_zoom": float(map_cfg.get("default_zoom", 2.5)),
    }


def _load_view_maps_settings(env: AgiEnv) -> tuple[dict, dict]:
    """Return the full TOML payload and the view_maps subsection."""
    try:
        with open(env.app_settings_file, "rb") as fh:
            data = _toml.load(fh)
    except FileNotFoundError:
        data = {}
    except Exception:
        data = {}
    view_section = data.get("view_maps")
    if not isinstance(view_section, dict):
        view_section = {}
    return data, view_section


def _persist_view_maps_settings(env: AgiEnv, base_settings: dict, view_settings: dict) -> dict:
    """Write the updated view_maps settings back to disk."""
    payload = dict(base_settings) if isinstance(base_settings, dict) else {}
    payload["view_maps"] = view_settings
    try:
        with open(env.app_settings_file, "wb") as fh:
            _dump_toml_payload(payload, fh)
    except Exception:
        pass
    return payload


def page(env):
    """
    Page function for displaying and interacting with data in a Streamlit app.

    This function sets up the page layout and functionality for displaying and interacting with data in a Streamlit app.

    It handles the following key tasks:
    - Setting up default values for session state variables related to the project, help path, and available projects.
    - Checking and validating the data directory path, and displaying appropriate messages if it is invalid or not found.
    - Loading and displaying the selected data file in a DataFrame.
    - Allowing users to select columns for visualizations and customization options like color sequence and scale.
    - Generating and displaying interactive scatter maps based on selected columns for latitude, longitude, and coloring.

    No specific Args are passed to this function as it directly interacts with and manipulates the page layout and user inputs in a Streamlit app.

    Returns:
        None

    Raises:
        None
    """

    if "project" not in st.session_state:
        st.session_state["project"] = env.target

    if "projects" not in st.session_state:
        st.session_state["projects"] = env.projects

    full_settings, view_settings = _load_view_maps_settings(env)
    for k in ("df_files_selected", "discrete", "continuous", "lat", "long", "coltype"):
        if k in view_settings and k not in st.session_state:
            st.session_state[k] = view_settings[k]

    map_defaults_key = f"_view_maps_map_defaults_{env.app}"

    # Resolve the data directory for the currently selected app
    default_datadir = Path(env.AGILAB_EXPORT_ABS) / env.target
    last_target_key = "_view_maps_last_target"
    last_target = st.session_state.get(last_target_key)

    current = st.session_state.get("datadir")
    if (
        last_target != env.target
        or current is None
        or str(current).strip() == ""
    ):
        current = str(view_settings.get("datadir") or default_datadir)
    st.session_state["datadir"] = str(current)

    st.session_state["datadir_str"] = st.session_state["datadir"]
    st.session_state[last_target_key] = env.target
    if (
        map_defaults_key not in st.session_state
        or last_target != env.target
    ):
        st.session_state[map_defaults_key] = _load_map_defaults(env)
    datadir = Path(st.session_state["datadir"])
    datadir_changed = st.session_state.get("_view_maps_last_datadir") != str(datadir)
    st.session_state["_view_maps_last_datadir"] = str(datadir)
    if view_settings.get("datadir") != st.session_state["datadir"]:
        view_settings["datadir"] = st.session_state["datadir"]
        full_settings = _persist_view_maps_settings(env, full_settings, view_settings)
    # Data directory input
    st.sidebar.text_input(
        "Data Directory",
        value=st.session_state["datadir"],
        key="input_datadir",
        on_change=update_datadir,
        args=("datadir", "input_datadir"),
    )

    if not datadir.exists() or not datadir.is_dir():
        st.sidebar.error("Directory not found.")
        st.warning("A valid data directory is required to proceed.")
        return  # Stop further processing

    # Find CSV files in the data directory
    dataset_key = "dataset_files"
    legacy_key = "csv_files"
    if dataset_key not in st.session_state and legacy_key in st.session_state:
        st.session_state[dataset_key] = st.session_state.pop(legacy_key)

    datadir_exts = (".csv", ".parquet", ".json")
    dataset_files: list[Path] = []
    for ext in datadir_exts:
        try:
            dataset_files.extend(find_files(st.session_state["datadir"], ext=ext))
        except NotADirectoryError as exc:
            st.warning(str(exc))
            dataset_files = []
            break
    # Filter out hidden paths (any component starting with ".")
    visible_files: list[Path] = []
    for f in dataset_files:
        try:
            parts = f.relative_to(datadir).parts
        except Exception:
            parts = f.parts
        if any(part.startswith(".") for part in parts):
            continue
        visible_files.append(f)
    dataset_files = visible_files

    st.session_state[dataset_key] = dataset_files
    if not st.session_state[dataset_key]:
        st.warning(
            f"No dataset found in {datadir}. "
            "Use the EXECUTE → EXPORT workflow to materialize CSV/Parquet/JSON outputs first."
        )
        st.stop()  # Stop further processing

    # Prepare list of CSV files relative to the data directory
    dataset_files_rel = sorted(
        {
            Path(file).relative_to(datadir).as_posix()
            for file in st.session_state[dataset_key]
        }
    )

    # Prefer the consolidated export file when present (matches flight app UX)
    priority_files = [
        candidate
        for candidate in dataset_files_rel
        if Path(candidate).name.lower() in {"export.csv", "export.parquet", "export.json"}
    ]
    settings_files = view_settings.get("df_files_selected") or []
    if settings_files and all(item in dataset_files_rel for item in settings_files):
        default_selection = settings_files
    else:
        default_selection = [priority_files[0]] if priority_files else (dataset_files_rel[:1] if dataset_files_rel else [])

    if (
        "df_files_selected" not in st.session_state
        or not st.session_state["df_files_selected"]
        or any(item not in dataset_files_rel for item in st.session_state["df_files_selected"])
    ):
        st.session_state["df_files_selected"] = default_selection

    current_selection = st.session_state.get("df_files_selected")
    if datadir_changed:
        st.session_state["df_files_selected"] = default_selection
        current_selection = default_selection
    if (
        current_selection is None
        or any(item not in dataset_files_rel for item in current_selection)
    ):
        st.session_state["df_files_selected"] = default_selection
    elif not current_selection and default_selection:
        st.session_state["df_files_selected"] = default_selection
    st.sidebar.multiselect(
        label="DataFrames",
        options=dataset_files_rel,
        key="df_files_selected",
    )

    selected_files = st.session_state.get("df_files_selected", [])
    if not selected_files:
        st.warning("Please select at least one dataset to proceed.")
        return

    # Load and concatenate selected DataFrames
    dataframes = []
    for rel_path in selected_files:
        df_file_abs = datadir / rel_path
        cache_buster = None
        try:
            cache_buster = df_file_abs.stat().st_mtime_ns
        except FileNotFoundError:
            cache_buster = None
        try:
            df_loaded = load_df(df_file_abs, with_index=True, cache_buster=cache_buster)
        except Exception as e:
            st.error(f"Error loading data from {rel_path}: {e}")
            continue
        df_loaded = df_loaded.copy()
        df_loaded["__dataset__"] = rel_path
        dataframes.append(df_loaded)

    if not dataframes:
        st.warning("The selected data files could not be loaded. Please select valid files.")
        return

    try:
        combined_df = pd.concat(dataframes, ignore_index=True)
    except Exception as e:
        st.error(f"Error concatenating datasets: {e}")
        return

    st.session_state["loaded_df"] = combined_df

    # Check if data is loaded and valid
    if (
            "loaded_df" not in st.session_state
            or not isinstance(st.session_state.loaded_df, pd.DataFrame)
            or not st.session_state.loaded_df.shape[1] > 0
    ):
        st.warning("The dataset is empty or could not be loaded. Please select a valid data file.")
        return  # Stop further processing

    # data filter to speed-up
    c = st.columns(5)
    sampling_ratio = c[4].number_input(
        "Sampling ratio",
        min_value=1,
        value=st.session_state.GUI_SAMPLING,
        step=1,
    )
    st.session_state.GUI_SAMPLING = sampling_ratio
    st.session_state.loaded_df = downsample_df_deterministic(st.session_state.loaded_df, sampling_ratio)
    nrows = st.session_state.loaded_df.shape[0]

    lines = st.slider(
        "Select the desired number of points:",
        min_value=5,
        max_value=nrows,
        value=st.session_state.TABLE_MAX_ROWS,
        step=10,
    )
    st.session_state.TABLE_MAX_ROWS = lines
    if lines >= 0:
        st.session_state.loaded_df = st.session_state.loaded_df.iloc[:lines, :]

    df = st.session_state.loaded_df

    if "beam" in df.columns:
        available_beams = sorted({str(val) for val in df["beam"].dropna().unique()})
        selected_beams = st.sidebar.multiselect(
            "Filter beams",
            available_beams,
            key=f"view_maps_beam_filter_{env.app}",
        )
        if selected_beams:
            df = df[df["beam"].astype(str).isin(selected_beams)].copy()
            st.session_state.loaded_df = df
        beam_summary_cols = {"points": ("beam", "size")}
        if "alt_m" in df.columns:
            beam_summary_cols["mean_alt_m"] = ("alt_m", "mean")
        if "sat" in df.columns:
            beam_summary_cols["dominant_sat"] = (
                "sat",
                lambda series: series.mode().iat[0] if not series.mode().empty else None,
            )
        with st.expander("Beam coverage", expanded=False):
            summary_df = (
                df.groupby("beam")
                .agg(**beam_summary_cols)
                .reset_index()
                .rename(columns={"beam": "beam_id"})
                .sort_values(by="beam_id")
            )
            st.dataframe(summary_df, use_container_width=True)
    else:
        st.sidebar.write("")

    sat_default = bool(view_settings.get("show_sat_overlay", True))
    show_sat_overlay = st.sidebar.checkbox(
        "Show satellite overlay",
        value=sat_default,
        key=f"view_maps_sat_overlay_{env.app}",
    )
    if view_settings.get("show_sat_overlay", True) != show_sat_overlay:
        view_settings["show_sat_overlay"] = show_sat_overlay
        full_settings = _persist_view_maps_settings(env, full_settings, view_settings)

    # Select numeric columns
    numeric_cols = st.session_state.loaded_df.select_dtypes(include=["number"]).columns.tolist()

    # Define lists to store continuous and discrete numeric variables
    continuous_cols = []
    discrete_numeric_cols = []

    # Define a threshold: if a numeric column has fewer unique values than this threshold,
    # treat it as discrete. Adjust this value based on your needs.
    # Threshold to classify numeric columns as discrete vs continuous
    unique_default = int(view_settings.get("unique_threshold", 10))
    unique_threshold = st.sidebar.number_input(
        "Discrete threshold (unique values <)",
        min_value=2,
        max_value=100,
        value=unique_default,
        step=1,
    )
    if view_settings.get("unique_threshold", 10) != unique_threshold:
        view_settings["unique_threshold"] = int(unique_threshold)
        full_settings = _persist_view_maps_settings(env, full_settings, view_settings)

    range_default = int(view_settings.get("range_threshold", 200))
    range_threshold = st.sidebar.number_input(
        "Integer discrete range (max-min <=)",
        min_value=1,
        max_value=10000,
        value=range_default,
        step=1,
    )
    if view_settings.get("range_threshold", 200) != range_threshold:
        view_settings["range_threshold"] = int(range_threshold)
        full_settings = _persist_view_maps_settings(env, full_settings, view_settings)

    # Loop through numeric columns and classify them based on the unique value count.
    for col in numeric_cols:
        if df[col].nunique() < unique_threshold:
            discrete_numeric_cols.append(col)
        else:
            continuous_cols.append(col)

    # Get discrete variables from object type
    discrete_object_cols = df.select_dtypes(include=["object"]).columns.tolist()

    # Combine numeric discrete and object discrete variables
    discrete_cols = discrete_numeric_cols + discrete_object_cols

    # Re-classify integer columns with limited range as discrete to avoid sliders
    for col in numeric_cols:
        if not is_integer_dtype(df[col]):
            continue
        try:
            value_range = df[col].max() - df[col].min()
        except TypeError:
            continue
        if pd.isna(value_range) or value_range > range_threshold:
            continue
        if col in continuous_cols:
            continuous_cols.remove(col)
        if col not in discrete_cols:
            discrete_cols.append(col)
    discreteseq = None
    colorscale = None

    # Identify numerical columns
    for col in discrete_cols.copy():  # Use copy to avoid modifying the list during iteration
        try:
            pd.to_datetime(
                st.session_state.loaded_df[col],
                format="%Y-%m-%d %H:%M:%S",
                errors="raise",
            )
            discrete_cols.remove(col)
            continuous_cols.append(col)
        except (ValueError, TypeError):
            pass

    for i, cols in enumerate([discrete_cols, continuous_cols]):
        if cols:
            colsn = (
                pd.DataFrame(
                    [
                        {
                            "Columns": col,
                            "nbval": len(set(st.session_state.loaded_df[col])),
                        }
                        for col in cols
                    ]
                )
                .sort_values(by="nbval", ascending=False)
                .Columns.tolist()
            )
            if var[i] == "discrete" and "beam" in colsn:
                colsn = ["beam"] + [col for col in colsn if col != "beam"]
            on_change_function = None
            if var[i] == "discrete":
                on_change_function = discrete
            elif var[i] == "continuous":
                on_change_function = continuous
            with c[i]:
                st.selectbox(
                    label=f"{var[i]}",
                    options=colsn,
                    index=var_default[i] if var_default[i] is not None and var_default[i] < len(colsn) else 0,
                    key=var[i],
                    on_change=on_change_function,
                )
                if var[i] == "discrete":
                    discreteseqs = [
                        "Plotly",
                        "D3",
                        "G10",
                        "T10",
                        "Alphabet",
                        "Dark24",
                        "Light24",
                        "Set1",
                        "Pastel1",
                        "Dark2",
                        "Set2",
                        "Pastel2",
                        "Set3",
                    ]
                    discreteseq = st.selectbox("Color Sequence", discreteseqs, index=0)
                elif var[i] == "continuous":
                    colorscales = px.colors.named_colorscales()
                    colorscale = st.selectbox("Color Scale", colorscales, index=0)
        else:
            with c[i]:
                st.warning(f"No columns available for {var[i]}.")
                st.session_state[var[i]] = None

    for i in range(2, 4):
        colsn = st.session_state.loaded_df.filter(regex=var[i]).columns.tolist()
        with c[i]:
            if colsn:
                st.selectbox(f"{var[i]}", colsn, index=0, key=var[i])
            else:
                st.warning(f"No columns matching '{var[i]}' found.")
                st.session_state[var[i]] = None

    map_cfg = st.session_state.get(map_defaults_key, {"center_lat": 0.0, "center_lon": 0.0, "default_zoom": 2.5})
    lat_col = st.session_state.get("lat")
    lon_col = st.session_state.get("long")
    if lat_col and lon_col and lat_col in df.columns and lon_col in df.columns:
        viewport = _compute_viewport(df, lat_col, lon_col)
        if viewport:
            map_cfg.update(viewport)

    plot_df = st.session_state.loaded_df
    color_column = st.session_state.get(st.session_state.get("coltype", ""), None)
    if (
        st.session_state.get("coltype") == "discrete"
        and color_column
        and color_column in plot_df.columns
        and is_numeric_dtype(plot_df[color_column])
    ):
        plot_df = plot_df.copy()
        plot_df[color_column] = plot_df[color_column].astype("Int64").astype(str)

    if st.session_state.get("lat") and st.session_state.get("long"):
        if st.session_state.get("coltype") and st.session_state.get(st.session_state["coltype"]):
            if discreteseq:
                # Get the color sequence
                color_sequence = getattr(px.colors.qualitative, discreteseq)
                fig = px.scatter_mapbox(
                    plot_df,
                    lat=st.session_state.lat,
                    lon=st.session_state.long,
                    zoom=map_cfg["default_zoom"],
                    center={"lat": map_cfg["center_lat"], "lon": map_cfg["center_lon"]},
                    color_discrete_sequence=color_sequence,
                    color=st.session_state[st.session_state.coltype],
                )
            elif colorscale:
                fig = px.scatter_mapbox(
                    plot_df,
                    lat=st.session_state.lat,
                    lon=st.session_state.long,
                    zoom=map_cfg["default_zoom"],
                    center={"lat": map_cfg["center_lat"], "lon": map_cfg["center_lon"]},
                    color_continuous_scale=colorscale,
                    color=st.session_state[st.session_state.coltype],
                )
            else:
                fig = px.scatter_mapbox(
                    plot_df,
                    lat=st.session_state.lat,
                    lon=st.session_state.long,
                    zoom=map_cfg["default_zoom"],
                    center={"lat": map_cfg["center_lat"], "lon": map_cfg["center_lon"]},
                )

            if (
                show_sat_overlay
                and {"sat_track_lat", "sat_track_long"} <= set(st.session_state.loaded_df.columns)
            ):
                sat_points = (
                    st.session_state.loaded_df[["sat_track_lat", "sat_track_long", "sat"]]
                    .dropna(subset=["sat_track_lat", "sat_track_long"])
                    .drop_duplicates()
                )
                if not sat_points.empty:
                    fig.add_trace(
                        go.Scattermapbox(
                            lat=sat_points["sat_track_lat"],
                            lon=sat_points["sat_track_long"],
                            mode="markers",
                            marker=dict(size=10, color="#ffa600", symbol="triangle"),
                            name="Satellite track",
                            text=sat_points.get("sat"),
                        )
                    )

            fig.update_layout(mapbox_style="open-street-map")
            fig.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0})

            st.plotly_chart(fig, use_container_width=True, theme="streamlit")
        else:
            st.warning("Please select a valid column for coloring.")
    else:
        st.warning("Latitude and Longitude columns are required for the map.")

    # Persist user selections for next reload
    persist_keys = ["df_files_selected", "discrete", "continuous", "lat", "long", "coltype"]
    mutated = False
    for key in persist_keys:
        val = st.session_state.get(key)
        if val is None:
            continue
        if view_settings.get(key) != val:
            view_settings[key] = val
            mutated = True
    if mutated:
        full_settings = _persist_view_maps_settings(env, full_settings, view_settings)

# -------------------- Main Application Entry -------------------- #
def main():
    """
    Main function to run the application.
    """

    try:
        parser = argparse.ArgumentParser(description="Run the AGI Streamlit View with optional parameters.")
        parser.add_argument(
            "--active-app",
            dest="active_app",
            type=str,
            help="Active app path (e.g. src/agilab/apps/builtin/flight_project)",
            required=True,
        )
        args, _ = parser.parse_known_args()

        active_app = Path(args.active_app).expanduser()
        if not active_app.exists():
            st.error(f"Error: provided --active-app path not found: {active_app}")
            sys.exit(1)

        if "coltype" not in st.session_state:
            st.session_state["coltype"] = var[0]

        # Derive the short app name (e.g., 'flight_project')
        app = active_app.name
        st.session_state["apps_path"] = str(active_app.parent)
        st.session_state["app"] = app

        st.info(f"active_app: {active_app}")
        env = AgiEnv(
            apps_path=active_app.parent,
            app=app,
            verbose=1,
        )
        env.init_done = True
        st.session_state['env'] = env
        st.session_state["IS_SOURCE_ENV"] = env.is_source_env
        st.session_state["IS_WORKER_ENV"] = env.is_worker_env

        if "TABLE_MAX_ROWS" not in st.session_state:
            st.session_state["TABLE_MAX_ROWS"] = env.TABLE_MAX_ROWS
        if "GUI_SAMPLING" not in st.session_state:
            st.session_state["GUI_SAMPLING"] = env.GUI_SAMPLING

        page(env)

    except Exception as e:
        st.error(f"An error occurred: {e}")
        import traceback

        st.code(traceback.format_exc())


# -------------------- Main Entry Point -------------------- #
if __name__ == "__main__":
    main()
