import os
import sys
import streamlit as st
import tomli
import tomli_w
from pydantic import ValidationError
import socket
import datetime
from pathlib import Path
from flight_trajectory import FlightTrajectoryArgs


def change_data_source():
    """
    Change the data source by deleting 'path' and 'files' keys from the session state if they exist.
    """
    st.session_state.pop('path', None)
    st.session_state.pop('files', None)


def initialize_defaults(app_settings):
    """
    Initialize default parameters for the application settings.

    Args:
        app_settings (dict): A dictionary containing the application settings.

    Returns:
        dict: A dictionary containing the updated default parameters.
    """
    args_default = app_settings.get('args', {})
    defaults = {'path': '~/data/flight_trajectory', 'flight_id': 1, 'data_out':
        '~/data/flight_trajectory/dataframe', 'data_dir':
        '~/data/flight_trajectory/dataset', 'beam_file': 'beams.csv', 'sat_file':
        'satellites.csv', 'waypoints': 'waypoints.geojson',
        'yaw_angular_speed': 1.0, 'roll_angular_speed': 3.0,
        'pitch_angular_speed': 2.0, 'vehicule_acceleration': 5.0,
        'max_speed': 900.0, 'max_roll': 30.0, 'max_pitch': 12.0,
        'target_climbup_pitch': 8.0, 'pitch_enable_speed_ratio': 0.3,
        'altitude_loss_speed_treshold': 400.0, 'landing_speed_target': 
        200.0, 'descent_pitch_target': -3, 'landing_pitch_target': 3,
        'cruising_pitch_max': 3, 'descent_alt_treshold_landing': 500,
        'max_speed_ratio_while_turining': 0.8, 'enable_climb': False,
        'enable_descent': False, 'default_alt_value': 4000.0}
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
    args_default = app_settings.get('args', {})
    args_default = initialize_defaults(app_settings)
result = st.session_state.env.check_args(FlightTrajectoryArgs, args_default)
if result:
    st.warning('\n'.join(result) + f'\nplease check {app_settings_file}')
    st.session_state.pop('is_args_from_ui', None)
st.session_state['flight_id'] = 0
st.session_state['path'] = '~/data/flight_trajectory'
st.session_state['beam_file'] = 'beams.csv'
st.session_state['sat_file'] = 'satellites.csv'
c6, c7, c8, c9, c10 = st.columns(5)
with c6:
    st.text_input(label='Data Dir', value=args_default['data_dir'], key=
        'data_dir')
with c7:
    st.text_input(label='Waypoints File', value=args_default['waypoints'],
        key='waypoints')
with c8:
    st.number_input(label='Yaw Angular Speed', value=args_default[
        'yaw_angular_speed'], key='yaw_angular_speed', step=0.1, format=
        '%.2f', min_value=0.0)
with c9:
    st.number_input(label='Roll Angular Speed', value=args_default[
        'roll_angular_speed'], key='roll_angular_speed', step=0.1, format=
        '%.2f', min_value=0.0)
with c10:
    st.number_input(label='Pitch Angular Speed', value=args_default[
        'pitch_angular_speed'], key='pitch_angular_speed', step=0.1, format
        ='%.2f', min_value=0.0)
c11, c12, c13, c14, c15 = st.columns(5)
with c11:
    st.number_input(label='Vehicule Acceleration', value=args_default[
        'vehicule_acceleration'], key='vehicule_acceleration', step=0.1,
        format='%.2f', min_value=0.0)
with c12:
    st.number_input(label='Max Speed', value=args_default['max_speed'], key
        ='max_speed', step=1.0, format='%.1f', min_value=0.0)
with c13:
    st.number_input(label='Max Roll', value=args_default['max_roll'], key=
        'max_roll', step=0.1, format='%.2f', min_value=0.0, max_value=180.0)
with c14:
    st.number_input(label='Max Pitch', value=args_default['max_pitch'], key
        ='max_pitch', step=0.1, format='%.2f', min_value=0.0, max_value=90.0)
with c15:
    st.number_input(label='Target Climbup Pitch', value=args_default[
        'target_climbup_pitch'], key='target_climbup_pitch', step=0.1,
        format='%.2f', min_value=0.0, max_value=90.0)
c16, c17, c18, c19, c20 = st.columns(5)
with c16:
    st.number_input(label='Pitch Enable Speed Ratio', value=args_default[
        'pitch_enable_speed_ratio'], key='pitch_enable_speed_ratio', step=
        0.01, format='%.2f', min_value=0.0, max_value=1.0)
