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

import os
import sys
import argparse
from pathlib import Path
import re

import streamlit as st
import pandas as pd
import pydeck as pdk
import plotly.express as px
import geojson
import random

from agi_env.agi_logger import AgiLogger

logger = AgiLogger.get_logger(__name__)

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
from agi_env.pagelib import find_files, load_df, render_logo, _dump_toml_payload
import tomllib as _toml


# List of available color palettes
discreteseqs = ["Plotly", "D3", "G10", "T10", "Alphabet", "Dark24", "Light24"]

# Terrain Layer configuration
TERRAIN_IMAGE = (
    "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
)
SURFACE_IMAGE = f"https://server.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}"
ELEVATION_DECODER = {
    "rScaler": 256,
    "gScaler": 1,
    "bScaler": 1 / 256,
    "offset": -32768,
}

# Define possible names for latitude and longitude columns
possible_latitude_names = ["latitude", "lat", "beam_lat"]
possible_longitude_names = ["longitude", "long", "lng", "beam_long"]
DATASET_EXTENSIONS = (".csv", ".parquet", ".json")
FILE_TYPE_OPTIONS = ("csv", "parquet", "json", "all")
DF_SELECTION_MODES = ("Single file", "Multi-select", "Regex (multi)")
PAGE_KEY_PREFIX = "view_maps_3d"


def _vm3d_key(name: str) -> str:
    return f"{PAGE_KEY_PREFIX}:{name}"


def _list_dataset_files(base_dir: Path, ext_choice: str = "all") -> list[Path]:
    files: list[Path] = []
    extensions = DATASET_EXTENSIONS if ext_choice == "all" else (f".{ext_choice}",)
    for ext in extensions:
        files.extend(find_files(base_dir, ext=ext))
    # De-duplicate while keeping deterministic ordering for widget defaults.
    return sorted(set(files))

st.title(":world_map: Cartography-3D Visualisation")


@st.cache_data
def generate_random_colors(num_colors):
    """
    Generate a list of random RGB color values.

    Args:
        num_colors (int): The number of random colors to generate.

    Returns:
        list: A list of RGB color values, each represented as a list [red, green, blue].

    Note:
        This function is cached using Streamlit's st.cache_data decorator.

    Example:
        generate_random_colors(3) -> [[128, 156, 178], [189, 102, 140], [145, 180, 200]]
    """
    return [
        [random.randint(100, 200), random.randint(100, 200), random.randint(100, 200)]
        for _ in range(num_colors)
    ]


def initialize_csv_files():
    """
    Initialize dataset files for the session state.

    If files do not exist in the session state, discover CSV/Parquet/JSON
    files in the data directory.
    If 'df_file' does not exist in the session state or is empty, set the
    first discovered dataset as the default.

    Args:
        None

    Returns:
        None
    """
    """ """
    datadir = Path(st.session_state.datadir)
    dataset_key = "dataset_files"
    if dataset_key not in st.session_state or not st.session_state[dataset_key]:
        files = _list_dataset_files(datadir)
        # Hide any path with dot-prefixed components
        visible = []
        for f in files:
            try:
                parts = f.relative_to(datadir).parts
            except Exception:
                parts = f.parts
            if any(part.startswith(".") for part in parts):
                continue
            visible.append(f)
        st.session_state[dataset_key] = visible
        # Backward-compatible alias used by older helper code.
        st.session_state["csv_files"] = visible
    if "df_file" not in st.session_state or not st.session_state["df_file"]:
        dataset_files_rel = [
            Path(file).relative_to(datadir).as_posix()
            for file in st.session_state.get(dataset_key, [])
        ]
        st.session_state["df_file"] = dataset_files_rel[0] if dataset_files_rel else None


def initialize_beam_files():
    """Initialize beam CSV files in the session state."""
    if (
            "beam_csv_files" not in st.session_state
            or not st.session_state["beam_csv_files"]
    ):
        files = find_files(st.session_state.beamdir)
        visible = []
        for f in files:
            try:
                parts = f.relative_to(st.session_state.beamdir).parts
            except Exception:
                parts = f.parts
            if any(part.startswith(".") for part in parts):
                continue
            visible.append(f)
        st.session_state["beam_csv_files"] = visible
    if "beam_file" not in st.session_state:
        beam_csv_files_rel = [
            Path(file).relative_to(st.session_state.beamdir).as_posix()
            for file in st.session_state.beam_csv_files
        ]
        st.session_state["beam_file"] = (
            beam_csv_files_rel[0] if beam_csv_files_rel else None
        )


