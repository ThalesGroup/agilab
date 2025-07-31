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

from agilab.pagelib import find_files, load_df, update_datadir, initialize_csv_files
import pandas as pd
import streamlit as st
import plotly.express as px
from pathlib import Path

st.title(":world_map: Cartography Visualisation")
env = st.session_state['env']
# Initialize session state
if "datadir" not in st.session_state:
    st.session_state["datadir"] = env.AGILAB_EXPORT_ABS

var = ["discrete", "continuous", "lat", "long"]
var_default = [0, None]


def continuous():
    """Set coltype to 'continuous'."""
    st.session_state["coltype"] = "continuous"


def discrete():
    """Set coltype to 'discrete'."""
    st.session_state["coltype"] = "discrete"


if "coltype" not in st.session_state:
    st.session_state["coltype"] = var[0]  # Default to 'discrete'


# def update_var(var_key, widget_key):
#     """
#     Update a variable in session state.
#
#     Args:
#       var_key: The key of the variable to update.
#       widget_key: The key of the widget whose value will be used.
#     """
#     st.session_state[var_key] = st.session_state[widget_key]

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

def page():
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
    if 'env' not in st.session_state:
        st.error("The application environment is not initialized. Please click on  AGILAB.")
        st.stop()
    else:
        env = st.session_state['env']

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
        value=st.session_state.GUI_NROW,
        step=10,
    )
    st.session_state.GUI_NROW = lines
    if lines >= 0:
        st.session_state.loaded_df = st.session_state.loaded_df.iloc[:lines, :]

    df = st.session_state.loaded_df

    # Select numeric columns
    numeric_cols = st.session_state.loaded_df.select_dtypes(include=["number"]).columns.tolist()

    # Define lists to store continuous and discrete numeric variables
    continuous_cols = []
    discrete_numeric_cols = []

    # Define a threshold: if a numeric column has fewer unique values than this threshold,
    # treat it as discrete. Adjust this value based on your needs.
    unique_threshold = 10

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

    if st.session_state.get("lat") and st.session_state.get("long"):
        if st.session_state.get("coltype") and st.session_state.get(st.session_state["coltype"]):
            if discreteseq:
                # Get the color sequence
                color_sequence = getattr(px.colors.qualitative, discreteseq)
                fig = px.scatter_mapbox(
                    st.session_state.loaded_df,
                    lat=st.session_state.lat,
                    lon=st.session_state.long,
                    zoom=2.5,
                    color_discrete_sequence=color_sequence,
                    color=st.session_state[st.session_state.coltype],
                )
            elif colorscale:
                fig = px.scatter_mapbox(
                    st.session_state.loaded_df,
                    lat=st.session_state.lat,
                    lon=st.session_state.long,
                    zoom=2.5,
                    color_continuous_scale=colorscale,
                    color=st.session_state[st.session_state.coltype],
                )
            else:
                fig = px.scatter_mapbox(
                    st.session_state.loaded_df,
                    lat=st.session_state.lat,
                    lon=st.session_state.long,
                    zoom=2.5,
                )

            fig.update_layout(mapbox_style="open-street-map")
            fig.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0})

            st.plotly_chart(fig, use_container_width=True, theme="streamlit")
        else:
            st.warning("Please select a valid column for coloring.")
    else:
        st.warning("Latitude and Longitude columns are required for the map.")


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

        st.code(traceback.format_exc())


# -------------------- Main Entry Point -------------------- #
if __name__ == "__main__":
    main()