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
import importlib
from math import sqrt, cos, sin, ceil, pi
import numpy as np
from pathlib import Path
import streamlit as st
import pandas as pd
import argparse
from barviz import Simplex, Collection, Scrawler, Attributes # CAUTION: Place it at the first line to avoid other pagelib import instabilities


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

def _default_active_app() -> Path | None:
    apps_dir = Path(__file__).resolve().parents[4] / "apps"
    if not apps_dir.exists():
        return None
    for candidate in sorted(apps_dir.iterdir()):
        if candidate.is_dir() and candidate.name.endswith("_project"):
            return candidate
    return None


from agi_env import AgiEnv
from agi_env.pagelib import render_logo, find_files, load_df, sidebar_views, on_df_change

var = ["discrete", "continuous", "lat", "long"]
var_default = [0, None]

st.title(":chart_with_downwards_trend: Dimension Reduction")

os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"


# Function to lazily import plotly
def lazy_import_plotly():
    """
    Lazy import Plotly graph objects.

    Returns:
        module: Plotly Graph Objects module.

    Note:
        This function lazily imports the Plotly graph objects module.
    """    
    importlib.import_module('plotly.graph_objects')
    import plotly.graph_objects as go
    return go


# Function to lazily import barviz
def lazy_import_barviz():
    """
    Lazy import necessary modules for barviz visualization.

    Returns:
        tuple: A tuple containing Simplex, Collection, Scrawler, and Attributes classes from the barviz module.
    """    
    importlib.import_module('barviz')
    from barviz import Simplex, Collection, Scrawler, Attributes
    return Simplex, Collection, Scrawler, Attributes


# Function to lazily import keras
def lazy_import_keras():
    """
    Lazy import keras modules and classes.

    Returns:
        tuple: A tuple containing the lazily imported modules and classes from Keras.
    """    
    importlib.import_module('keras')
    from keras import Sequential
    from keras.callbacks import EarlyStopping
    from keras.layers import Dense
    return Sequential, EarlyStopping, Dense


# Function to lazily import sklearn
def lazy_import_sklearn():
    """
    Lazy import sklearn modules for train_test_split and StandardScaler.

    Returns:
        tuple: A tuple containing the train_test_split function and StandardScaler class.
    """    
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler
    return train_test_split, StandardScaler


