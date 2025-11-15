"""Streamlit form for configuring Flight Trajectory arguments."""
from __future__ import annotations
from pathlib import Path
import streamlit as st
from pydantic import ValidationError
from agi_env.pagelib import diagnose_data_directory
from agi_env.streamlit_args import load_args_state, persist_args, render_form
import flight_clone as args_module
from flight_clone import ArgsModel
env = st.session_state._env
defaults_model, defaults_payload, settings_path = load_args_state(env,
    args_module=args_module)
if not st.session_state.get('toggle_edit', False):
    data_col, config_col = st.columns(2)
    share_root = Path(getattr(env, 'agi_share_dir', env.home_abs))
    with data_col:
        num_flights = st.number_input('Number of flights', value=int(
            defaults_model.num_flights), min_value=1, step=1)
        source_options = ['file', 'hawk']
        try:
            source_index = source_options.index(defaults_model.data_source)
        except ValueError:
            source_index = 0
        data_source = st.selectbox('Data source', options=source_options,
            index=source_index)
        data_in = st.text_input('Inputs dir' if data_source == 'file' else
            'Hawk cluster data_in', value=str(defaults_model.data_in), help
            =
            f'Workers read from {share_root}/<path>; keep this relative unless you need an absolute override.'
            )
        data_out = st.text_input('Outputs dir', value=str(defaults_model.
            data_out or f'{defaults_model.data_in}/dataframe'), help=
            f'Outputs will be written under {share_root}/<path> next to the dataset.'
            )
        beam_file = st.text_input('Beam definition file', value=
            defaults_model.beam_file)
        sat_file = st.text_input('Satellite catalog', value=defaults_model.
            sat_file)
        waypoints = st.text_input('Waypoints GeoJSON', value=defaults_model
            .waypoints)
        regenerate_waypoints = st.checkbox('Regenerate waypoints at runtime',
            value=bool(getattr(defaults_model, 'regenerate_waypoints', 
            False)), help=
            'When enabled, rebuilds waypoints.geojson from the bundled Ukraine transport corridors before execution.'
            )
        plane_type = st.text_input('Plane type', value=defaults_model.
            plane_type)
        dataset_format = st.selectbox('Dataset output format', options=[
            'csv', 'parquet'], index=['csv', 'parquet'].index(
            defaults_model.dataset_format) if defaults_model.dataset_format in
            ['csv', 'parquet'] else 0, help=
            'Choose the format used for generated telemetry dataframes.')
    with config_col:
        yaw_speed = st.number_input('Yaw angular speed (°/s)', value=float(
            defaults_model.yaw_angular_speed), step=0.1)
        roll_speed = st.number_input('Roll angular speed (°/s)', value=
            float(defaults_model.roll_angular_speed), step=0.1)
        pitch_speed = st.number_input('Pitch angular speed (°/s)', value=
            float(defaults_model.pitch_angular_speed), step=0.1)
        vehicule_acc = st.number_input('Vehicle acceleration (m/s²)', value
            =float(defaults_model.vehicule_acceleration), step=0.5)
        max_speed = st.number_input('Max speed (km/h)', value=float(
            defaults_model.max_speed), step=10.0)
        default_alt = st.number_input('Default altitude (m)', value=float(
            defaults_model.default_alt_value), step=100.0)
    col1, col2, col3 = st.columns(3)
    with col1:
        max_roll = st.number_input('Max roll (°)', value=float(
            defaults_model.max_roll), step=1.0)
        target_climb_pitch = st.number_input('Target climb pitch (°)',
            value=float(defaults_model.target_climbup_pitch), step=0.5)
        cruising_pitch = st.number_input('Cruising pitch max (°)', value=
            float(defaults_model.cruising_pitch_max), step=0.5)
        descent_altitude_threshold = st.number_input(
            'Descent alt threshold (m)', value=int(defaults_model.
            descent_altitude_threshold_landing), step=50)
    with col2:
        max_pitch = st.number_input('Max pitch (°)', value=float(
            defaults_model.max_pitch), step=0.5)
        pitch_speed_ratio = st.number_input('Pitch enable speed ratio',
            value=float(defaults_model.pitch_enable_speed_ratio), step=0.05)
        landing_pitch = st.number_input('Landing pitch target (°)', value=
            float(defaults_model.landing_pitch_target), step=0.5)
        speed_ratio_turn = st.number_input('Max speed ratio while turning',
            value=float(defaults_model.max_speed_ratio_while_turining),
            step=0.05)
    with col3:
        altitude_loss_threshold = st.number_input(
            'Altitude loss speed threshold', value=float(defaults_model.
            altitude_loss_speed_threshold), step=10.0)
        landing_speed = st.number_input('Landing speed target (km/h)',
            value=float(defaults_model.landing_speed_target), step=5.0)
        descent_pitch = st.number_input('Descent pitch target (°)', value=
            float(defaults_model.descent_pitch_target), step=0.5)
    enable_col, descent_col = st.columns(2)
    with enable_col:
        enable_climb = st.checkbox('Enable climb phase', value=bool(
            defaults_model.enable_climb))
    with descent_col:
        enable_descent = st.checkbox('Enable descent phase', value=bool(
            defaults_model.enable_descent))
    if data_source == 'file':
        directory = share_root / data_in
        if not directory.is_dir():
            diagnosis = diagnose_data_directory(directory)
            if not diagnosis:
                diagnosis = (
                    f"The provided data_in '{directory}' is not a valid directory. If this location is a shared file mount, the shared file server may be down."
                    )
            st.error(diagnosis)
            st.stop()
    candidate_args = {'num_flights': int(num_flights), 'data_source': 
        data_source.strip() or defaults_model.data_source, 'data_in':
        data_in, 'data_out': data_out, 'beam_file': beam_file, 'sat_file':
        sat_file, 'waypoints': waypoints, 'regenerate_waypoints': bool(
        regenerate_waypoints), 'yaw_angular_speed': float(yaw_speed),
        'roll_angular_speed': float(roll_speed), 'pitch_angular_speed':
        float(pitch_speed), 'vehicule_acceleration': float(vehicule_acc),
        'max_speed': float(max_speed), 'max_roll': float(max_roll),
        'max_pitch': float(max_pitch), 'target_climbup_pitch': float(
        target_climb_pitch), 'pitch_enable_speed_ratio': float(
        pitch_speed_ratio), 'altitude_loss_speed_threshold': float(
        altitude_loss_threshold), 'landing_speed_target': float(
        landing_speed), 'descent_pitch_target': float(descent_pitch),
        'landing_pitch_target': float(landing_pitch), 'cruising_pitch_max':
        float(cruising_pitch), 'descent_altitude_threshold_landing': int(
        descent_altitude_threshold), 'max_speed_ratio_while_turining':
        float(speed_ratio_turn), 'enable_climb': bool(enable_climb),
        'enable_descent': bool(enable_descent), 'default_alt_value': float(
        default_alt), 'plane_type': plane_type, 'dataset_format':
        dataset_format}
else:
    candidate_args = render_form(defaults_model)
    if 'num_flights' in candidate_args:
        candidate_args['num_flights'] = int(candidate_args['num_flights'])
try:
    parsed = ArgsModel(**candidate_args)
except ValidationError as exc:
    messages = env.humanize_validation_errors(exc)
    st.warning('\n'.join(messages))
    st.session_state.pop('is_args_from_ui', None)
else:
    persist_args(args_module, parsed, settings_path=settings_path,
        defaults_payload=defaults_payload)
    st.success('All params are valid!')