def continious():
    """
    Update the column type to 'continious' in the session state.

    Args:
        None

    Returns:
        None
    """
    """ """
    st.session_state["coltype"] = "continious"


def discrete():
    """
    Set the column type to 'discrete' in the session state dictionary.

    No args.

    No returns.

    No raises.
    """
    """ """
    st.session_state["coltype"] = "discrete"


def update_var(var_key, widget_key):
    """

    Args:
      var_key:
      widget_key:

    Returns:

    """
    st.session_state[var_key] = st.session_state[widget_key]


def update_datadir(var_key, widget_key):
    """

    Args:
      var_key:
      widget_key:

    Returns:

    """
    for key in ("df_file", "df_files_selected", "csv_files", "dataset_files", "loaded_df"):
        if key in st.session_state:
            del st.session_state[key]
    update_var(var_key, widget_key)
    initialize_csv_files()


def update_beamdir(var_key, widget_key):
    """Update the beam directory and reinitialize beam files."""
    if "beam_file" in st.session_state:
        del st.session_state["beam_file"]
    if "beam_csv_files" in st.session_state:
        del st.session_state["beam_csv_files"]
    update_var(var_key, widget_key)
    initialize_beam_files()


def get_category_color_map(df, coltype, palette_name):
    """Generate a color map for the categories in the selected column."""
    unique_categories = df[coltype].unique()
    num_categories = len(unique_categories)

    # Get the selected color palette
    selected_palette = get_palette(palette_name)

    # Ensure we have enough colors, repeating if necessary
    if len(selected_palette) < num_categories:
        selected_palette = (
                                   selected_palette * (num_categories // len(selected_palette) + 1)
                           )[:num_categories]

    # Map categories to colors
    return {
        category: hex_to_rgb(color)
        for category, color in zip(unique_categories, selected_palette)
    }


# Function to get the selected color palette
def get_palette(palette_name):
    # Access color palette dynamically from px.colors.qualitative
    """
    Get a qualitative color palette by name from Plotly Express.

    Args:
        palette_name (str): The name of the color palette to retrieve.

    Returns:
        list or property: The qualitative color palette corresponding to the input name. Returns an empty list if the palette is not found.

    Raises:
        AttributeError: If the specified palette name is not found in Plotly Express colors.
    """
    try:
        palette = getattr(px.colors.qualitative, palette_name)
        return palette
    except AttributeError:
        st.error(f"Palette '{palette_name}' not found.")
        return []


# Function to convert HEX to RGB 0-255 range
def hex_to_rgb(hex_color):
    """
    Convert a hex color code to RGB values.

    Args:
        hex_color (str): A string representing a hex color code.

    Returns:
        tuple: A tuple containing the RGB values as integers.

        The RGB values are in the range of 0 to 255.

        If the input hex color is not valid, (0, 0, 0) is returned.

    Raises:
        None
    """
    if hex_color.startswith("#") and len(hex_color) == 7:
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i: i + 2], 16) for i in (0, 2, 4))
    return (0, 0, 0)  # Default to black if format is incorrect


def poly_geojson_to_csv(geojson_data):
    """
    Convert a GeoJSON object containing polygon and multipolygon features to a Pandas DataFrame with longitude and latitude columns.

    Args:
        geojson_data (dict): A GeoJSON object containing polygon and multipolygon features.

    Returns:
        pandas.DataFrame: A DataFrame with columns ['polygon_index', 'longitude', 'latitude'].

    Raises:
        KeyError: If the input GeoJSON object does not contain the expected keys.
    """
    features = geojson_data["features"]

    # Extract coordinates
    rows = []
    polygon_index = 0
    for feature in features:
        geometry = feature["geometry"]
        if geometry["type"] == "Polygon":
            # Extract coordinates from the first ring (assuming no holes)
            coordinates = geometry["coordinates"][0]
            for coord in coordinates:
                lon = coord[0]
                lat = coord[1]
                rows.append([polygon_index, lon, lat])
            polygon_index += 1
        elif geometry["type"] == "MultiPolygon":
            for polygon in geometry["coordinates"]:
                for coord in polygon[0]:
                    lon = coord[0]
                    lat = coord[1]
                    rows.append([polygon_index, lon, lat])
                polygon_index += 1

    # Convert to DataFrame
    df = pd.DataFrame(rows, columns=["polygon_index", "longitude", "latitude"])

    return df


