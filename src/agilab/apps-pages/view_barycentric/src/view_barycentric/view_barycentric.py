# SPDX-License-Identifier: BSD-3-Clause AND MIT
#
# Portions of this file are adapted from “barviz / barviz-mod”
#   Copyright (c) 2022 Jean-Luc Parouty
#   Licensed under the MIT License (see LICENSES/LICENSE-MIT-barviz-mod)
#
# Additional modifications:
#   Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS FRANCE SAS
#   Licensed under the BSD 3-Clause License (see LICENSE)
#
# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS FRANCE SAS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS FRANCE SAS, may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import os
import sys
import math
import numpy as np
from pathlib import Path
import pandas as pd
import toml as toml
import plotly.graph_objects as go
from barviz import Simplex, Collection, Scrawler, Attributes
from math import sqrt, cos, sin
import streamlit as st
from sklearn.preprocessing import StandardScaler
from scipy.signal import savgol_filter
import argparse


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
    apps_dir = Path(__file__).resolve().parents[4] / "apps"
    if not apps_dir.exists():
        return None
    for candidate in sorted(apps_dir.iterdir()):
        if candidate.is_dir() and candidate.name.endswith("_project"):
            return candidate
    return None


from agi_env import AgiEnv
from agi_env.pagelib import sidebar_views, find_files, load_df, on_project_change, select_project, JumpToMain, update_datadir, \
    initialize_csv_files, update_var

var = ["discrete", "continuous", "lat", "long"]
var_default = [0, None]

st.title(":chart_with_upwards_trend: Barycentric Graph")


class ModifiedScrawler(Scrawler):
    """
    A class representing a modified version of a scrawler.

    Attributes:
        simplex (Scrawler): The scrawler object.
        fig (plotly.graph_objs.Figure): The plotly figure object.

    Methods:
        plot(*stuffs, save_as=None, observed_point=None, format='png'): Plot method for creating visualizations.

    Args:
        *stuffs: Variable length arguments for additional data to plot.
        save_as (str): The filename to save the plot as. Default is None.
        observed_point: The observed point to update the center to. Default is None.
        format (str): The format for saving the plot. Default is 'png'.

    Returns:
        None
    """    
    """ """

    def plot(self, *stuffs, save_as=None, observed_point=None, format="png"):
        """

        Args:
          *stuffs:
          save_as: (Default value = None)
          observed_point: (Default value = None)
          format: (Default value = 'png')

        Returns:

        """
        attrs = self.simplex.attrs
        renderer = attrs.renderer
        skeleton = self.simplex.get_skeleton()
        traces = self._trace_collection(skeleton)
        config = {
            "toImageButtonOptions": {
                "format": format,
                "filename": self.simplex.name,
                "width": attrs.width,
                "height": attrs.height,
                "scale": attrs.save_scale,
            }
        }
        if stuffs is not None:
            for c in stuffs:
                traces.extend(self._trace_collection(c))
        fig = go.Figure(data=[*traces])
        if observed_point is not None:
            self.update_center(observed_point)
        fig.update_layout(self._get_layout())
        st.plotly_chart(fig, config=config, renderer=renderer)
        self.fig = fig
        self.plot_save(save_as)


class ModifiedSimplex(Simplex):
    """
    A class representing a modified simplex.

    Attributes:
        points (list): List of points that define the simplex.
        name (str): The name of the simplex.
        colors (list): List of colors for the simplex.
        labels (list): List of labels for the simplex.
        attrs (dict): Dictionary of attributes for the simplex.
        n_points (int): The number of points in the simplex.
    """    
    """ """

    def __init__(
            self,
            points=[],
            name="unknown",
            colors=None,
            labels=None,
            attrs={},
            n_points=None,
    ):
        """
        Initialize a Simplex object.

        Args:
            points (list, optional): A list of points that define the simplex. Defaults to an empty list.
            name (str, optional): The name of the simplex. Defaults to 'unknown'.
            colors (list, optional): A list of colors for the simplex. Defaults to None.
            labels (list, optional): A list of labels for the points of the simplex. Defaults to None.
            attrs (dict, optional): A dictionary of attributes for the simplex. Defaults to an empty dictionary.
            n_points (int, optional): The number of points to generate for the simplex. If provided, points will be generated automatically based on this value.

        Raises:
            None

        Returns:
            None
        """        
        if n_points is not None:
            points = self.__create_simplex_points(n_points)
        super(Simplex, self).__init__(points, name, colors, labels, attrs)
        self.version = Simplex.version
        self._attrs = Attributes(attrs, Simplex._attributes_default)
        self.scrawler = ModifiedScrawler(self)
        if labels is None:
            self.labels = [f"P{i}" for i in range(self.nbp)]
        if colors is None:
            self.colors = [i for i in range(self.nbp)]
        if self.attrs.markers_colormap["cmax"] is None:
            self.attrs.markers_colormap["cmax"] = self.nbp - 1
        if self.attrs.lines_colormap["cmax"] is None:
            self.attrs.lines_colormap["cmax"] = self.nbp - 1

    def __create_simplex_points(self, n):
        """
        Create a set of points forming a simplex in 3D space.

        Args:
            n (int): The number of points to generate.

        Returns:
            numpy.ndarray: An array of 3D points forming a simplex.

        Note:
            The points are generated using a phi value calculated based on the golden ratio.

        Raises:
            None
        """        
        points = []
        phi = math.pi * (3.0 - sqrt(5.0))
        for i in range(n):
            y = 1 - (i / float(n - 1)) * 2
            radius = sqrt(1 - y * y)
            theta = phi * i
            x = cos(theta) * radius
            z = sin(theta) * radius
            points.append((x, y, z))
        return np.array(points)