class ModifiedScrawler(Scrawler):
    """
    A class representing a modified scrawler, extending the Scrawler class.

    Attributes:

        Inherits attributes from the Scrawler class.
    
    Methods:
    
        plot(*stuffs, save_as=None, observed_point=None, format='png'): Plots the data, allowing for additional visualizations to be added.
    
            Args:
                *stuffs: Additional data to be plotted.
                save_as (str): The filename to save the plot as. Default is None.
                observed_point: The observed point to update the center of the plot to. Default is None.
                format (str): The file format for the plot. Default is 'png'.
            
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
        # Simplex, Collection, Scrawler, Attributes = lazy_import_barviz()
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
        go = lazy_import_plotly()
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
        points (list): List of points representing the simplex.
        name (str): The name of the simplex.
        colors (dict): Dictionary mapping colors to points.
        labels (list): List of labels for the points.
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
            points (list, optional): A list of points defining the simplex. If not provided, points will be generated based on n_points.
            name (str, optional): The name of the simplex.
            colors (None or list, optional): The colors of the simplex points.
            labels (None or list, optional): The labels for the simplex points.
            attrs (dict, optional): Additional attributes for the simplex.
            n_points (int, optional): The number of points to generate if points are not provided.

        Attributes:
            version (str): The version of the Simplex object.
            _attrs (Attributes): The attributes of the Simplex object.
            scrawler (ModifiedScrawler): The scrawler object associated with the Simplex.
            labels (list): The labels of the simplex points.
            colors (list): The colors of the simplex points.

        Raises:
            None
        """        
        if not points:
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
        Create points for a simplex in n dimensions.

        Args:
            self: The object instance.
            n (int): The number of dimensions for the simplex.

        Returns:
            numpy array: An array of points representing the simplex in n dimensions.
        """        
        points = []
        phi = pi * (3.0 - sqrt(5.0))
        for i in range(n):
            y = 1 - (i / float(n - 1)) * 2
            radius = sqrt(1 - y * y)
            theta = phi * i
            x = cos(theta) * radius
            z = sin(theta) * radius
            points.append((x, y, z))
        return np.array(points)


@st.cache_resource
def build_AE(data, ndim, ndim_inter, ndim_middle):
    """

    Args:
      data:
      ndim:
      ndim_inter:
      ndim_middle:

    Returns:

    """
    Sequential, EarlyStopping, Dense = lazy_import_keras()
    aek = Sequential()
    es = EarlyStopping(
        "val_loss", min_delta=1e-10, patience=100, verbose=1, restore_best_weights=True
    )
    nlayers_inter = ceil(ndim_middle / 2)
    for _ in range(nlayers_inter):
        aek.add(Dense(ndim_inter, input_dim=ndim, activation="relu"))
    aek.add(Dense(ndim_middle, activation="relu"))
    for _ in range(nlayers_inter):
        aek.add(Dense(ndim_inter, activation="relu"))
    aek.add(Dense(ndim, activation="sigmoid"))
    aek.compile(optimizer="nadam", loss="mse")
    aek.fit(
        data,
        data,
        batch_size=10,
        epochs=30,
        verbose=0,
        callbacks=[es],
        validation_split=0.2,
    )
    return aek


def __normalize_data(data):
    """
    Normalize the data using StandardScaler from Scikit-learn.

    Args:
        data (pd.DataFrame): The input data to be normalized.

    Returns:
        pd.DataFrame: The normalized data with scaled values.

    Raises:
        ImportError: If Scikit-learn is not installed.
        ValueError: If the input data is not a pandas DataFrame.
    """    
    train_test_split, StandardScaler = lazy_import_sklearn()
    scaler = StandardScaler()
    data = data.fillna(0)
    normalized_data = pd.DataFrame(scaler.fit_transform(data), columns=data.columns)
    return normalized_data


def __bary_visualisation(
        df, X, selected_color, selected_name, selected_format, color_data=None
):
    """
    Visualize a barycentric plot based on the input data.

    Args:
        df (DataFrame): Input dataframe containing the data points.
        X (DataFrame): Input dataframe containing the data points for visualization.
        selected_color (str): Name of the selected color feature.
        selected_name (str): Name of the selected feature.
        selected_format (str): Format for the plot.
        color_data (Series, optional): Optional series containing color data.

    Returns:
        None

    Raises:
        None
    """    
    normalized_data = __normalize_data(df)
    numpy_array = normalized_data.values
    barycentric_data = np.exp(numpy_array) / np.sum(
        np.exp(numpy_array), axis=1, keepdims=True
    )
    barycentric_data = pd.DataFrame(barycentric_data)
    if color_data is not None:
        labels = [
            f"Index: {index} | {selected_color}: {color_data.iloc[index]}"
            for index, row in df.iterrows()
        ]
        if color_data.dtypes in ["object", "bool"]:
            color_mapping = {
                color: index for index, color in enumerate(color_data.unique())
            }
            color_array = color_data.map(color_mapping)
            colorscale = "Jet"
        else:
            color_array = color_data
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
    s.attrs.markers_colormap = {"colorscale": ["white", "white"], "cmin": 0, "cmax": 1}
    s.attrs.width = 700
    s.attrs.height = 700
    s.attrs.text_size = 12
    s.plot(c, format=selected_format)
    row_index = st.selectbox("Choose a row:", df.index)
    if color_data is not None:
        st.markdown(f"**{selected_color}:** {color_data.iloc[row_index]}")
    data = {
        "Output": df.iloc[row_index].values,
        "Normalized": normalized_data.iloc[row_index].values,
        "Barycentric Coordinate": barycentric_data.iloc[row_index].values,
    }
    st.table(data)
    st.write("Input:")
    st.write(pd.DataFrame(X.iloc[row_index]).T)


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
    if "df_file" in st.session_state:
        del st.session_state["df_file"]
    if "csv_files" in st.session_state:
        del st.session_state["csv_files"]
    update_var(var_key, widget_key)


def page(env):
    # Lazy import and initial session state setup
    """
    Load and preprocess data, build an autoencoder model, and visualize reduced data.

    This function handles the logic for loading, preprocessing, building an autoencoder model, and visualizing reduced data based on user-selected parameters.

    Raises:
        FileNotFoundError: If the selected data file is not found.
    """

    if "project" not in st.session_state:
        st.session_state["project"] = env.target

    if not "projects" in st.session_state:
        st.session_state["projects"] = env.projects

    sidebar_views()

    # Load the selected DataFrame
    df_file_abs = Path(st.session_state.datadir) / st.session_state.df_file
    try:
        st.session_state["data"] = load_df(df_file_abs)
    except FileNotFoundError:
        st.warning("The selected data file was not found. Please select a valid file.")
        return  # Stop further processing
    #
    # # Check if data is loaded and valid
    if "data" not in st.session_state or st.session_state["data"].empty:
        st.warning("The dataset is empty or could not be loaded. Please select a valid data file.")
        return  # Stop further processing

    # Proceed with the rest of your processing
    if (
            isinstance(st.session_state.data, pd.DataFrame)
            and not st.session_state.data.empty
    ):
        Sequential, EarlyStopping, Dense = lazy_import_keras()
        train_test_split, StandardScaler = lazy_import_sklearn()
        nrows = st.session_state.data.shape[0]
        lines = st.slider(
            "Number of rows:",
            min_value=10,
            max_value=nrows,
            value=nrows // 10,
            step=100,
        )
        if lines >= 0:
            st.session_state.data = st.session_state.data.iloc[:lines, :]
        st.session_state.df_cols = st.session_state.data.columns.tolist()
        X = st.session_state.data.select_dtypes(include=["number"])
        ndim = X.shape[1]
        ndim_inter = round(round(ndim ** 0.9))
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            ndim_middle = st.number_input(
                "Dimension", value=3, step=1, min_value=2, max_value=(ndim - 1)
            )
        with col2:
            selected_color = st.selectbox(
                "Color",
                st.session_state.df_cols,
            )
        with col3:
            selected_name = st.text_input(label="File", value="myfigure")
        with col4:
            selected_format = st.selectbox(
                label="Format", options=["png", "jpeg", "svg", "webp"]
            )
        norm_X = __normalize_data(X)
        y = st.session_state.data[f"{selected_color}"]
        X_train, X_test, y_train, y_test = train_test_split(
            norm_X.values, y, test_size=0.2, random_state=42
        )
        aek = build_AE(X_train, ndim, ndim_inter, ndim_middle)
        aeke = Sequential(aek.layers[: -(ceil(ndim_middle / 2) + 1)])
        X_train_reduit_keras, X_test_reduit_keras = aeke.predict(
            X_train, verbose=0
        ), aeke.predict(X_test, verbose=0)
        lr_df = pd.DataFrame(data=X_train_reduit_keras)
        __bary_visualisation(
            lr_df,
            X,
            selected_color,
            selected_name,
            selected_format,
            color_data=y_train,
        )
    else:
        st.warning("The dataset is invalid or empty. Please select a valid data file.")
        return  # Stop further processing


# -------------------- Main Application Entry -------------------- #
def main():
    """
    Main function to run the application.
    """
    try:
        parser = argparse.ArgumentParser(description="Run the AGI Streamlit View with optional parameters.")
        parser.add_argument("--active-app", type=str, help="Where you store your apps (default is ./)",
                            default=None)
        args, _ = parser.parse_known_args()

        if args.active_app is None:
            env_active_app = os.environ.get("AGILAB_ACTIVE_APP")
            if env_active_app:
                active_app = Path(env_active_app).expanduser()
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
                    active_app = _default_active_app()
        else:
            active_app = Path(args.active_app)

        if active_app is None:
            st.error("Error: Missing mandatory parameter: --active-app")
            sys.exit(1)

        if "coltype" not in st.session_state:
            st.session_state["coltype"] = var[0]

        # Short app name
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


# -------------------- Main Entry Point -------------------- #
if __name__ == "__main__":
    main()