def move_to_data(file_name, csv):
    """
    Move CSV data to a specified file path.

    Args:
        file_name (str): The name of the file to be created.
        csv (str): The CSV data to be written to the file.

    Returns:
        None

    Side Effects:
        - Creates a file with the given file_name and writes the csv data to it.
        - Displays a success message in the sidebar with the file path.

    Dependencies:
        - st.session_state['beamdir']: The base directory path.
        - update_beamdir: A function to update the beam directory paths.

    Raises:
        None
    """
    data_path = Path(st.session_state["beamdir"]) / file_name
    data_path.write_text(csv)
    st.sidebar.success(f"File moved to {data_path}")
    update_beamdir("beamdir", "input_beamdir")

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

# Main page function
def page():
    """
    Display a web page interface for visualizing and analyzing data.

    This function sets up a sidebar with inputs for data directories, loads data files, and allows for interactive data visualization using PyDeck.

    Args:
        None

    Returns:
        None
    """
    render_logo("3D Maps and Network Topology Visualization")

    if 'env' not in st.session_state:
        st.error("The application environment is not initialized. Please click on  AGILAB.")
        st.stop()
    else:
        env = st.session_state['env']

    # Define variable types and their default indices
    var = ["discrete", "continious", "lat", "long", "alt"]
    var_default = [0, None]

    # Load persisted settings
    settings_path = Path(env.app_settings_file)
    persisted = {}
    try:
        with open(settings_path, "rb") as fh:
            persisted = _toml.load(fh)
    except Exception:
        persisted = {}
    view_settings = persisted.get("view_maps_3d", {}) if isinstance(persisted, dict) else {}

    # Lazy imports and efficient session state initialization
    if "datadir" not in st.session_state:
        datadir = Path(view_settings.get("datadir") or (env.AGILAB_EXPORT_ABS / env.target))
        if not datadir.exists():
            logger.info(f"mkdir {datadir}")
            os.makedirs(datadir, exist_ok=True)
        st.session_state["datadir"] = datadir
    if "project" not in st.session_state:
        st.session_state["project"] = env.target
    if "projects" not in st.session_state:
        st.session_state["projects"] = env.projects
    if "beamdir" not in st.session_state:
        base_share = env.share_root_path()
        st.session_state["beamdir"] = Path(view_settings.get("beamdir") or (base_share / env.target.replace("_project", "")))
    if "coltype" not in st.session_state:
        st.session_state["coltype"] = view_settings.get("coltype", var[0])

    datadir_widget_key = _vm3d_key("input_datadir")
    datadir_str = str(st.session_state.datadir)
    if st.session_state.get(datadir_widget_key) != datadir_str:
        st.session_state[datadir_widget_key] = datadir_str
    st.sidebar.text_input(
        "Data Directory",
        key=datadir_widget_key,
        on_change=update_datadir,
        args=("datadir", datadir_widget_key),
    )

    if "loaded_df" not in st.session_state:
        st.session_state["loaded_df"] = None

    datadir = Path(st.session_state.datadir)
    datadir_last_key = _vm3d_key("last_datadir")
    datadir_changed = st.session_state.get(datadir_last_key) != str(datadir)
    st.session_state[datadir_last_key] = str(datadir)

    if not datadir.exists() or not datadir.is_dir():
        st.sidebar.error("Directory not found.")
        st.warning("A valid data directory is required to proceed.")
        return  # Stop further processing

    file_ext_key = _vm3d_key("file_ext_choice")
    ext_default = str(view_settings.get("file_ext_choice", "all")).lower()
    if ext_default not in FILE_TYPE_OPTIONS:
        ext_default = "all"
    if st.session_state.get(file_ext_key) not in FILE_TYPE_OPTIONS:
        st.session_state[file_ext_key] = ext_default
    ext_choice = st.sidebar.selectbox(
        "File type",
        FILE_TYPE_OPTIONS,
        key=file_ext_key,
    )
    st.session_state["file_ext_choice"] = ext_choice

    dataset_key = "dataset_files"
    legacy_key = "csv_files"
    dataset_files = _list_dataset_files(datadir, ext_choice=ext_choice)
    st.session_state[dataset_key] = dataset_files
    st.session_state[legacy_key] = dataset_files
    if not dataset_files:
        st.warning(
            f"No dataset found in {datadir} (filter: {ext_choice}). "
            "Please add CSV/Parquet/JSON outputs via Execute/Export."
        )
        st.stop()
    dataset_files_rel_set: set[str] = set()
    for file in dataset_files:
        try:
            rel_path = Path(file).relative_to(datadir)
        except Exception:
            continue
        if any(part.startswith(".") for part in rel_path.parts):
            continue
        dataset_files_rel_set.add(rel_path.as_posix())
    dataset_files_rel = sorted(dataset_files_rel_set)

    settings_files = view_settings.get("df_files_selected") or []
    if not settings_files:
        legacy_setting = view_settings.get("df_file")
        settings_files = [legacy_setting] if legacy_setting else []
    default_selection = (
        [item for item in settings_files if item in dataset_files_rel]
        or dataset_files_rel[:1]
    )

    mode_key = _vm3d_key("df_select_mode")
    mode_default = str(view_settings.get("df_select_mode", "Multi-select"))
    if mode_default not in DF_SELECTION_MODES:
        mode_default = "Multi-select"
    if st.session_state.get(mode_key) not in DF_SELECTION_MODES:
        st.session_state[mode_key] = mode_default
    df_mode = st.sidebar.radio(
        "Dataset selection",
        options=DF_SELECTION_MODES,
        key=mode_key,
    )
    st.session_state["df_select_mode"] = df_mode

    selection_key = _vm3d_key("df_files_selected")
    if selection_key not in st.session_state:
        legacy_selected = st.session_state.get("df_files_selected")
        if isinstance(legacy_selected, list):
            st.session_state[selection_key] = [item for item in legacy_selected if item in dataset_files_rel]
        else:
            st.session_state[selection_key] = []
    current_selection = st.session_state.get(selection_key)
    if not isinstance(current_selection, list):
        current_selection = []
    current_selection = [item for item in current_selection if item in dataset_files_rel]
    if datadir_changed or (not current_selection and default_selection):
        current_selection = default_selection
    st.session_state[selection_key] = current_selection

    single_file_key = _vm3d_key("df_file")
    single_default = (
        current_selection[0]
        if current_selection
        else (default_selection[0] if default_selection else "")
    )
    if st.session_state.get(single_file_key) not in dataset_files_rel:
        st.session_state[single_file_key] = single_default

    regex_key = _vm3d_key("df_file_regex")
    if regex_key not in st.session_state:
        st.session_state[regex_key] = str(view_settings.get("df_file_regex", ""))

    selected_files: list[str] = []
    if df_mode == "Single file":
        st.sidebar.selectbox(
            "DataFrame",
            options=dataset_files_rel,
            key=single_file_key,
        )
        selected_single = st.session_state.get(single_file_key)
        if selected_single:
            selected_files = [selected_single]
    elif df_mode == "Regex (multi)":
        regex_raw = st.sidebar.text_input(
            "DataFrame filename regex",
            key=regex_key,
            help="Python regex applied to the relative file path. Leave empty to match all files.",
        ).strip()
        regex_ok = True
        pattern = None
        if regex_raw:
            try:
                pattern = re.compile(regex_raw)
            except re.error as exc:
                regex_ok = False
                st.sidebar.error(f"Invalid regex: {exc}")
        matching = (
            [item for item in dataset_files_rel if pattern.search(item)]
            if (regex_ok and pattern is not None)
            else (dataset_files_rel if not regex_raw else [])
        )
        st.sidebar.caption(f"{len(matching)} / {len(dataset_files_rel)} files match")
        if st.sidebar.button(
            f"Select all matching ({len(matching)})",
            disabled=not matching,
            key=_vm3d_key("df_regex_select_all"),
        ):
            st.session_state[selection_key] = matching
        seeded = st.session_state.get(selection_key)
        if not isinstance(seeded, list):
            seeded = []
        seeded = [item for item in seeded if item in dataset_files_rel]
        if not seeded:
            seeded = default_selection
        st.session_state[selection_key] = seeded
        st.sidebar.multiselect(
            "DataFrames",
            options=dataset_files_rel,
            key=selection_key,
            help="Select one or more CSV/Parquet/JSON files (including split part files).",
        )
        selected_files = [item for item in st.session_state.get(selection_key, []) if item in dataset_files_rel]
    else:
        st.sidebar.multiselect(
            "DataFrames",
            options=dataset_files_rel,
            key=selection_key,
            help="Select one or more CSV/Parquet/JSON files (including split part files).",
        )
        selected_files = [item for item in st.session_state.get(selection_key, []) if item in dataset_files_rel]
    st.sidebar.caption(f"{len(selected_files)} selected")
    if selected_files:
        st.session_state[single_file_key] = selected_files[0]
    st.session_state["df_files_selected"] = selected_files
    st.session_state["df_file"] = selected_files[0] if selected_files else ""
    st.session_state["df_file_regex"] = st.session_state.get(regex_key, "")
    if not selected_files:
        st.warning("Please select at least one dataset to proceed.")
        return

    beamdir_widget_key = _vm3d_key("input_beamdir")
    beamdir_str = str(st.session_state.beamdir)
    if st.session_state.get(beamdir_widget_key) != beamdir_str:
        st.session_state[beamdir_widget_key] = beamdir_str
    st.sidebar.text_input(
        "Polygon Directory",
        key=beamdir_widget_key,
        on_change=update_beamdir,
        args=("beamdir", beamdir_widget_key),
    )

    # Initialize session state for beam_files if it doesn't exist
    default_beam_files = ["dataset/beams.csv"]  # Define your default file here
    if "beam_files" not in st.session_state:
        st.session_state["beam_files"] = default_beam_files

    if st.session_state.beamdir:
        beamdir = Path(st.session_state.beamdir)
        if beamdir.exists() and beamdir.is_dir():
            files = find_files(st.session_state["beamdir"], recursive=False)
            visible = []
            for f in files:
                try:
                    parts = f.relative_to(beamdir).parts
                except Exception:
                    parts = f.parts
                if any(part.startswith(".") for part in parts):
                    continue
                visible.append(f)
            st.session_state["beam_csv_files"] = visible
            beam_csv_files_rel = sorted(
                [
                    Path(file).relative_to(beamdir).as_posix()
                    for file in st.session_state.beam_csv_files
                ]
            )
            beam_files_key = _vm3d_key("beam_files")
            if beam_files_key not in st.session_state:
                legacy_beams = st.session_state.get("beam_files")
                if isinstance(legacy_beams, list):
                    st.session_state[beam_files_key] = [
                        item for item in legacy_beams if item in beam_csv_files_rel
                    ]
                else:
                    st.session_state[beam_files_key] = []
            beam_seed = st.session_state.get(beam_files_key)
            if not isinstance(beam_seed, list):
                beam_seed = []
            beam_seed = [item for item in beam_seed if item in beam_csv_files_rel]
            if not beam_seed and default_beam_files:
                beam_seed = [item for item in default_beam_files if item in beam_csv_files_rel]
            st.session_state[beam_files_key] = beam_seed
            st.sidebar.multiselect(
                "Polygon Files",
                beam_csv_files_rel,
                key=beam_files_key,
            )
            selected_beams = st.session_state.get(beam_files_key, [])
            if isinstance(selected_beams, list):
                st.session_state["beam_files"] = [item for item in selected_beams if item in beam_csv_files_rel]
            else:
                st.session_state["beam_files"] = []
        else:
            st.warning("Beam directory not found")

    if "beam_files" in st.session_state and st.session_state["beam_files"]:
        st.session_state["dfs_beams"] = {}
        for beam_file in st.session_state["beam_files"]:
            beam_file_abs = Path(st.session_state.beamdir) / beam_file
            cache_buster = None
            try:
                cache_buster = beam_file_abs.stat().st_mtime_ns
            except Exception:
                pass
            st.session_state["dfs_beams"][beam_file] = load_df(
                beam_file_abs, with_index=False, cache_buster=cache_buster
            )
    selected_files = st.session_state.get("df_files_selected", [])
    dataframes: list[pd.DataFrame] = []
    load_errors: list[str] = []
    for rel_path in selected_files:
        df_file_abs = datadir / rel_path
        cache_buster = None
        try:
            cache_buster = df_file_abs.stat().st_mtime_ns
        except Exception:
            pass
        try:
            df_loaded = load_df(df_file_abs, with_index=True, cache_buster=cache_buster)
        except Exception as exc:
            load_errors.append(f"{rel_path}: {exc}")
            continue
        if not isinstance(df_loaded, pd.DataFrame):
            load_errors.append(f"{rel_path}: unexpected type {type(df_loaded)}")
            continue
        if df_loaded.empty:
            load_errors.append(f"{rel_path}: empty dataframe")
            continue
        df_loaded = df_loaded.copy()
        df_loaded["__dataset__"] = rel_path
        dataframes.append(df_loaded)
    if load_errors:
        st.sidebar.warning("Some selected files failed to load; continuing with the rest.")
        with st.sidebar.expander("Load errors", expanded=False):
            for err in load_errors[:50]:
                st.write(err)
            if len(load_errors) > 50:
                st.write(f"... ({len(load_errors) - 50} more)")
    if dataframes:
        st.session_state["loaded_df"] = pd.concat(dataframes, ignore_index=True)
    else:
        st.session_state["loaded_df"] = pd.DataFrame()
        st.error("No selected dataframes could be loaded.")
        return

    # Persist current selections for reloads
    save_settings = {
        "datadir": str(st.session_state.get("datadir", "")),
        "beamdir": str(st.session_state.get("beamdir", "")),
        "file_ext_choice": st.session_state.get("file_ext_choice", "all"),
        "df_select_mode": st.session_state.get("df_select_mode", "Multi-select"),
        "df_file_regex": st.session_state.get("df_file_regex", ""),
        "df_file": st.session_state.get("df_file", ""),
        "df_files_selected": st.session_state.get("df_files_selected", []),
        "beam_files": st.session_state.get("beam_files", []),
        "coltype": st.session_state.get("coltype", ""),
    }
    mutated = False
    view_settings = persisted.get("view_maps_3d", {}) if isinstance(persisted, dict) else {}
    if not isinstance(view_settings, dict):
        view_settings = {}
    for k, v in save_settings.items():
        if view_settings.get(k) != v and v not in (None, ""):
            view_settings[k] = v
            mutated = True
    if mutated:
        persisted["view_maps_3d"] = view_settings
        try:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            with open(settings_path, "wb") as fh:
                _dump_toml_payload(persisted, fh)
        except Exception:
            pass

    # Create a button styled link to open geojson.io with Streamlit-like customization
    st.sidebar.markdown(
        """
        <style>
        .custom-button {
            background-color: #000000; /* Black background */
            color: white; /* White text */
            border: none;
            padding: 8px 16px; /* Smaller size */
            text-align: center;
            text-decoration: none; /* No underline */
            display: inline-block;
            font-size: 14px; /* Smaller font size */
            margin: 4px 2px;
            cursor: pointer;
            border-radius: 12px; /* Rounded corners */
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.3);
            transition: background-color 0.3s, transform 0.2s;
        }
        .custom-button:hover {
            background-color: #333333; /* Darker black on hover */
        }
        </style>
        <a href="http://geojson.io" target="_blank" class="custom-button">
            Open geojson.io
        </a>
    """,
        unsafe_allow_html=True,
    )

    # File uploader for GeoJSON
    uploaded_file = st.sidebar.file_uploader(
        "Upload your GeoJSON file", type=["geojson"]
    )
    if uploaded_file is not None:
        # Load GeoJSON data
        geojson_data = geojson.load(uploaded_file)

        # Convert GeoJSON to simple CSV
        df = poly_geojson_to_csv(geojson_data)

        csv = df.to_csv(index=False)

        # Provide an input field for the CSV file name
        file_name = st.sidebar.text_input(
            "Enter the name for your converted CSV file", value="converted_data.csv"
        )

        # Provide a "Move to data" button
        if st.sidebar.button("Move to data"):
            move_to_data(file_name, csv)

        # Provide a download link for the CSV file
        st.sidebar.download_button(
            label="Download CSV",
            data=csv,
            file_name=file_name,
            mime="text/csv",
        )

    if "loaded_df" in st.session_state:
        if (
                isinstance(st.session_state.loaded_df, pd.DataFrame)
                and not st.session_state.loaded_df.empty
        ):
            # Initialize an empty DataFrame to store distribution metrics
            c = st.columns(5)
            sampling_key = _vm3d_key("sampling_ratio")
            if sampling_key not in st.session_state:
                st.session_state[sampling_key] = max(1, int(st.session_state.GUI_SAMPLING))
            sampling_ratio = c[4].number_input(
                "Sampling ratio",
                min_value=1,
                step=1,
                key=sampling_key,
            )
            st.session_state.GUI_SAMPLING = int(sampling_ratio)
            st.session_state.loaded_df=downsample_df_deterministic(st.session_state.loaded_df, sampling_ratio)
            loaded_df = st.session_state.loaded_df
            nrows = st.session_state.loaded_df.shape[0]
            min_lines = 1 if nrows < 10 else 10
            line_limit_key = _vm3d_key("table_max_rows")
            try:
                table_max_rows = int(st.session_state.TABLE_MAX_ROWS)
            except Exception:
                table_max_rows = nrows
            default_line_limit = min(max(min_lines, table_max_rows), nrows)
            if st.session_state.get(line_limit_key) is None:
                st.session_state[line_limit_key] = default_line_limit
            else:
                try:
                    current_limit = int(st.session_state[line_limit_key])
                except Exception:
                    current_limit = default_line_limit
                st.session_state[line_limit_key] = min(max(min_lines, current_limit), nrows)
            lines = st.slider(
                "Select the desired number of points:",
                min_value=min_lines,
                max_value=nrows,
                step=1,
                key=line_limit_key,
            )
            st.session_state.TABLE_MAX_ROWS = int(lines)
            if lines >= 0:
                st.session_state.loaded_df = st.session_state.loaded_df.iloc[:lines, :]

            # st.session_state.loaded_df.set_index(
            #     st.session_state.loaded_df.columns[0], inplace=True
            # )

            # Select numeric columns
            numeric_cols = st.session_state.loaded_df.select_dtypes(include=["number"]).columns.tolist()
            # Define lists to store continuous and discrete numeric variables
            continious_cols = []
            discrete_cols = []

            # Define a threshold: if a numeric column has fewer unique values than this threshold,
            # treat it as discrete. Adjust this value based on your needs.
            unique_threshold = 20

            # Loop through numeric columns and classify them based on the unique value count.
            for col in numeric_cols:
                if st.session_state.loaded_df[col].nunique() < unique_threshold:
                    discrete_cols.append(col)
                else:
                    continious_cols.append(col)

            # Identify and reassign date-like columns from discrete to continuous.
            date_format = "%Y-%m-%d %H:%M:%S"
            for col in discrete_cols.copy():
                try:
                    pd.to_datetime(st.session_state.loaded_df[col], format=date_format, errors="raise")
                    discrete_cols.remove(col)
                    continious_cols.append(col)
                except (ValueError, TypeError):
                    pass

            # set a default opacity in case the slider never gets created
            opacity_key = _vm3d_key("opacity_slider")
            opacity_value = st.session_state.get(opacity_key, 0.8)

            for i, cols in enumerate([discrete_cols, continious_cols]):
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
                    with c[i]:
                        st.selectbox(
                            f"{var[i]}",
                            colsn,
                            index=var_default[i],
                            key=var[i],
                            on_change=eval(var[i]),
                        )
                        if i == 0:
                            # Select color palette from the list
                            palette_name = st.selectbox(
                                "color ↕", discreteseqs, index=0
                            )
                        else:
                            opacity_value = st.slider(
                                "opacity",
                                min_value=0.0,
                                max_value=1.0,
                                value=0.8,
                                step=0.01,
                                key=opacity_key,
                            )
                else:
                    with c[i]:
                        st.selectbox(
                            f"{var[i]}",
                            [],
                            index=var_default[i],
                            key=var[i],
                            on_change=eval(var[i]),
                        )

            for i in range(2, 5):
                colsn = st.session_state.loaded_df.filter(regex=var[i]).columns.tolist()
                with c[i]:
                    st.selectbox(f"{var[i]}", colsn, index=0, key=var[i])

            # Multi-select for layer selection with a unique key
            selected_layers = st.multiselect(
                "Select Layers",
                ["Terrain", "Flight Path", "Beams"],  # Include Beams layer
                default=["Terrain", "Flight Path", "Beams"],  # Set default layers
                key=_vm3d_key("layer_selection"),  # Unique key
            )

            # Determine visibility based on selection
            show_terrain = "Terrain" in selected_layers
            show_flight_path = "Flight Path" in selected_layers
            show_beams = "Beams" in selected_layers

            # Map categories to colors
            coltype = st.session_state["coltype"]
            selected_col = st.session_state[coltype]
            df = st.session_state.loaded_df

            # Initialize category_color_map as an empty dictionary
            category_color_map = {}

            # Ensure selected_col exists in the dataframe and is not None
            if selected_col is not None and selected_col in df.columns:
                category_color_map = get_category_color_map(
                    df, selected_col, palette_name
                )

                # Assign colors to the dataframe based on categories
                df["color"] = df[selected_col].map(category_color_map)
            else:
                # If selected_col is None or doesn't exist, assign a default color (e.g., white)
                df["color"] = [(255, 255, 255) for _ in range(len(df))]  # RGB for white
            if (
                    "lat" in st.session_state
                    and "long" in st.session_state
                    and "alt" in st.session_state
            ):
                # PyDeck Layer for Flight Path using ScatterplotLayer
                scatterplot_layer = pdk.Layer(
                    type="ScatterplotLayer",
                    data=st.session_state.loaded_df,
                    get_position=[
                        st.session_state.long,
                        st.session_state.lat,
                        st.session_state.alt,
                    ],
                    get_radius=20,  # Fixed radius to ensure points are visible
                    radius_min_pixels=3,  # Minimum radius in pixels
                    radius_max_pixels=35,  # Maximum radius in pixels
                    get_fill_color="[color[0], color[1], color[2], opacity_value * 255]",  # Adjust opacity if needed
                    pickable=True,  # Enable picking for interactivity
                    auto_highlight=True,
                    opacity=opacity_value,  # Use the selected opacity value
                    visible=show_flight_path,
                )

            terrain_layer = pdk.Layer(
                "TerrainLayer",
                elevation_decoder=ELEVATION_DECODER,
                texture=SURFACE_IMAGE,
                elevation_data=TERRAIN_IMAGE,
                min_zoom=0,
                max_zoom=23,
                strategy="no-overlap",
                opacity=0.5,  # Make terrain semi-transparent
                visible=show_terrain,  # Controlled by layer selection
            )

            # Generate colors for beams
            all_beam_polygons = []

            for beam_file, df in st.session_state.get("dfs_beams", {}).items():
                df.set_index(df.columns.tolist()[0], inplace=True, drop=True)
                beam_indices = df.index.unique()
                colors = generate_random_colors(len(beam_indices))

                # Prepare data for PolygonLayer for beams
                beam_polygons = [
                    {
                        "index": beam_index,
                        "polygon": [
                            [row.iloc[0], row.iloc[1]] for _, row in group_df.iterrows()
                        ],
                        "color": color,
                    }
                    for beam_index, ((_, group_df), color) in enumerate(
                        zip(df.groupby(df.index), colors)
                    )
                ]

                all_beam_polygons.extend(beam_polygons)

            # PyDeck Layer for Beams using PolygonLayer
            beams_layer = pdk.Layer(
                "PolygonLayer",
                data=all_beam_polygons,
                get_polygon="polygon",
                get_fill_color="color",  # Use the color attribute for fill color
                get_line_color=[0, 0, 0],  # White line color
                line_width_min_pixels=0.5,  # Adjust line width as needed (smaller value for thinner beams)
                pickable=True,
                extruded=True,  # Enable 3D extrusion
                elevation_scale=50,  # Adjust elevation scale for 3D effect
                elevation_range=[
                    500,
                    1000,
                ],  # Elevation range to ensure beams are above the flight path
                opacity=0.1,  # Adjust opacity to make beams more visible
                visible=True,
            )

            # Combine layers into a single PyDeck Deck
            layers = []

            if show_terrain:
                layers.append(terrain_layer)

            if show_flight_path:
                layers.append(scatterplot_layer)

            if show_beams:
                layers.append(beams_layer)

            # PyDeck Viewport state
            view_state = pdk.ViewState(
                latitude=st.session_state.loaded_df[st.session_state.lat].mean(),
                longitude=st.session_state.loaded_df[st.session_state.long].mean(),
                zoom=2.5,
                pitch=45,
                bearing=-25,
                min_pitch=0,  # Allow looking straight down
                max_pitch=85,  # Limit max pitch to avoid looking from below
            )

            # PyDeck Deck
            r = pdk.Deck(
                layers=layers,
                initial_view_state=view_state,
                tooltip={
                    "text": f"{selected_col}: {{{selected_col}}}"
                            f"\nLongitude: {{long}}\nLatitude: {{lat}}\nAltitude: {{alt}}"
                },
            )

            # Define HTML and CSS for the horizontal legend with Streamlit dark theme background color
            legend_html = f"""
            <div style="
                position: relative;
                width: 100%;
                background-color: #0e1117;  /* Streamlit dark theme background color */
                color: white;
                padding: 10px;
                border-radius: 5px;
                margin-top: 10px;
                display: flex;
                flex-wrap: wrap;
                flex-direction: column;
                align-items: center;
                text-align: center;
            ">
                <h4 style="margin-bottom: 10px; width: 100%; text-align: center;">Legend ({selected_col}):</h4>
                <div style="width: 100%; display: flex; flex-wrap: wrap; justify-content: center;">
                {''.join([f'<span style="margin: 0 5px; color: #{color[0]:02x}{color[1]:02x}{color[2]:02x};'
                          f'">&#x25A0;</span><span>{category}</span>' for category, color in category_color_map.items()])}
                 </div>
            </div>
            """

            # Add the legend to the PyDeck deck
            st.pydeck_chart(r)
            st.markdown(legend_html, unsafe_allow_html=True)
    loaded_df = st.session_state.get("loaded_df")
    if isinstance(loaded_df, pd.DataFrame) and not loaded_df.empty:
        st.dataframe(loaded_df)
    else:
        st.info("No data loaded yet. Select one or more datasets from the sidebar.")

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

        # Short app name
        app = active_app.name
        st.session_state["apps_path"] = str(active_app.parent)
        st.session_state["app"] = app

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

        # Initialize session state
        if "datadir" not in st.session_state:
            st.session_state["datadir"] = env.AGILAB_EXPORT_ABS

        page()

    except Exception as e:
        st.error(f"An error occurred: {e}")
        import traceback

        st.code(traceback.format_exc())


# -------------------- Main Entry Point -------------------- #
if __name__ == "__main__":
    main()
