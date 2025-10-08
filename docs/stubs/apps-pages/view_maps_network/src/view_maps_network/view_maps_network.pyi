import sys
import streamlit as st
import pandas as pd
import pydeck as pdk
import ast
import networkx as nx
import numpy as np
import plotly.graph_objects as go
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from pathlib import Path
from agi_env import AgiEnv
from agi_env.pagelib import find_files, load_df, render_logo
from typing import Any

def _ensure_repo_on_path(*args: Any, **kwargs: Any) -> Any: ...

MAPBOX_API_KEY = "pk.eyJ1Ijoic2FsbWEtZWxnOSIsImEiOiJjbHkyc3BnbjcwMHE0MmpzM2dyd3RyaDI2In0.9Q5rjICLWC1yThpxSVWX6w"

TERRAIN_IMAGE = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"

SURFACE_IMAGE = f"https://api.mapbox.com/v4/mapbox.satellite/{{z}}/{{x}}/{{y}}@4x.png?access_token={MAPBOX_API_KEY}"

ELEVATION_DECODER = {
    "rScaler": 256,
    "gScaler": 1,
    "bScaler": 1 / 256,
    "offset": -32768,
}

terrain_layer = pdk.Layer(
    "TerrainLayer",
    elevation_decoder=ELEVATION_DECODER,
    texture=SURFACE_IMAGE,
    elevation_data=TERRAIN_IMAGE,
    min_zoom=0,
    max_zoom=23,
    strategy="no-overlap",
    opacity=0.3,
    visible=True,
)

link_colors_plotly = {
    "satcom_link": "rgb(0, 200, 255)",
    "optical_link": "rgb(0, 128, 0)",
    "legacy_link": "rgb(128, 0, 128)",
    "ivbl_link": "rgb(255, 69, 0)",
}

def hex_to_rgba(*args: Any, **kwargs: Any) -> Any: ...

def create_edges_geomap(*args: Any, **kwargs: Any) -> Any: ...

def create_layers_geomap(*args: Any, **kwargs: Any) -> Any: ...

def get_fixed_layout(*args: Any, **kwargs: Any) -> Any: ...

def spiral_layout(*args: Any, **kwargs: Any) -> Any: ...

def convert_to_tuples(*args: Any, **kwargs: Any) -> Any: ...

def parse_edges(*args: Any, **kwargs: Any) -> Any: ...

def filter_edges(*args: Any, **kwargs: Any) -> Any: ...

def bezier_curve(*args: Any, **kwargs: Any) -> Any: ...

def create_network_graph(*args: Any, **kwargs: Any) -> Any: ...

def increment_time(*args: Any, **kwargs: Any) -> Any: ...

def decrement_time(*args: Any, **kwargs: Any) -> Any: ...

def safe_literal_eval(*args: Any, **kwargs: Any) -> Any: ...

def extract_metrics(*args: Any, **kwargs: Any) -> Any: ...

def normalize_values(*args: Any, **kwargs: Any) -> Any: ...

def update_var(*args: Any, **kwargs: Any) -> Any: ...

def update_datadir(*args: Any, **kwargs: Any) -> Any: ...

def page(*args: Any, **kwargs: Any) -> Any: ...

def main(*args: Any, **kwargs: Any) -> Any: ...

def update_var(*args: Any, **kwargs: Any) -> Any: ...

def update_datadir(*args: Any, **kwargs: Any) -> Any: ...