def __normalize_data(data):
    """
    Normalize the input data using StandardScaler.

    Args:
        data (DataFrame): Input data to be normalized.

    Returns:
        DataFrame: Normalized data using StandardScaler.

    Raises:
        None
    """    
    scaler = StandardScaler()
    data = data.fillna(0)
    normalized_data = pd.DataFrame(scaler.fit_transform(data), columns=data.columns)
    return normalized_data


def _maybe_smooth_long_column(df: pd.DataFrame) -> None:
    """
    Apply a Savitzky-Golay filter to the 'long' column when sufficient data exists.
    """
    if "long" not in df.columns:
        return

    long_numeric = pd.to_numeric(df["long"], errors="coerce")
    valid_mask = long_numeric.notna()
    valid_count = int(valid_mask.sum())
    if valid_count < 5:
        return

    # Choose an odd window length no larger than 21 and not exceeding valid_count
    window_length = min(21, valid_count if valid_count % 2 else valid_count - 1)
    if window_length < 5:
        window_length = 5
    if window_length > valid_count:
        window_length = valid_count if valid_count % 2 else valid_count - 1
    if window_length < 3:
        return

    polyorder = 2 if window_length > 3 else 1

    try:
        smoothed_values = savgol_filter(long_numeric[valid_mask], window_length=window_length, polyorder=polyorder)
    except ValueError:
        # Fall back to no smoothing if the parameters are incompatible
        return

    df.loc[valid_mask, "long"] = smoothed_values


def __bary_visualisation(df, selected_format, selected_name, selected_x1, selected_x2, color=None):
    """
    Visualize barycentric coordinates using a simplex plot.

    Args:
        df (DataFrame): The input DataFrame with the data to visualize.
        selected_format (str): The selected format for visualization.
        selected_name (str): The selected name for visualization.
        selected_x1 (str): The selected x-axis parameter for visualization.
        selected_x2 (str): The selected y-axis parameter for visualization.
        color (str): Optional parameter for color coding.

    Returns:
        None

    Raises:
        JumpToMain: If an exception occurs while trying to update the visualization.

    Notes:
        This function visualizes barycentric coordinates using a simplex plot, with optional color coding based on a specified parameter.
        The input DataFrame should contain the data to be visualized.
    """    
    normalized_data = __normalize_data(df)
    numpy_array = normalized_data.values
    barycentric_data = np.exp(numpy_array) / np.sum(
        np.exp(numpy_array), axis=1, keepdims=True
    )
    barycentric_data = pd.DataFrame(barycentric_data, columns=df.columns)

    if color is not None:
        color_df = st.session_state.loaded_df[color]
        labels = [
            (
                    f"Index: {index} | "
                    " | ".join(
                        f"{selected_x2}: {col} | {selected_x1}: {val}"
                        for col, val in row.items()
                        if pd.notna(val)
                    )
                    + f" | {color}: {color_df.iloc[index]}"
            )
            for index, row in df.iterrows()
            if pd.notna(index) and isinstance(index, int)
        ]
        if color_df.dtypes in ["object", "bool"]:
            color_mapping = {
                color: index for index, color in enumerate(color_df.unique())
            }
            color_array = color_df.map(color_mapping)
            colorscale = "Jet"
        else:
            color_array = color_df.values
            colorscale = "Blues"
        cmin = np.min(color_array)
        cmax = np.max(color_array)
        c = Collection(points=barycentric_data, labels=labels, colors=color_array)
        c.attrs.markers_colormap = {
            "colorscale": colorscale,
            "cmin": cmin,
            "cmax": cmax,
        }
    else:
        labels = [
            (
                f"Index: {index} | {' | '.join(f'{col}: {val}' for col, val in row.items())}"
            )
            for index, row in df.iterrows()
        ]
        c = Collection(points=barycentric_data, labels=labels)
        c.attrs.markers_colormap = {
            "colorscale": ["blue", "blue"],
            "cmin": 0,
            "cmax": 1,
        }

    c.attrs.markers_opacity = 1
    c.attrs.markers_size = 3
    c.attrs.markers_border_width = 0
    s = ModifiedSimplex(
        n_points=df.shape[1], name=selected_name, labels=df.columns.tolist()
    )
    s.attrs.lines_visible = False
    s.attrs.markers_size = 3
    s.attrs.markers_colormap = {
        "colorscale": ["white", "white"],
        "cmin": 0,
        "cmax": 1,
    }
    s.attrs.width = 700
    s.attrs.height = 700
    s.attrs.text_size = 12
    st.header(f"{selected_x1} per {selected_x2}")
    s.plot(c, format=selected_format)

    try:
        st.write(st.session_state.loaded_df[[f"{selected_x2}", f"{selected_x1}"]].T)
    except Exception as e:
        # st.error(f"```{str(e)}```")
        JumpToMain(e)

    tables = [f"Normalized {selected_x1}", "Barycentric coordinates"]
    selected_table = st.selectbox(
        label="Data", label_visibility="hidden", options=tables
    )
    if selected_table == tables[0]:
        st.write(normalized_data)
    else:
        st.write(barycentric_data)


