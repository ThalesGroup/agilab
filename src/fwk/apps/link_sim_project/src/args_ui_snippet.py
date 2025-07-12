import datetime
import getpass
from pathlib import Path
import streamlit as st
import toml
import tomli
import tomli_w
import pandas as pd
import os
import pydeck as pdk
from link_sim import LinkSimArgs
env = st.session_state['env']


def initialize_defaults(app_settings):
    """
    Initialize default parameters for the application settings.

    Args:
        app_settings (dict): A dictionary containing the application settings.

    Returns:
        dict: A dictionary containing the updated default parameters.
    """
    args_default = app_settings.get('args', {})
    defaults = {'path': '~/data/link_sim', 'data_out': '~/data/link_sim/dataframes',
    'data_dir': '~/data/link_sim/dataset', 'data_flight': 'flights',
    'data_sat': 'sat', 'antenna_conf_path': 'plane_conf.json','cloud_heatmap_IVDL':'CloudMapIvdl.npz',
    'cloud_heatmap_sat':'CloudMapSat.npz',
    'services_conf_path':'service.json',
    'output_format': 'parquet'}
    for key, value in defaults.items():
        args_default.setdefault(key, value)
    app_settings['args'] = args_default
    return args_default


app_settings_file = st.session_state.env.app_settings_file
if 'is_args_from_ui' not in st.session_state:
    with open(app_settings_file, 'rb') as f:
        app_settings = tomli.load(f)
    args_default = initialize_defaults(app_settings)
    st.session_state.app_settings = app_settings
else:
    app_settings = st.session_state.app_settings
    args_default = initialize_defaults(app_settings)
result = st.session_state.env.check_args(LinkSimArgs, args_default)
if result:
    st.warning('\n'.join(result) + f'\nplease check {app_settings_file}')
    st.session_state.pop('is_args_from_ui', None)
st.session_state['path'] = '~/data/sat'
c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.text_input(label='Output directory', value=args_default['data_out'],
        key='data_out')
with c2:
    st.text_input(label='Data directory', value=args_default['data_dir'],
        key='data_dir')
with c3:
    st.text_input(label='flight sub-directory', value=args_default[
        'data_flight'], key='data_flight')
with c4:
    st.text_input(label='sat sub-directory', value=args_default['data_sat'],
        key='data_sat')
with c5:
    st.text_input(label='antenna configuration file', value=args_default[
        'plane_conf_path'], key='plane_conf_path')
c6, c7, c8, c9, c10 = st.columns(5)
with c6:
    st.text_input(label='cloud heatmap file for IVDL', value=args_default[
        'cloud_heatmap_IVDL'], key='cloud_heatmap_IVDL')
with c7:
    st.text_input(label='cloud heatmap file for Sat', value=args_default[
        'cloud_heatmap_sat'], key='cloud_heatmap_sat')
with c8:
    st.text_input(label='service configuration file', value=args_default[
        'services_conf_path'], key='services_conf_path')
with c9:
    st.selectbox(label='output format', options=['json', 'parquet'], index=
        ['json', 'parquet'].index(args_default['output_format']), key=
        'output_format')
args_from_ui = {'path': st.session_state.path, 'data_out': st.session_state
    .data_out, 'data_dir': st.session_state.data_dir, 'data_flight': st.
    session_state.data_flight, 'data_sat': st.session_state.data_sat,
    'plane_conf_path': st.session_state.plane_conf_path, 'output_format':
    st.session_state.output_format,'cloud_heatmap_IVDL':st.session_state.cloud_heatmap_IVDL,'cloud_heatmap_sat':st.session_state.cloud_heatmap_sat,"services_conf_path":st.session_state.services_conf_path}
result = st.session_state.env.check_args(LinkSimArgs, args_from_ui)
if result:
    st.warning('\n'.join(result))
else:
    st.success('All params are valid\xa0!')
    if args_from_ui != args_default:
        st.session_state.is_args_from_ui = True
        with open(app_settings_file, 'wb') as file:
            st.session_state.app_settings['args'] = args_from_ui
            tomli_w.dump(st.session_state.app_settings, file)