with c17:
    st.number_input(label='Altitude Loss Speed Treshold', value=
        args_default['altitude_loss_speed_treshold'], key=
        'altitude_loss_speed_treshold', step=1.0, format='%.1f', min_value=0.0)
with c18:
    st.number_input(label='Landing Speed Target', value=args_default[
        'landing_speed_target'], key='landing_speed_target', step=1.0,
        min_value=0.0)
with c19:
    st.number_input(label='Descent Pitch Target', value=args_default[
        'descent_pitch_target'], key='descent_pitch_target', step=0.1,
        min_value=-90.0, max_value=90.0)
with c20:
    st.number_input(label='Landing Pitch Target', value=args_default[
        'landing_pitch_target'], key='landing_pitch_target', step=0.1,
        min_value=-90.0, max_value=90.0)
c21, c22, c23, c24, c25 = st.columns(5)
with c21:
    st.number_input(label='Cruising Pitch Max', value=args_default[
        'cruising_pitch_max'], key='cruising_pitch_max', step=0.1, format=
        '%.2f', min_value=0.0, max_value=90.0)
with c22:
    st.number_input(label='Descent Alt Treshold Landing', value=
        args_default['descent_alt_treshold_landing'], key=
        'descent_alt_treshold_landing', step=1, min_value=0)
with c23:
    st.number_input(label='Max Speed Ratio While Turning', value=
        args_default['max_speed_ratio_while_turining'], key=
        'max_speed_ratio_while_turining', step=0.01, format='%.2f',
        min_value=0.0, max_value=1.0)
with c24:
    st.number_input(label='Default Alt Value', value=args_default[
        'default_alt_value'], key='default_alt_value', step=1.0, format=
        '%.1f', min_value=0.0)
with c25:
    st.text_input(label='Data Output Dir', value=args_default['data_out'],
        key='data_out')
c26, c27, c28, c29, c30 = st.columns(5)
with c26:
    st.text_input(label='plane type', value=args_default['plane_type'], key
        ='plane_type')
c25, c26 = st.columns(2)
with c25:
    st.checkbox(label='Enable Climb', value=args_default['enable_climb'],
        key='enable_climb')
with c26:
    st.checkbox(label='Enable Descent', value=args_default['enable_descent'
        ], key='enable_descent')
args_from_ui = {'path': st.session_state.path, 'flight_id': st.
    session_state.flight_id, 'data_out': st.session_state.data_out,
    'data_dir': st.session_state.data_dir, 'beam_file': st.session_state.
    beam_file, 'sat_file': st.session_state.sat_file, 'waypoints': st.
    session_state.waypoints, 'yaw_angular_speed': st.session_state.
    yaw_angular_speed, 'roll_angular_speed': st.session_state.
    roll_angular_speed, 'pitch_angular_speed': st.session_state.
    pitch_angular_speed, 'vehicule_acceleration': st.session_state.
    vehicule_acceleration, 'max_speed': st.session_state.max_speed,
    'max_roll': st.session_state.max_roll, 'max_pitch': st.session_state.
    max_pitch, 'target_climbup_pitch': st.session_state.
    target_climbup_pitch, 'pitch_enable_speed_ratio': st.session_state.
    pitch_enable_speed_ratio, 'altitude_loss_speed_treshold': st.
    session_state.altitude_loss_speed_treshold, 'landing_speed_target': st.
    session_state.landing_speed_target, 'descent_pitch_target': st.
    session_state.descent_pitch_target, 'landing_pitch_target': st.
    session_state.landing_pitch_target, 'cruising_pitch_max': st.
    session_state.cruising_pitch_max, 'descent_alt_treshold_landing': st.
    session_state.descent_alt_treshold_landing,
    'max_speed_ratio_while_turining': st.session_state.
    max_speed_ratio_while_turining, 'enable_climb': st.session_state.
    enable_climb, 'enable_descent': st.session_state.enable_descent,
    'default_alt_value': st.session_state.default_alt_value, 'plane_type':
    st.session_state.plane_type}
result = st.session_state.env.check_args(FlightTrajectoryArgs, args_from_ui)
if result:
    st.warning('\n'.join(result))
else:
    st.success('All params are valid\xa0!')
    if args_from_ui != args_default:
        st.session_state.is_args_from_ui = True
        with open(app_settings_file, 'wb') as file:
            st.session_state.app_settings['args'] = args_from_ui
            tomli_w.dump(st.session_state.app_settings, file)