def page(env):
    # Initialize session state
    """
    Page function for displaying data visualization tools.

    This function sets up the data directory, project, and visualization parameters for the user interface.

    Returns:
        None

    Raises:
        None
    """

    if "project" not in st.session_state:
        st.session_state["project"] = env.target

    if "projects" not in st.session_state:
        st.session_state["projects"] = env.projects

    datadir = Path(st.session_state.datadir)
    # Data directory input
    st.sidebar.text_input(
        "Data Directory",
        value=str(st.session_state.datadir),
        key="input_datadir",
        on_change=update_datadir,
        args=("datadir", "input_datadir"),
    )

    if not datadir.exists() or not datadir.is_dir():
        st.sidebar.error("Directory not found.")
        st.warning("A valid data directory is required to proceed.")
        return  # Stop further processing

    # Find CSV files in the data directory
    st.session_state["csv_files"] = find_files(st.session_state["datadir"])
    if not st.session_state["csv_files"]:
        st.warning("A dataset is required to proceed. Please added via memu execute/export.")
        st.stop()  # Stop further processing

    # Prepare list of CSV files relative to the data directory
    csv_files_rel = sorted(
        [
            Path(file).relative_to(datadir).as_posix()
            for file in st.session_state["csv_files"]
        ]
    )

    # DataFrame selection
    st.sidebar.selectbox(
        label="DataFrame",
        options=csv_files_rel,
        key="df_file",
        index=(
            csv_files_rel.index(st.session_state.df_file)
            if "df_file" in st.session_state
               and st.session_state.df_file in csv_files_rel
            else 0
        ),
        # on_change=update_var,
        args=("df_file"),
    )

    # Check if a DataFrame has been selected
    if not st.session_state.get("df_file"):
        st.warning("Please select a dataset to proceed.")
        return  # Stop further processing

    # Load the selected DataFrame
    df_file_abs = Path(st.session_state.datadir) / st.session_state.df_file
    try:
        st.session_state["loaded_df"] = load_df(df_file_abs, with_index=True)
    except Exception as e:
        st.error(f"Error loading data: {e}")
        st.warning("The selected data file could not be loaded. Please select a valid file.")
        return  # Stop further processing

    # Check if data is loaded and valid
    if (
            "loaded_df" not in st.session_state
            or not isinstance(st.session_state.loaded_df, pd.DataFrame)
            or not st.session_state.loaded_df.shape[1] > 0
    ):
        st.warning("The dataset is empty or could not be loaded. Please select a valid data file.")
        return  # Stop further processing


    if "df_file" in st.session_state and st.session_state["df_file"]:
        df_file_abs = Path(st.session_state.datadir) / st.session_state.df_file
        st.session_state["loaded_df"] = load_df(df_file_abs)

    if "loaded_df" in st.session_state:
        if (
                isinstance(st.session_state.loaded_df, pd.DataFrame)
                and not st.session_state.loaded_df.empty
        ):
            nrows = st.session_state.loaded_df.shape[0]
            lines = st.slider(
                "Number of rows:",
                min_value=10,
                max_value=nrows,
                value=nrows // 10,
                step=100,
            )
            if lines >= 0:
                st.session_state.loaded_df = st.session_state.loaded_df.iloc[:lines, :]

            _maybe_smooth_long_column(st.session_state.loaded_df)

            if "project" in st.session_state:
                st.markdown(f"{env.target} worker arguments:")
                settings = toml.load(env.app_settings_file)
                current_filename = Path(__file__).stem
                # set default values
                if current_filename in settings:
                    st.session_state["variables"] = settings[current_filename][
                        "variables"
                    ]

                # Get the list of column names from the loaded DataFrame.
                st.session_state.df_cols = st.session_state.loaded_df.columns.tolist()

                numeric_cols = []
                for col in st.session_state.df_cols:
                    try:
                        # Use the DataFrame (loaded_df) to access the column.
                        st.session_state.loaded_df[col].astype(float)
                        numeric_cols.append(col)
                    except Exception:
                        # If conversion fails, skip the column.
                        pass

                # st.write("Columns that can be converted to float:", numeric_cols)

                if "variables" in st.session_state:
                    default_x1 = st.session_state.variables[0]
                    default_x2 = st.session_state.variables[1]
                    default_color = st.session_state.variables[2]
                else:
                    default_x1 = st.session_state.df_cols[0]
                    default_x2 = st.session_state.df_cols[0]
                    default_color = st.session_state.df_cols[0]

                col1, col2, col3 = st.columns(3)

                with col1:
                    selected_x1 = st.selectbox(
                        "Correlated variables pair",
                        numeric_cols,
                        index=(
                            st.session_state.df_cols.index(default_x1)
                            if default_x1 in st.session_state.df_cols
                            else 0
                        ),
                    )
                    selected_x2 = st.selectbox(
                        "Correlated variables",
                        numeric_cols,
                        label_visibility="collapsed",
                        index=(
                            st.session_state.df_cols.index(default_x2)
                            if default_x2 in st.session_state.df_cols
                            else 0
                        ),
                    )
                with col2:
                    selected_color = st.selectbox(
                        "Color",
                        st.session_state.df_cols,
                        index=(
                            st.session_state.df_cols.index(default_color)
                            if default_color in st.session_state.df_cols
                            else 0
                        ),
                    )
                with col3:
                    selected_name = st.text_input(label="File", value="myfigure")
                    selected_format = st.selectbox(
                        label="Format",
                        label_visibility="collapsed",
                        options=["jpeg", "png", "svg", "webp"],
                        index=0
                    )

                if selected_x1 and selected_x2 and selected_color:
                    pivot_df = st.session_state.loaded_df.drop_duplicates(
                        subset=[selected_x1]
                    )
                    pivot_df = pivot_df.dropna(subset=[selected_x1, selected_x2])
                    pivot_df = pivot_df.pivot(columns=selected_x1, values=selected_x2)

                    if pivot_df.shape[1] > 1:
                        __bary_visualisation(pivot_df,
                                             selected_format,
                                             selected_name,
                                             selected_x1,
                                             selected_x2,
                                             color=selected_color)
                    else:
                        st.info(
                            f"Error: only 1 distinct value for {selected_x2}. To plot this graph, there must be at "
                            f"least 2 different values for {selected_x2} in the provided dataset."
                            f"Select more rows, or choose another correlated variable."
                        )


