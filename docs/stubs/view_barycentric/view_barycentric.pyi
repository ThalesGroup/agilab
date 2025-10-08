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
import argparse
from agi_env import AgiEnv
from agi_env.pagelib import sidebar_views, find_files, load_df, on_project_change, select_project, JumpToMain, update_datadir, \
    initialize_csv_files, update_var
from typing import Any

def _ensure_repo_on_path(*args: Any, **kwargs: Any) -> Any: ...

def _default_app(*args: Any, **kwargs: Any) -> Any: ...

var = ["discrete", "continuous", "lat", "long"]

var_default = [0, None]

class ModifiedScrawler(Scrawler):
    def plot(self, *args: Any, **kwargs: Any) -> Any: ...

class ModifiedSimplex(Simplex):
    def __init__(self, *args: Any, **kwargs: Any) -> Any: ...
    def __create_simplex_points(self, *args: Any, **kwargs: Any) -> Any: ...

def __normalize_data(*args: Any, **kwargs: Any) -> Any: ...

def __bary_visualisation(*args: Any, **kwargs: Any) -> Any: ...

def page(*args: Any, **kwargs: Any) -> Any: ...

def main(*args: Any, **kwargs: Any) -> Any: ...
