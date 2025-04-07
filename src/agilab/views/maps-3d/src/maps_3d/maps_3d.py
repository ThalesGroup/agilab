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

from agi_gui.pagelib import (
    env,
)  # CAUTION: Place it at the first line to avoid other pagelib import instabilities
from agi_gui.pagelib import find_files, load_df, render_logo
import traceback
import streamlit as st
import pandas as pd
import pydeck as pdk
from pathlib import Path
import plotly.express as px
import geojson
import random

render_logo(3D Maps and Network Topology Visualization)

# Define variable types and their default indices
var = ["discrete", "continious", "lat", "long", "alt"]
var_default = [0, None]

# Lazy imports and efficient session state initialization
if "datadir" not in st.session_state:
    datadir = env.AGILAB_EXPORT_ABS / env.target
    if not datadir.exists():
        os.mkdir(datadir, exist=True)
    st.session_state["datadir"] = datadir
if "project" not in st.session_state:
    st.session_state["project"] = env.target
if "projects" not in st.session_state:
    st.session_state["projects"] = env.projects
if "datadir" not in st.session_state:
    st.session_state["datadir"] = env.AGILAB_EXPORT_ABS
if "beamdir" not in st.session_state:
    st.session_state["beamdir"] = env.AGILAB_SHARE_ABS / env.target.replace(
        "_project", ""
    )
if "coltype" not in st.session_state:
    st.session_state["coltype"] = var[0]

# List of available color palettes
discreteseqs = ["Plotly", "D3", "G10", "T10", "Alphabet", "Dark24", "Light24"]

# Terrain Layer configuration
MAPBOX_API_KEY = "your-api-key"
TERRAIN_IMAGE = (
    "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
)
SURFACE_IMAGE = f"https://api.mapbox.com/v4/mapbox.satellite/{{z}}/{{x}}/{{y}}@2x.png?access_token={MAPBOX_API_KEY}"
ELEVATION_DECODER = {
    "rScaler": 256,
    "gScaler": 1,
    "bScaler": 1 / 256,
    "offset": -32768,
}

# Define possible names for latitude and longitude columns
possible_latitude_names = ["latitude", "lat", "beam_lat"]
possible_longitude_names = ["longitude", "long", "lng", "beam_long"]


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
    Initialize the CSV files for the session state.

    If 'csv_files' does not exist in the session state or is empty, it will find files in the data directory.
    If 'df_file' does not exist in the session state or is empty, it will set the first CSV file found as the default.

    Args:
        None

    Returns:
        None
    """
    """ """
    if "csv_files" not in st.session_state or not st.session_state["csv_files"]:
        st.session_state["csv_files"] = find_files(st.session_state.datadir)
    if "df_file" not in st.session_state or not st.session_state["df_file"]:
        csv_files_rel = [
            Path(file).relative_to(st.session_state.datadir).as_posix()
            for file in st.session_state.csv_files
        ]
        st.session_state["df_file"] = csv_files_rel[0] if csv_files_rel else None


def initialize_beam_files():
    """Initialize beam CSV files in the session state."""
    if (
            "beam_csv_files" not in st.session_state
            or not st.session_state["beam_csv_files"]
    ):
        st.session_state["beam_csv_files"] = find_files(st.session_state.beamdir)
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
    if "df_file" in st.session_state:
        del st.session_state["df_file"]
    if "csv_files" in st.session_state:
        del st.session_state["csv_files"]
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
    st.sidebar.text_input(
        "Data Directory",
        value=st.session_state.datadir,
        key="input_datadir",
        on_change=update_datadir,
        args=("datadir", "input_datadir"),
    )

    datadir = Path(st.session_state.datadir)

    if not datadir.exists() or not datadir.is_dir():
        st.sidebar.error("Directory not found.")
        st.warning("A valid data directory is required to proceed.")
        return  # Stop further processing

    if st.session_state.datadir:
        datadir = Path(st.session_state.datadir)
        if datadir.exists() and datadir.is_dir():
            st.session_state["csv_files"] = find_files(st.session_state["datadir"])
            if not st.session_state["csv_files"]:
                st.warning(
                    "A dataset is required to proceed. Please added via memu execute/export."
                )
                st.stop()
            csv_files_rel = sorted(
                [
                    Path(file).relative_to(datadir).as_posix()
                    for file in st.session_state.csv_files
                ]
            )
            st.sidebar.selectbox(
                "DataFrame",
                csv_files_rel,
                key="df_file",
                index=(
                    csv_files_rel.index(st.session_state.df_file)
                    if "df_file" in st.session_state
                       and st.session_state.df_file in csv_files_rel
                    else 0
                ),
            )
        else:
            st.sidebar.error("Directory not found")

    st.sidebar.text_input(
        "Polygon Directory",
        value=str(st.session_state.beamdir),
        key="input_beamdir",
        on_change=update_beamdir,
        args=("beamdir", "input_beamdir"),
    )

    # Initialize session state for beam_files if it doesn't exist
    default_beam_files = ["beams.csv"]  # Define your default file here
    if "beam_files" not in st.session_state:
        st.session_state["beam_files"] = default_beam_files

    if st.session_state.beamdir:
        beamdir = Path(st.session_state.beamdir)
        if beamdir.exists() and beamdir.is_dir():
            st.session_state["beam_csv_files"] = find_files(st.session_state["beamdir"])
            beam_csv_files_rel = sorted(
                [
                    Path(file).relative_to(beamdir).as_posix()
                    for file in st.session_state.beam_csv_files
                ]
            )
            st.sidebar.multiselect(
                "Polygon Files",
                beam_csv_files_rel,
                key="beam_files",
                # default=st.session_state["beam_files"],
                on_change=update_var,
                args=("beam_files", "beam_files"),
            )
        else:
            st.warning("Beam directory not found")

    if "beam_files" in st.session_state and st.session_state["beam_files"]:
        st.session_state["dfs_beams"] = {}
        for beam_file in st.session_state["beam_files"]:
            beam_file_abs = Path(st.session_state.beamdir) / beam_file
            st.session_state["dfs_beams"][beam_file] = load_df(
                beam_file_abs, with_index=False
            )

    if "df_file" in st.session_state and st.session_state["df_file"]:
        df_file_abs = Path(st.session_state.datadir) / st.session_state.df_file
        df_file_abs = "~/export/flight_sim/export.csv"
        st.session_state["loaded_df"] = load_df(df_file_abs, with_index=False)

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
            nrows = st.session_state.loaded_df.shape[0]
            lines = st.slider(
                "Select the desired number of points:",
                min_value=10,
                max_value=nrows,
                value=3830,
                step=10,
            )
            if lines >= 0:
                st.session_state.loaded_df = st.session_state.loaded_df.iloc[:lines, :]

            st.session_state.loaded_df.set_index(
                st.session_state.loaded_df.columns[0], inplace=True
            )
            continious_cols = st.session_state.loaded_df.select_dtypes(
                include=["number"]
            ).columns.tolist()
            discrete_cols = st.session_state.loaded_df.select_dtypes(
                include=["object"]
            ).columns.tolist()

            # Identify numerical columns
            date_format = "%Y-%m-%d %H:%M:%S"
            for col in discrete_cols:
                try:
                    pd.to_datetime(
                        st.session_state.loaded_df[col],
                        format=date_format,
                        errors="raise",
                    )
                    discrete_cols.remove(col)
                    continious_cols.append(col)
                except (ValueError, TypeError):
                    pass

            # Initialize an empty DataFrame to store distribution metrics
            c = st.columns(5)
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
                                key="opacity_slider",
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
                key="layer_selection",  # Unique key
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