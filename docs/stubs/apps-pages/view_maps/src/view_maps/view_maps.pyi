import os
import sys
import pandas as pd
import streamlit as st
import plotly.express as px
from pathlib import Path
import argparse
from agi_env import AgiEnv
from agi_env.pagelib import find_files, load_df, update_datadir, initialize_csv_files
from typing import Any

def _ensure_repo_on_path(*args: Any, **kwargs: Any) -> Any: ...

def _default_app(*args: Any, **kwargs: Any) -> Any: ...

var = ["discrete", "continuous", "lat", "long"]

var_default = [0, None]

def continuous(*args: Any, **kwargs: Any) -> Any: ...

def discrete(*args: Any, **kwargs: Any) -> Any: ...

def downsample_df_deterministic(*args: Any, **kwargs: Any) -> Any: ...

def page(*args: Any, **kwargs: Any) -> Any: ...

def main(*args: Any, **kwargs: Any) -> Any: ...