# -------------------- Main Application Entry -------------------- #
def main():
    """
    Main function to run the application.
    """
    try:
        """
        Main function to run the application.
        """
        try:
            parser = argparse.ArgumentParser(description="Run the AGI Streamlit View with optional parameters.")
            parser.add_argument("--active-app", dest="active_app", type=str,
                                help="Active app path (e.g. src/agilab/apps/flight_project)", default=None)
            args, _ = parser.parse_known_args()

            if args.active_app is None:
                env_app = os.environ.get("AGILAB_APP")
                if env_app:
                    active_app = Path(env_app).expanduser()
                else:
                    active_app = None
                    candidate_file = Path("~/.local/share/agilab/.agilab-path").expanduser()
                    if candidate_file.is_file():
                        with candidate_file.open("r", encoding="utf-8") as f:
                            agilab_path = f.read()
                            before, sep, _ = agilab_path.rpartition(".venv")
                            potential = Path(before) / "apps" / "flight_project"
                            if potential.exists():
                                active_app = potential
                    if active_app is None:
                        active_app = _default_app()
            else:
                active_app = Path(args.active_app)

            if active_app is None:
                st.error("Error: Missing mandatory parameter: --active-app")
                sys.exit(1)

            if "coltype" not in st.session_state:
                st.session_state["coltype"] = var[0]

            # Short app name (e.g., 'flight_project')
            app = active_app.name
            st.session_state["apps_dir"] = str(active_app.parent)

            env = AgiEnv(
                apps_dir=active_app.parent,
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

            page(env)

        except Exception as e:
            st.error(f"An error occurred: {e}")
            import traceback

            st.error(traceback.format_exc())

    except Exception as e:
        st.error(f"An error occurred: {e}")
        import traceback

        st.error(traceback.format_exc())


# -------------------- Main Entry Point -------------------- #
if __name__ == "__main__":
    main()
