import os
import sys
import streamlit as st
import pandas as pd
import pydeck as pdk
from pathlib import Path
import plotly.express as px
import geojson
import random
import argparse
from agi_env import AgiEnv
from agi_env.pagelib import find_files, load_df, render_logo, cached_load_df
from typing import Any

def _ensure_repo_on_path(*args: Any, **kwargs: Any) -> Any: ...

def _default_app(*args: Any, **kwargs: Any) -> Any: ...

discreteseqs = ["Plotly", "D3", "G10", "T10", "Alphabet", "Dark24", "Light24"]

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

possible_latitude_names = ["latitude", "lat", "beam_lat"]

possible_longitude_names = ["longitude", "long", "lng", "beam_long"]

def generate_random_colors(*args: Any, **kwargs: Any) -> Any: ...

def initialize_csv_files(*args: Any, **kwargs: Any) -> Any: ...

def initialize_beam_files(*args: Any, **kwargs: Any) -> Any: ...

def continious(*args: Any, **kwargs: Any) -> Any: ...

def discrete(*args: Any, **kwargs: Any) -> Any: ...

def update_var(*args: Any, **kwargs: Any) -> Any: ...

def update_datadir(*args: Any, **kwargs: Any) -> Any: ...

def update_beamdir(*args: Any, **kwargs: Any) -> Any: ...

def get_category_color_map(*args: Any, **kwargs: Any) -> Any: ...

def get_palette(*args: Any, **kwargs: Any) -> Any: ...

def hex_to_rgb(*args: Any, **kwargs: Any) -> Any: ...

def poly_geojson_to_csv(*args: Any, **kwargs: Any) -> Any: ...

def move_to_data(*args: Any, **kwargs: Any) -> Any: ...

def downsample_df_deterministic(*args: Any, **kwargs: Any) -> Any: ...

def page(*args: Any, **kwargs: Any) -> Any: ...

def main(*args: Any, **kwargs: Any) -> Any: ...
