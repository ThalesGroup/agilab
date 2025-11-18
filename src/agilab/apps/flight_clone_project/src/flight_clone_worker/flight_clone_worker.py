import getpass
import glob
import os
import re
import traceback
import warnings
from collections import defaultdict
from datetime import datetime as dt
from pathlib import Path

from agi_node.polars_worker import PolarsWorker
from agi_node.agi_dispatcher import BaseWorker
warnings.filterwarnings('ignore')
import polars as pl
import math
import pandas as pd
import numpy as np
from geopy.distance import geodesic
from geopy.distance import distance as Geodistance
from geopy.point import Point
import json
import logging
from types import SimpleNamespace

import plotly.express as px
import plotly.graph_objects as go
from matplotlib import path as mpath

from flight_clone import FlightCloneArgs

try:
    from sat_trajectory_worker import (
        DEFAULT_EPOCH,
        TLEEntry,
        compute_trajectory,
        load_tle_catalog,
    )
except ImportError:  # pragma: no cover - optional dependency at runtime
    try:
        # Local shim bundled with the worker package
        from flight_clone_worker import sat_trajectory_worker as _satellite_fallback
    except ImportError:
        # When invoked top-level (no package context), fall back to sibling module
        import sat_trajectory_worker as _satellite_fallback

    DEFAULT_EPOCH = _satellite_fallback.DEFAULT_EPOCH
    TLEEntry = _satellite_fallback.TLEEntry
    compute_trajectory = _satellite_fallback.compute_trajectory
    load_tle_catalog = _satellite_fallback.load_tle_catalog

logger = logging.getLogger(__name__)


class _MutableNamespace(SimpleNamespace):

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)


class plane_trajectory:
    df_col_names = ['plane_id', 'time_s', 'speed_ms', 'alt_m', 'roll_deg',
        'pitch_deg', 'yaw_deg', 'bearing_deg', 'latitude', 'longitude',
        'distance', 'phase', 'plane_type']

    def __init__(self, flight_id: int=1, waypoints: list=[(0, 0, 0), (1, 0,
        10000), (2, 1, 9000), (3, 3, 5000), (-3, -3, 5000)],
        yaw_angular_speed: float=1.0, roll_angular_speed: float=3.0,
        pitch_angular_speed: float=2.0, vehicle_acceleration: float=5.0,
        max_speed: float=900.0, max_roll: float=30.0, max_pitch: float=12.0,
        target_climbup_pitch: float=8.0, pitch_enable_speed_ratio: float=
        0.3, altitude_loss_speed_threshold: float=400.0,
        landing_speed_target: float=200.0, descent_pitch_target: float=-3,
        landing_pitch_target: float=3, cruising_pitch_max: float=3,
        descent_altitude_threshold_landing: float=500,
        max_speed_ratio_while_turining: float=0.3, enable_climb: bool=True,
        enable_descent: bool=True, default_alt_value: float=4000.0,
        plane_type: str='classique_plane'):
        self.speed = 0
        self.alt = 0
        self.roll = 0
        self.pitch = 0
        self.yaw = 0
        self.bearing = 0
        self.distance = 0
        self.current_waypoint_index = 1
        self.time = 0
        self.enable_climb = enable_climb
        self.enable_descent = enable_descent
        self.flight_id = flight_id
        self.waypoints = waypoints
        if len(self.waypoints) < 2:
            raise ValueError(
                f'Expected at least 2 waypoints, but got {len(self.waypoints)}'
                )
        else:
            for i in range(len(self.waypoints)):
                if len(self.waypoints[i]) < 2:
                    raise ValueError(
                        f'Expected at least 2 coords (lat,lon) but got {len(self.waypoints[i])} args at index {i}'
                        )
                if len(self.waypoints[i]) < 3:
                    self.waypoints[i] = self.waypoints[i][1], self.waypoints[i
                        ][0], default_alt_value
                else:
                    self.waypoints[i] = self.waypoints[i][1], self.waypoints[i
                        ][0], self.waypoints[i][2]
        self.coords = list(self.waypoints[0][:2])
        self.yaw_angular_speed = yaw_angular_speed
        self.roll_angular_speed = roll_angular_speed
        self.pitch_angular_speed = pitch_angular_speed
        self.vehicle_acceleration = vehicle_acceleration
        self.max_speed_kmh = max_speed
        self.target_speed_m_s = max_speed * 1000 / 3600
        self.target_altitude_m = self.waypoints[1][2]
        self.max_roll = max_roll
        self.max_pitch = max_pitch
        self.cruising_pitch_max = cruising_pitch_max
        self.plane_type = plane_type
        self.pitch_enable_speed_ratio = pitch_enable_speed_ratio
        self.pitch_enable_speed_m_s = (self.pitch_enable_speed_ratio * self
            .target_speed_m_s)
        self.waypoint_arrival_threshold_m = self.target_speed_m_s / 2
        self.vehicle_deceleration = vehicle_acceleration * 1.2
        self.landing_speed_kmh = landing_speed_target
        self.landing_speed_m_s = landing_speed_target * 1000 / 3600
        self.stall_speed_threshold_kmh = altitude_loss_speed_threshold
        self.stall_speed_threshold_m_s = (altitude_loss_speed_threshold * 
            1000 / 3600)
        self.descent_pitch_target_deg = descent_pitch_target
        self.descent_altitude_threshold_landing_m = (
            descent_altitude_threshold_landing)
        self.landing_pitch_target_deg = landing_pitch_target
        self.climb_pitch_target_deg = target_climbup_pitch
        self.max_speed_ratio_while_turning = max_speed_ratio_while_turining
        if not enable_climb:
            self.alt = self.waypoints[0][2]
            self.speed = self.target_speed_m_s
            self.bearing = self.calculate_bearing(tuple(self.coords), tuple
                (self.waypoints[1][:2]))
        min_distance = self.get_min_waypoints_distance()
        for idx in range(1, len(waypoints)):
            lat1, lon1, _ = waypoints[idx - 1]
            lat2, lon2, _ = waypoints[idx]
            distance = self.haversine_distance(lat1, lon1, lat2, lon2)
            if distance < min_distance:
                print(
                    f'Distance between waypoint {idx - 1} and {idx}: {distance:.2f}m'
                    )
                raise ValueError(
                    f'Waypoints #{idx - 1} and #{idx} are too close: {distance:.2f}m < {min_distance:.2f}m, change their positions or decrease the max speed'
                    )

    def __str__(self):
        return f"""TrajectoryLogger(
  time = {self.time} s
  speed = {self.speed} m/s
  alt = {self.alt} m
  roll = {self.roll}°
  pitch = {self.pitch}°
  yaw = {self.yaw}°
  bearing = {self.bearing}°
  coords = {self.coords}
  waypoints = {self.waypoints}
  yaw_angular_speed = {self.yaw_angular_speed}°/s
  roll_angular_speed = {self.roll_angular_speed}°/s
  pitch_angular_speed = {self.pitch_angular_speed}°/s
  vehicule_acceleration = {self.vehicle_acceleration} m/s²
  max_speed = {self.max_speed_kmh} km/h ({self.target_speed_m_s:.2f} m/s)
  Alt_Target = {self.target_altitude_m} m
  max_roll = {self.max_roll}°
  max_pitch = {self.max_pitch}°
)"""
    __repr__ = __str__

    def calculate_bearing(self, coord1, coord2):
        """
        Calculate the compass bearing from coord1 to coord2.

        This function computes the initial bearing (also called forward azimuth) that
        you would follow from the start coordinate to reach the end coordinate on
        the Earth's surface, assuming a spherical Earth model.

        The bearing is calculated clockwise from the north direction (0° to 360°).

        Parameters:
            coord1 (tuple): Latitude and longitude of the start point (degrees).
            coord2 (tuple): Latitude and longitude of the end point (degrees).

        Returns:
            float: Bearing angle in degrees from North (0° to 360°).

        Math:
            - Converts lat/lon to radians.
            - Uses spherical trigonometry formulas to compute bearing:
                x = sin(delta_longitude) * cos(lat2)
                y = cos(lat1)*sin(lat2) - sin(lat1)*cos(lat2)*cos(delta_longitude)
            - Bearing = atan2(x, y) converted to degrees and normalized to [0,360).
        """
        lat1_rad = math.radians(coord1[0])
        lat2_rad = math.radians(coord2[0])
        diff_long_rad = math.radians(coord2[1] - coord1[1])
        x = math.sin(diff_long_rad) * math.cos(lat2_rad)
        y = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad
            ) * math.cos(lat2_rad) * math.cos(diff_long_rad)
        initial_bearing_rad = math.atan2(x, y)
        initial_bearing_deg = math.degrees(initial_bearing_rad)
        compass_bearing = (initial_bearing_deg + 360) % 360
        return compass_bearing

    def estimate_level_off_alt_gain(self):
        """
        Estimate the altitude gained during the aircraft's pitch reduction phase.

        This method estimates how much altitude the aircraft will gain while
        reducing its pitch angle from the current pitch to zero (level flight),
        assuming constant pitch angular speed and target speed.

        Returns:
            float: Estimated altitude gain in meters during leveling off.

        Math:
            - Time to level off is current pitch divided by pitch angular speed.
            - Average pitch during leveling is assumed to be half the initial pitch.
            - Vertical speed component is target speed * sin(average pitch).
            - Estimated altitude gain = vertical speed * time to level.
        """
        if self.pitch <= 0 or self.pitch_angular_speed <= 1e-06:
            return 0
        time_to_level = self.pitch / self.pitch_angular_speed
        avg_pitch_deg = self.pitch / 2.0
        avg_pitch_rad = math.radians(avg_pitch_deg)
        predict_speed = self.target_speed_m_s
        avg_vertical_speed = predict_speed * math.sin(avg_pitch_rad)
        estimated_gain = avg_vertical_speed * time_to_level
        return estimated_gain

    def simulate_takeoff_and_climb(self, dt=1.0, pitch_threshold=0.05):
        """
        Simulate the aircraft's takeoff roll, climb phase, and predictive level-off.

        The simulation uses geographic coordinates (latitude/longitude) and updates
        aircraft state every dt seconds. It transitions through three phases:
        - Takeoff Roll: aircraft accelerates on runway with zero pitch.
        - Climb: aircraft climbs at maximum pitch until near target altitude.
        - Level Off: aircraft reduces pitch to level flight near target altitude.

        Inputs:
            dt (float): Time step for simulation update (seconds).
            pitch_threshold (float): Pitch angle threshold to consider leveling complete (degrees).

        Returns:
            pd.DataFrame: A DataFrame logging the aircraft state at each time step with
                columns for time, speed, altitude, roll, pitch, yaw, bearing, position, etc.

        Math and Logic:
            - Uses pitch angular speed and vehicle acceleration to update pitch and speed.
            - Calculates vertical and horizontal speed components from pitch.
            - Updates geographic position using geopy's geodesic destination.
            - Tracks phase transitions based on speed and altitude.
        """
        print(
            f'--- Starting Takeoff Roll, Climb & Predictive Level Off Simulation ---'
            )
        print(
            f'Using Geographic Coordinates (Lat/Lon). Pitch enabled > {self.pitch_enable_speed_m_s:.1f} m/s'
            )
        print(
            f'Target Alt: {self.target_altitude_m} m, Target Speed: {self.target_speed_m_s:.2f} m/s, Max Pitch: {self.max_pitch}°'
            )
        print(
            f'-----------------------------------------------------------------------'
            )
        log_entries = []
        time_elapsed = 0
        phase = 'Takeoff Roll'
        level_off_initiated = False
        pitch_enabled = False
        if len(self.waypoints) > 1:
            self.bearing = self.calculate_bearing(self.coords, self.
                waypoints[1][:2])
            self.yaw = self.bearing
            print(
                f'Initial bearing calculated using class method: {self.bearing:.2f}°'
                )
        else:
            print(
                'Warning: Only one checkpoint. Cannot calculate bearing. Setting to 0.'
                )
            self.bearing = 0
            self.yaw = 0
        while True:
            predicted_altitude_gain = 0.0
            trigger_altitude = self.target_altitude_m
            if not pitch_enabled and self.speed >= self.pitch_enable_speed_m_s:
                print(
                    f'Time {time_elapsed:.1f}s: Speed ({self.speed:.1f} m/s) reached threshold ({self.pitch_enable_speed_m_s:.1f} m/s). Pitch enabled.'
                    )
                pitch_enabled = True
                phase = 'Climb'
            if phase == 'Takeoff Roll':
                target_pitch = 0.0
            elif phase == 'Climb':
                predicted_altitude_gain = self.estimate_level_off_alt_gain()
                trigger_altitude = (self.target_altitude_m -
                    predicted_altitude_gain)
                if self.alt >= trigger_altitude:
                    print(
                        f'Time {time_elapsed:.1f}s: Alt ({self.alt:.1f}m) reached trigger ({trigger_altitude:.1f}m) for level off. Initiating Level Off.'
                        )
                    phase = 'Level Off'
                    level_off_initiated = True
                    target_pitch = 0.0
                else:
                    target_pitch = self.max_pitch if pitch_enabled else 0.0
            else:
                target_pitch = 0.0
                level_off_initiated = True
            target_speed = self.target_speed_m_s
            current_pitch_rad = math.radians(self.pitch)
            initial_vs = self.speed * math.sin(current_pitch_rad)
            initial_hs = self.speed * math.cos(current_pitch_rad)
            log_entry = {'plane_id': self.flight_id, 'time_s': time_elapsed,
                'speed_ms': self.speed, 'alt_m': self.alt, 'roll_deg': self
                .roll, 'pitch_deg': self.pitch, 'yaw_deg': self.yaw,
                'bearing_deg': self.bearing, 'latitude': self.coords[0],
                'longitude': self.coords[1], 'distance': self.distance,
                'phase': 'Initial Climb', 'plane_type': self.plane_type}
            log_entries.append(log_entry)
            pitch_error = target_pitch - self.pitch
            delta_pitch = np.clip(pitch_error, -self.pitch_angular_speed *
                dt, self.pitch_angular_speed * dt)
            next_pitch = self.pitch + delta_pitch
            next_pitch = np.clip(next_pitch, -self.climb_pitch_target_deg /
                2, self.climb_pitch_target_deg)
            if self.speed < target_speed:
                delta_speed = self.vehicle_acceleration * dt
                next_speed = min(self.speed + delta_speed * math.sin(math.
                    pi * 0.05 + math.pi * (self.speed / target_speed) * 
                    0.95), target_speed)
            else:
                next_speed = target_speed
            next_pitch_rad = math.radians(next_pitch)
            vertical_speed = next_speed * math.sin(next_pitch_rad)
            horizontal_speed = next_speed * math.cos(next_pitch_rad)
            delta_alt = vertical_speed * dt
            next_alt = self.alt + delta_alt
            if phase != 'Takeoff Roll' and next_alt < 0:
                next_alt = 0
            distance_meters = horizontal_speed * dt
            if distance_meters > 0.001:
                if 'Point' in globals() and 'geodesic' in globals():
                    start_point = Point(latitude=self.coords[0], longitude=
                        self.coords[1])
                    destination = geodesic(meters=distance_meters).destination(
                        point=start_point, bearing=self.bearing)
                    next_coords = [destination.latitude, destination.longitude]
                else:
                    lat1_rad = math.radians(self.coords[0])
                    lon1_rad = math.radians(self.coords[1])
                    bearing_rad = math.radians(self.bearing)
                    earth_radius_m = 6371000
                    ang_dist = distance_meters / earth_radius_m
                    lat2_rad = math.asin(math.sin(lat1_rad) * math.cos(
                        ang_dist) + math.cos(lat1_rad) * math.sin(ang_dist) *
                        math.cos(bearing_rad))
                    lon2_rad = lon1_rad + math.atan2(math.sin(bearing_rad) *
                        math.sin(ang_dist) * math.cos(lat1_rad), math.cos(
                        ang_dist) - math.sin(lat1_rad) * math.sin(lat2_rad))
                    next_coords = [math.degrees(lat2_rad), math.degrees(
                        lon2_rad)]
            else:
                next_coords = list(self.coords)
            self.speed = next_speed
            self.pitch = next_pitch
            self.alt = next_alt
            self.coords = next_coords
            self.yaw = self.bearing
            self.distance += next_speed
            time_elapsed += dt
            if level_off_initiated and abs(self.pitch) < pitch_threshold:
                alt_error = abs(self.alt - self.target_altitude_m)
                print(
                    f'--- Level Off Complete. Pitch ({self.pitch:.2f}°) near zero at time {time_elapsed:.1f}s. Final Alt: {self.alt:.1f}m (Error: {alt_error:.1f}m) ---'
                    )
                final_log_entry = {'plane_id': self.flight_id, 'time_s':
                    time_elapsed, 'speed_ms': self.speed, 'alt_m': self.alt,
                    'roll_deg': self.roll, 'pitch_deg': self.pitch,
                    'yaw_deg': self.yaw, 'bearing_deg': self.bearing,
                    'latitude': self.coords[0], 'longitude': self.coords[1],
                    'distance': self.distance, 'phase': 'Initial Climb',
                    'plane_type': self.plane_type}
                log_entries.append(final_log_entry)
                break
            if time_elapsed > 72000:
                print('Warning: Simulation exceeded maximum time limit (20hr).'
                    )
                final_log_entry = {'plane_id': self.flight_id, 'time_s':
                    time_elapsed, 'speed_ms': self.speed, 'alt_m': self.alt,
                    'roll_deg': self.roll, 'pitch_deg': self.pitch,
                    'yaw_deg': self.yaw, 'bearing_deg': self.bearing,
                    'latitude': self.coords[0], 'longitude': self.coords[1],
                    'distance': self.distance, 'phase': 'Initial Climb',
                    'plane_type': self.plane_type}
                log_entries.append(final_log_entry)
                break
        trajectory_log_df = pd.DataFrame(log_entries)
        trajectory_log_df = trajectory_log_df.reindex(columns=self.df_col_names
            )
        return trajectory_log_df

    def perform_pitch_correction_to_level(self, dt=1.0):
        """
        Gradually adjusts the aircraft's pitch angle back to level (zero).

        This function simulates the pitch correction process where the pitch angle
        approaches zero at a controlled angular speed reduced by a factor of 10.
        During correction, the aircraft's position and altitude are updated accordingly.

        Parameters:
            dt (float): Time step for each simulation iteration in seconds.

        Returns:
            list of dict: Log entries recording the aircraft state at each time step,
            including position, pitch, altitude, and other relevant parameters.

        Explanation:
            - Pitch angle is decreased or increased stepwise towards zero.
            - Horizontal distance traveled is updated based on speed and pitch.
            - Geographic position is updated using geodesic destination calculation.
            - Altitude changes are calculated from vertical component of speed.
        """
        pitch = self.pitch
        pitch_angular_speed = self.pitch_angular_speed / 10
        log_entries = []
        distance_traveled = self.distance
        while True:
            pitch_delta = pitch_angular_speed * dt
            if pitch > 0:
                pitch -= pitch_delta
                if pitch < 0:
                    pitch = 0
            if pitch < 0:
                pitch += pitch_delta
                if pitch > 0:
                    pitch = 0
            horizontal_distance = self.speed * math.cos(math.radians(pitch)
                ) * dt
            distance_traveled += horizontal_distance
            destination = Geodistance(meters=horizontal_distance).destination(
                point=Point(self.coords[0], self.coords[1]), bearing=self.
                bearing)
            self.alt += self.speed * math.sin(math.radians(pitch)) * dt
            self.time += 1
            self.distance = distance_traveled
            self.pitch = pitch
            self.coords[0], self.coords[1
                ] = destination.latitude, destination.longitude
            log_entries.append({'plane_id': self.flight_id, 'time_s': self.
                time, 'speed_ms': self.speed, 'alt_m': self.alt, 'roll_deg':
                self.roll, 'pitch_deg': self.pitch, 'yaw_deg': self.yaw,
                'bearing_deg': self.bearing, 'latitude': self.coords[0],
                'longitude': self.coords[1], 'distance': self.distance,
                'phase': 'Pitch_to_Center', 'plane_type': self.plane_type})
            if pitch == 0:
                break
        return log_entries

    def estimate_altitude_change_for_pitch_correction(self, dt=1.0):
        """
        Estimates total altitude change expected while correcting pitch angle to zero.

        This method simulates the pitch angle reduction towards zero, calculating
        cumulative altitude gain or loss during the pitch correction maneuver.

        Parameters:
            dt (float): Time step in seconds for the pitch correction simulation.

        Returns:
            float: Estimated net altitude change (meters) during pitch correction.
                   Positive values indicate altitude gain; negative values indicate loss.

        Explanation:
            - Simulates gradual pitch angle approach to zero at reduced angular speed.
            - Altitude changes are integrated from vertical speed component at each step.
            - Positive pitch reduces altitude gain; negative pitch reduces altitude.
        """
        pitch = self.pitch
        pitch_angular_speed = self.pitch_angular_speed / 10
        altitude_difference = 0
        while True:
            pitch_delta = pitch_angular_speed * dt
            if pitch > 0:
                pitch -= pitch_delta
                if pitch < 0:
                    pitch = 0
                altitude_difference += self.speed * math.sin(math.radians(
                    pitch)) * dt
            if pitch < 0:
                pitch += pitch_delta
                if pitch > 0:
                    pitch = 0
                altitude_difference -= self.speed * math.sin(math.radians(
                    pitch)) * dt
            if pitch == 0:
                break
        return altitude_difference

    def simulate_cruise_to_waypoint(self, dt=1.0):
        """
        Simulates cruising flight to the current target waypoint with altitude adjustments.

        This function guides the aircraft towards the waypoint, controlling pitch to
        approach the target altitude smoothly, accelerating up to target speed, and
        adjusting position iteratively until close to the waypoint.

        Parameters:
            dt (float): Time step in seconds for each simulation update.

        Returns:
            pd.DataFrame: A DataFrame logging the aircraft state at each step, including
            speed, altitude, pitch, roll, yaw, bearing, coordinates, distance traveled,
            and the current phase.

        Explanation:
            - Calculates bearing to waypoint and adjusts heading.
            - Determines target pitch based on altitude difference and distance.
            - Adjusts pitch up or down to reach target altitude smoothly.
            - Updates speed, position, altitude according to physics.
            - Uses geodesic calculations to update geographic coordinates.
            - Continues until aircraft is within half the target speed distance to waypoint.
        """
        self.bearing = self.calculate_bearing(self.coords, self.waypoints[
            self.current_waypoint_index][:2])
        log_entries = []
        prev_altitude = -1
        prev_delta_altitude = -1
        do_log = True
        adapt_altitude_to_target = True
        distance_to_waypoint = geodesic(tuple(self.coords), self.waypoints[
            self.current_waypoint_index][:2]).meters
        altitude_diff = abs(self.alt - self.waypoints[self.
            current_waypoint_index][2])
        hypotenuse = math.sqrt(altitude_diff ** 2 + distance_to_waypoint ** 2)
        min_angle = abs(math.degrees(math.acos(distance_to_waypoint /
            hypotenuse)))
        if min_angle < self.cruising_pitch_max / 5:
            target_pitch = min_angle * 4
        elif min_angle < self.cruising_pitch_max / 2:
            target_pitch = min_angle * 2
        elif min_angle < self.cruising_pitch_max:
            target_pitch = self.cruising_pitch_max
        elif min_angle < self.max_pitch:
            target_pitch = min_angle
        else:
            target_pitch = min_angle + 4
        pitch_direction_up = self.waypoints[self.current_waypoint_index][2
            ] > self.alt
        while True:
            new_bearing = self.calculate_bearing(self.coords, self.
                waypoints[self.current_waypoint_index][:2])
            yaw_change = new_bearing - self.bearing
            self.bearing = new_bearing
            if self.speed < self.target_speed_m_s:
                speed_increment = self.vehicle_acceleration * dt
                self.speed += speed_increment
                if self.speed > self.target_speed_m_s:
                    self.speed = self.target_speed_m_s
            if adapt_altitude_to_target:
                delta_altitude = abs(self.alt - self.waypoints[self.
                    current_waypoint_index][2])
                if (self.estimate_altitude_change_for_pitch_correction(dt=
                    dt) >= delta_altitude or prev_delta_altitude != -1 and 
                    delta_altitude > prev_delta_altitude):
                    log_entries.extend(self.
                        perform_pitch_correction_to_level(dt=dt))
                    do_log = False
                    adapt_altitude_to_target = False
                    self.pitch = 0
                else:
                    pitch_delta = self.pitch_angular_speed * 0.1 * dt
                    if pitch_direction_up:
                        self.pitch += pitch_delta
                        if self.pitch > target_pitch:
                            self.pitch = target_pitch
                    else:
                        self.pitch -= pitch_delta
                        if self.pitch < -target_pitch:
                            self.pitch = -target_pitch
                    prev_delta_altitude = delta_altitude
            if do_log:
                horizontal_distance = self.speed * math.cos(math.radians(
                    self.pitch)) * dt
                self.distance += horizontal_distance
                destination = Geodistance(meters=horizontal_distance
                    ).destination(point=Point(self.coords[0], self.coords[1
                    ]), bearing=self.bearing)
                self.alt += self.speed * math.sin(math.radians(self.pitch)
                    ) * dt
                self.coords[0], self.coords[1
                    ] = destination.latitude, destination.longitude
                self.time += 1
                log_entries.append({'plane_id': self.flight_id, 'time_s':
                    self.time, 'speed_ms': self.speed, 'alt_m': self.alt,
                    'roll_deg': self.roll, 'pitch_deg': self.pitch,
                    'yaw_deg': yaw_change, 'bearing_deg': self.bearing,
                    'latitude': self.coords[0], 'longitude': self.coords[1],
                    'distance': self.distance, 'phase':
                    f'Cruise to waypoint {self.current_waypoint_index}',
                    'plane_type': self.plane_type})
            else:
                do_log = True
            if geodesic(tuple(self.coords), self.waypoints[self.
                current_waypoint_index][:2]
                ).meters < self.target_speed_m_s / 2:
                break
        self.current_waypoint_index += 1
        trajectory_log_df = pd.DataFrame(log_entries)
        trajectory_log_df = trajectory_log_df.reindex(columns=self.df_col_names
            )
        return trajectory_log_df

    def estimate_descent_distance(self, dt=1.0, target_angle=-3,
        descent_altitude_threshold_landing=500, pitch_angular_speed=1):
        """
        Estimates the horizontal distance required for the aircraft to safely descend
        from its current altitude to the landing threshold altitude, following a specified
        descent pitch angle and speed profile.

        Parameters:
            dt (float): Simulation time step in seconds.
            target_angle (float): Desired descent pitch angle in degrees (negative for descent).
            descent_altitude_threshold_landing (float): Altitude threshold in meters
                at which landing procedures are initiated.
            pitch_angular_speed (float): Angular speed for pitch adjustment during descent.

        Returns:
            float: Estimated horizontal distance in meters needed to complete the descent.

        Explanation:
            - Simulates descent trajectory by iteratively adjusting pitch angle toward target.
            - Models speed reduction when below landing altitude and near stall speeds.
            - Calculates geographic position updates via geodesic calculations.
            - Applies a simplified altitude loss acceleration factor for stall conditions.
            - Stops simulation when altitude reaches zero or below.
        """
        coords = self.coords.copy()
        speed = self.speed
        altitude = self.alt
        distance_traveled = 0
        pitch = self.pitch
        alt_loss_max_acceleration = -1.5 * speed * math.sin(math.radians(
            target_angle)) * dt
        while True:
            new_bearing = self.calculate_bearing(self.coords, self.
                waypoints[self.current_waypoint_index][:2])
            yaw_change = new_bearing - self.bearing
            self.bearing = new_bearing
            if altitude > descent_altitude_threshold_landing:
                if pitch > target_angle:
                    pitch_delta = dt * self.pitch_angular_speed
                    pitch -= pitch_delta
                    pitch = max(pitch, target_angle)
                horizontal_distance = speed * math.cos(math.radians(pitch)
                    ) * dt
                distance_traveled += horizontal_distance
                destination = Geodistance(meters=horizontal_distance
                    ).destination(point=Point(coords[0], coords[1]),
                    bearing=self.bearing)
                altitude += speed * math.sin(math.radians(pitch)) * dt
                coords[0], coords[1
                    ] = destination.latitude, destination.longitude
            else:
                if (pitch < self.landing_pitch_target_deg and speed < self.
                    stall_speed_threshold_m_s):
                    pitch_delta = (dt * self.pitch_angular_speed * 0.1 *
                        pitch_angular_speed)
                    pitch += pitch_delta
                    pitch = min(pitch, self.landing_pitch_target_deg)
                elif pitch < 0 and speed >= self.stall_speed_threshold_m_s:
                    pitch_delta = (dt * self.pitch_angular_speed * 0.1 *
                        pitch_angular_speed)
                    pitch += pitch_delta
                    pitch = min(pitch, 0)
                if speed > self.landing_speed_m_s:
                    deceleration = dt * self.vehicle_deceleration
                    speed_reduction_factor = math.sin(0.1 * math.pi + 0.9 *
                        math.pi * (self.target_speed_m_s - self.
                        landing_speed_m_s - (self.speed - self.
                        landing_speed_m_s)) / (self.target_speed_m_s - self
                        .landing_speed_m_s))
                    speed -= deceleration * speed_reduction_factor
                    speed = max(speed, self.landing_speed_m_s)
                if speed < self.stall_speed_threshold_m_s:
                    altitude -= alt_loss_max_acceleration / (speed - self.
                        landing_speed_m_s + 1)
                horizontal_distance = speed * math.cos(math.radians(pitch)
                    ) * dt
                distance_traveled += horizontal_distance
                destination = Geodistance(meters=horizontal_distance
                    ).destination(point=Point(coords[0], coords[1]),
                    bearing=self.bearing)
                altitude += speed * math.sin(math.radians(pitch)) * dt
                coords[0], coords[1
                    ] = destination.latitude, destination.longitude
                if altitude < 0:
                    altitude = 0
                    break
        return distance_traveled

    def perform_descent(self, dt=1.0, target_angle=-3,
        descent_altitude_threshold_landing=500, pitch_angular_speed=1):
        """
        Simulates the aircraft's descent phase towards the final waypoint, including
        pitch control, speed adjustments, altitude loss, and position updates.

        Parameters:
            dt (float): Time step in seconds for each simulation iteration.
            target_angle (float): Target pitch angle for descent (negative value in degrees).
            descent_altitude_threshold_landing (float): Altitude threshold (meters) to
                modify descent behavior for landing.
            pitch_angular_speed (float): Angular speed for pitch control during descent.

        Returns:
            pd.DataFrame: Log of aircraft states throughout descent, including position,
            speed, pitch, altitude, and phase.

        Explanation:
            - Adjusts pitch angle gradually toward target descent angle.
            - Reduces speed progressively as the aircraft nears landing speed.
            - Models altitude loss due to stall when speed drops below stall threshold.
            - Updates geographic position using geodesic calculations.
            - Continues until altitude reaches zero, indicating landing.
        """
        self.bearing = self.calculate_bearing(self.coords, self.waypoints[-
            1][:2])
        log_entries = []
        speed = self.speed
        altitude = self.alt
        distance_traveled = self.distance
        pitch = self.pitch
        alt_loss_max_acceleration = -1.5 * speed * math.sin(math.radians(
            target_angle)) * dt
        while True:
            new_bearing = self.calculate_bearing(self.coords, self.
                waypoints[self.current_waypoint_index][:2])
            yaw_change = new_bearing - self.bearing
            self.bearing = new_bearing
            if altitude > descent_altitude_threshold_landing:
                if pitch > target_angle:
                    pitch_delta = dt * self.pitch_angular_speed
                    pitch -= pitch_delta
                    pitch = max(pitch, target_angle)
                horizontal_distance = speed * math.cos(math.radians(pitch)
                    ) * dt
                distance_traveled += horizontal_distance
                destination = Geodistance(meters=horizontal_distance
                    ).destination(point=Point(self.coords[0], self.coords[1
                    ]), bearing=self.bearing)
                altitude += speed * math.sin(math.radians(pitch)) * dt
            else:
                if (pitch < self.landing_pitch_target_deg and speed < self.
                    stall_speed_threshold_m_s):
                    pitch_delta = (dt * self.pitch_angular_speed * 0.1 *
                        pitch_angular_speed)
                    pitch += pitch_delta
                    pitch = min(pitch, self.landing_pitch_target_deg)
                elif pitch < 0 and speed >= self.stall_speed_threshold_m_s:
                    pitch_delta = (dt * self.pitch_angular_speed * 0.1 *
                        pitch_angular_speed)
                    pitch += pitch_delta
                    pitch = min(pitch, 0)
                if speed > self.landing_speed_m_s:
                    deceleration = dt * self.vehicle_deceleration
                    speed_reduction_factor = math.sin(0.1 * math.pi + 0.9 *
                        math.pi * (self.target_speed_m_s - self.
                        landing_speed_m_s - (self.speed - self.
                        landing_speed_m_s)) / (self.target_speed_m_s - self
                        .landing_speed_m_s))
                    speed -= deceleration * speed_reduction_factor
                    speed = max(speed, self.landing_speed_m_s)
                if speed < self.stall_speed_threshold_m_s:
                    altitude -= alt_loss_max_acceleration / (speed - self.
                        landing_speed_m_s + 1)
                horizontal_distance = speed * math.cos(math.radians(pitch)
                    ) * dt
                distance_traveled += horizontal_distance
                destination = Geodistance(meters=horizontal_distance
                    ).destination(point=Point(self.coords[0], self.coords[1
                    ]), bearing=self.bearing)
                altitude += speed * math.sin(math.radians(pitch)) * dt
                if altitude < 0:
                    altitude = 0
            self.speed = speed
            self.time += 1
            self.distance = distance_traveled
            self.alt = altitude
            self.pitch = pitch
            self.coords[0], self.coords[1
                ] = destination.latitude, destination.longitude
            log_entries.append({'plane_id': self.flight_id, 'time_s': self.
                time, 'speed_ms': self.speed, 'alt_m': self.alt, 'roll_deg':
                self.roll, 'pitch_deg': self.pitch, 'yaw_deg': yaw_change,
                'bearing_deg': self.bearing, 'latitude': self.coords[0],
                'longitude': self.coords[1], 'distance': self.distance,
                'phase':
                f'Descending to the final waypoint {self.current_waypoint_index}'
                , 'plane_type': self.plane_type})
            if altitude == 0:
                break
        trajectory_log_df = pd.DataFrame(log_entries)
        trajectory_log_df = trajectory_log_df.reindex(columns=self.df_col_names
            )
        return trajectory_log_df

    def cruise_to_destination(self, dt=1.0):
        """
        Controls the aircraft cruise phase toward the final destination waypoint,
        calculating when to initiate descent based on estimated required descent distance.

        Parameters:
            dt (float): Simulation time step in seconds.

        Returns:
            pd.DataFrame: Complete flight log from cruise to final descent, combining
            cruise and descent logs, including positions, speeds, altitudes, and phases.

        Explanation:
            - Calculates the distance required to descend safely using estimate_descent_distance().
            - Adjusts descent parameters if needed to ensure landing within waypoint.
            - Simulates cruise flight until aircraft is within descent initiation distance.
            - Then calls perform_descent() to complete the approach and landing.
            - Logs all states continuously and concatenates cruise and descent data.
        """
        self.bearing = self.calculate_bearing(self.coords, self.waypoints[-
            1][:2])
        log_entries = []
        dist_needed_for_landing = self.estimate_descent_distance(dt=dt,
            target_angle=self.descent_pitch_target_deg,
            descent_altitude_threshold_landing=self.
            descent_altitude_threshold_landing_m, pitch_angular_speed=1)
        distance_to_final_waypoint = geodesic(tuple(self.coords), self.
            waypoints[-1][:2]).meters
        initial_descent_pitch_target = self.descent_pitch_target_deg
        pitch_angular_speed = 1
        if dist_needed_for_landing > distance_to_final_waypoint:
            print(
                'Landing setup with current plane simulation parameters not possible, attempting more aggressive parameters to land at last waypoint'
                )
        while dist_needed_for_landing > distance_to_final_waypoint:
            if self.speed < self.target_speed_m_s:
                speed_increment = self.vehicle_acceleration * dt
                self.speed += speed_increment
                if self.speed > self.target_speed_m_s:
                    self.speed = self.target_speed_m_s
            self.descent_pitch_target_deg -= 1
            self.descent_altitude_threshold_landing_m += 100
            pitch_angular_speed = abs(initial_descent_pitch_target) / abs(self
                .descent_pitch_target_deg)
            dist_needed_for_landing = self.estimate_descent_distance(dt=dt,
                target_angle=self.descent_pitch_target_deg,
                descent_altitude_threshold_landing=self.
                descent_altitude_threshold_landing_m, pitch_angular_speed=
                pitch_angular_speed)
        while True:
            current_distance_to_waypoint = geodesic(tuple(self.coords),
                self.waypoints[-1][:2]).meters
            if current_distance_to_waypoint > dist_needed_for_landing:
                new_bearing = self.calculate_bearing(self.coords, self.
                    waypoints[self.current_waypoint_index][:2])
                yaw_change = new_bearing - self.bearing
                self.bearing = new_bearing
                horizontal_speed = self.speed * math.cos(math.radians(self.
                    pitch))
                self.distance += horizontal_speed * dt
                destination = Geodistance(meters=horizontal_speed * dt
                    ).destination(point=Point(self.coords[0], self.coords[1
                    ]), bearing=self.bearing)
                self.time += 1
                self.coords[0], self.coords[1
                    ] = destination.latitude, destination.longitude
                log_entries.append({'plane_id': self.flight_id, 'time_s':
                    self.time, 'speed_ms': self.speed, 'alt_m': self.alt,
                    'roll_deg': self.roll, 'pitch_deg': self.pitch,
                    'yaw_deg': yaw_change, 'bearing_deg': self.bearing,
                    'latitude': self.coords[0], 'longitude': self.coords[1],
                    'distance': self.distance, 'phase':
                    f'Cruise to last waypoint ({self.current_waypoint_index})',
                    'plane_type': self.plane_type})
            else:
                descent_log_df = self.perform_descent(dt=dt, target_angle=
                    self.descent_pitch_target_deg,
                    descent_altitude_threshold_landing=self.
                    descent_altitude_threshold_landing_m,
                    pitch_angular_speed=pitch_angular_speed)
                break
        trajectory_log_df = pd.DataFrame(log_entries)
        trajectory_log_df = trajectory_log_df.reindex(columns=self.df_col_names
            )
        trajectory_log_df = pd.concat([trajectory_log_df, descent_log_df],
            ignore_index=True)
        return trajectory_log_df

    def calculate_turn_direction_and_angle(self, target_bearing):
        """
        Determines the optimal turn direction (left or right) and the minimal angular
        difference needed to reach the target bearing from the current bearing.

        Parameters:
            target_bearing (float): Target heading bearing in degrees (0-360).

        Returns:
            tuple(bool, float):
                - bool: True if the aircraft should turn right; False if left.
                - float: Angle in degrees representing the smallest rotation needed.

        Explanation:
            - Uses modular arithmetic on bearings (0-360 degrees).
            - Chooses turn direction to minimize angular travel.
            - Accounts for wrap-around at 0/360 degrees.
        """
        bearing_difference = self.bearing - target_bearing
        abs_difference = abs(bearing_difference)
        if abs_difference <= 180:
            turn_right = bearing_difference < 0
            rotation_angle = abs(target_bearing - self.bearing)
        elif bearing_difference > 0:
            turn_right = True
            rotation_angle = abs(self.bearing - 360 - target_bearing)
        else:
            turn_right = False
            rotation_angle = abs(self.bearing + 360 - target_bearing)
        return turn_right, rotation_angle

    def haversine_distance(self, lat1, lon1, lat2, lon2):
        R = 6371000
        phi1 = np.radians(lat1)
        phi2 = np.radians(lat2)
        dphi = np.radians(lat2 - lat1)
        dlambda = np.radians(lon2 - lon1)
        a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(
            dlambda / 2.0) ** 2
        c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
        return R * c

    def estimate_roll_pitch_correction_rotation(self, dt=1.0, current_roll=None
        ):
        """
        Estimates the total angular rotation in degrees the aircraft will undergo while
        correcting its roll angle back to zero by simulating incremental roll adjustments.

        Parameters:
            dt (float): Time step in seconds.
            current_roll (float or None): Optional starting roll angle in degrees;
                if None, uses the aircraft's current roll attribute.

        Returns:
            float: Absolute total rotation in degrees accumulated during roll correction.

        Explanation:
            - Simulates roll angle decay towards zero at a constant angular speed.
            - Calculates cumulative rotation induced by pitch angular speed and roll.
            - Rotation is calculated as the integral of angular increments per dt.
        """
        total_rotation = 0
        roll = self.roll if current_roll is None else current_roll
        while True:
            roll_change = self.roll_angular_speed * dt
            if roll > 0:
                roll -= roll_change
                if roll < 0:
                    roll = 0
            elif roll < 0:
                roll += roll_change
                if roll > 0:
                    roll = 0
            incremental_rotation = self.pitch_angular_speed * abs(roll
                ) / self.max_roll * math.sin(math.radians(roll))
            total_rotation += incremental_rotation
            if roll == 0:
                break
        return abs(total_rotation)

    def perform_roll_pitch_correction(self, dt=1.0):
        """
        Performs roll and pitch correction to stabilize the aircraft's orientation by
        gradually reducing the roll angle to zero, updating pitch accordingly, and
        adjusting the aircraft's bearing, altitude, and position during the maneuver.

        Parameters:
            dt (float): Time step in seconds for each simulation iteration.

        Returns:
            list of dict: A list of log entries capturing the aircraft's state at each
            timestep during the correction process, including position, attitude, speed,
            and phase information.

        Explanation:
            - Roll is incrementally adjusted towards zero at a fixed angular speed.
            - Pitch is computed based on the roll angle and pitch angular speed.
            - Bearing is updated considering the roll-induced angular changes.
            - Altitude changes are limited to avoid unrealistic jumps.
            - Geographic position is updated using geodesic calculations.
            - The process repeats until roll angle reaches zero, indicating level flight.
        """
        log_entries = []
        earth_gravity = 9.807
        while True:
            roll_change = self.roll_angular_speed * dt
            if self.roll > 0:
                self.roll -= roll_change
                if self.roll < 0:
                    self.roll = 0
            elif self.roll < 0:
                self.roll += roll_change
                if self.roll > 0:
                    self.roll = 0
            bearing_increment = self.pitch_angular_speed * abs(self.roll
                ) / self.max_roll * math.sin(math.radians(self.roll))
            self.bearing += bearing_increment
            pitch = self.pitch_angular_speed * abs(self.roll
                ) / self.max_roll * math.cos(math.radians(self.roll))
            self.pitch = pitch
            altitude_increment = self.speed * math.sin(math.radians(pitch)
                ) * dt
            self.alt += min(altitude_increment, 0.5)
            horizontal_distance = self.speed * math.cos(math.radians(pitch)
                ) * dt
            self.distance += horizontal_distance
            destination = Geodistance(meters=horizontal_distance).destination(
                point=Point(self.coords[0], self.coords[1]), bearing=self.
                bearing)
            self.time += 1
            self.coords[0], self.coords[1
                ] = destination.latitude, destination.longitude
            log_entries.append({'plane_id': self.flight_id, 'time_s': self.
                time, 'speed_ms': self.speed, 'alt_m': self.alt, 'roll_deg':
                self.roll, 'pitch_deg': self.pitch, 'yaw_deg': self.yaw,
                'bearing_deg': self.bearing, 'latitude': self.coords[0],
                'longitude': self.coords[1], 'distance': self.distance,
                'phase':
                f'perform Roll-Pitch correction {self.current_waypoint_index}',
                'plane_type': self.plane_type})
            if self.roll == 0:
                break
        return log_entries

    def perform_turn_to_next_waypoint(self, dt=1.0):
        """
        Executes the aircraft's turn maneuver towards the next waypoint by calculating
        turn direction, controlling roll angle, adjusting speed for sharper turns, and
        updating position and orientation over time.

        Parameters:
            dt (float): Time step in seconds for each iteration of the turn simulation.

        Returns:
            pd.DataFrame: A DataFrame log of the aircraft's state at each timestep during
            the turn, including position, attitude, speed, and phase details.

        Explanation:
            - Determines shortest turn direction and rotation angle to target bearing.
            - Modulates speed lower when sharper turns are needed.
            - Adjusts roll angle progressively up to maximum limits based on turn direction.
            - Updates bearing and pitch angles accordingly.
            - Moves aircraft position along updated bearing and speed.
            - Continues until turn angle is less than roll-pitch correction threshold.
        """
        total_rotation = 0
        log_entries = []
        target_bearing = self.calculate_bearing(tuple(self.coords), self.
            waypoints[self.current_waypoint_index])
        turn_right, rotation_needed = self.calculate_turn_direction_and_angle(
            target_bearing)
        speed_ratio = rotation_needed / 180
        target_speed = self.target_speed_m_s * (1 - (1 - self.
            max_speed_ratio_while_turning) * math.sin(speed_ratio))
        while True:
            target_bearing = self.calculate_bearing(tuple(self.coords),
                self.waypoints[self.current_waypoint_index])
            _, rotation_needed = self.calculate_turn_direction_and_angle(
                target_bearing)
            if self.speed > target_speed:
                speed_decrement = dt * self.vehicle_deceleration
                self.speed -= speed_decrement
                if self.speed < target_speed:
                    self.speed = target_speed
            if rotation_needed < self.estimate_roll_pitch_correction_rotation(
                dt=dt):
                log_entries.extend(self.perform_roll_pitch_correction(dt=dt))
                break
            roll_delta = self.roll_angular_speed * dt
            if turn_right:
                self.roll += roll_delta
                if self.roll > self.max_roll:
                    self.roll = self.max_roll
            else:
                self.roll -= roll_delta
                if self.roll < -self.max_roll:
                    self.roll = -self.max_roll
            incremental_rotation = self.pitch_angular_speed * abs(self.roll
                ) / self.max_roll * math.sin(math.radians(self.roll))
            total_rotation += incremental_rotation
            self.bearing += incremental_rotation
            if self.bearing > 360:
                self.bearing -= 360
            if self.bearing < 0:
                self.bearing += 360
            pitch = self.pitch_angular_speed * abs(self.roll
                ) / self.max_roll * math.cos(math.radians(self.roll))
            self.pitch = pitch
            self.alt += min(self.speed * math.sin(math.radians(pitch)) * dt,
                0.5)
            self.distance += self.speed * math.cos(math.radians(pitch)) * dt
            displacement = self.speed * math.cos(math.radians(pitch)) * dt
            destination = Geodistance(meters=displacement).destination(point
                =Point(self.coords[0], self.coords[1]), bearing=self.bearing)
            self.time += 1
            self.coords[0], self.coords[1
                ] = destination.latitude, destination.longitude
            log_entries.append({'plane_id': self.flight_id, 'time_s': self.
                time, 'speed_ms': self.speed, 'alt_m': self.alt, 'roll_deg':
                self.roll, 'pitch_deg': self.pitch, 'yaw_deg': self.yaw,
                'bearing_deg': self.bearing, 'latitude': self.coords[0],
                'longitude': self.coords[1], 'distance': self.distance,
                'phase': f'Turn to waypoint {self.current_waypoint_index}',
                'plane_type': self.plane_type})
        trajectory_log = pd.DataFrame(log_entries)
        trajectory_log = trajectory_log.reindex(columns=self.df_col_names)
        return trajectory_log

    def get_min_waypoints_distance(self, dt=1.0):
        """
        Executes the aircraft's turn maneuver towards the next waypoint,
        controlling roll angle, adjusting speed for sharper turns, and
        updating position and orientation over time. then compute the min distance needed between waypoints.

        Parameters:
            dt (float): Time step in seconds for each iteration of the turn simulation.

        Returns:
            pd.DataFrame: A DataFrame log of the aircraft's state at each timestep during
            the turn, including position, attitude, speed, and phase details.
        """

        def local_calculate_turn_direction_and_angle(bearing, target_bearing):
            bearing_difference = bearing - target_bearing
            abs_difference = abs(bearing_difference)
            if abs_difference <= 180:
                turn_right = bearing_difference < 0
                rotation_angle = abs(target_bearing - bearing)
            elif bearing_difference > 0:
                turn_right = True
                rotation_angle = abs(bearing - 360 - target_bearing)
            else:
                turn_right = False
                rotation_angle = abs(bearing + 360 - target_bearing)
            return turn_right, rotation_angle
        total_rotation = 0
        log_entries = []
        speed = self.target_speed_m_s
        bearing = 0
        yaw = 0
        roll = 0
        pitch = 0
        alt = 10000
        coords = [0, 0]
        distance = 0
        time = 0
        rotation_needed = 180
        turn_right = False
        speed_ratio = rotation_needed / 180
        target_speed = self.target_speed_m_s * (1 - (1 - self.
            max_speed_ratio_while_turning) * math.sin(speed_ratio))
        while True:
            target_bearing = self.calculate_bearing(tuple(coords), [-1, 0, 
                10000])
            _, rotation_needed = local_calculate_turn_direction_and_angle(
                bearing, target_bearing)
            if speed > target_speed:
                speed_decrement = dt * self.vehicle_deceleration
                speed -= speed_decrement
                if speed < target_speed:
                    speed = target_speed
            if rotation_needed < self.estimate_roll_pitch_correction_rotation(
                dt=dt, current_roll=roll):
                break
            roll_delta = self.roll_angular_speed * dt
            if turn_right:
                roll += roll_delta
                if roll > self.max_roll:
                    roll = self.max_roll
            else:
                roll -= roll_delta
                if roll < -self.max_roll:
                    roll = -self.max_roll
            incremental_rotation = self.pitch_angular_speed * abs(roll
                ) / self.max_roll * math.sin(math.radians(roll))
            total_rotation += incremental_rotation
            bearing += incremental_rotation
            if bearing > 360:
                bearing -= 360
            if bearing < 0:
                bearing += 360
            pitch = self.pitch_angular_speed * abs(roll
                ) / self.max_roll * math.cos(math.radians(roll))
            alt += min(speed * math.sin(math.radians(pitch)) * dt, 0.5)
            distance += speed * math.cos(math.radians(pitch)) * dt
            displacement = speed * math.cos(math.radians(pitch)) * dt
            destination = Geodistance(meters=displacement).destination(point
                =Point(coords[0], coords[1]), bearing=bearing)
            coords[0], coords[1] = destination.latitude, destination.longitude
            time += 1
            log_entries.append({'plane_id': self.flight_id, 'time_s': time,
                'speed_ms': speed, 'alt_m': alt, 'roll_deg': roll,
                'pitch_deg': pitch, 'yaw_deg': yaw, 'bearing_deg': bearing,
                'latitude': coords[0], 'longitude': coords[1], 'distance':
                distance, 'phase':
                f'Turn to waypoint {self.current_waypoint_index}',
                'plane_type': self.plane_type})
        trajectory_log = pd.DataFrame(log_entries)
        trajectory_log = trajectory_log.reindex(columns=self.df_col_names)

        def haversine_distance(lat1, lon1, lat2, lon2):
            """
            Compute the Haversine distance between two points in decimal degrees.
            Returns distance in meters.
            """
            R = 6371000
            phi1 = np.radians(lat1)
            phi2 = np.radians(lat2)
            dphi = np.radians(lat2 - lat1)
            dlambda = np.radians(lon2 - lon1)
            a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(
                dlambda / 2.0) ** 2
            c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
            return R * c
        trajectory_log['distance_from_origin_m'] = haversine_distance(0, 0,
            trajectory_log['latitude'].values, trajectory_log['longitude'].
            values)
        return trajectory_log['distance_from_origin_m'].max()

    def plot(self, df):
        """
        Generates 2D plots of altitude, speed, and pitch angle over time during a flight
        phase using Plotly, displaying key flight parameters to visualize performance.

        Parameters:
            df (pd.DataFrame): DataFrame containing logged flight data with columns:
                - 'time_s': time in seconds
                - 'alt_m': altitude in meters
                - 'speed_ms': speed in meters/second
                - 'pitch_deg': pitch angle in degrees
                - plus other columns for context (not all plotted)

        Returns:
            None: Displays interactive plots in the output environment.

        Explanation:
            - Altitude vs Time plot shows altitude changes during the flight phase.
            - Speed vs Time plot includes a horizontal line indicating target speed.
            - Pitch vs Time plot includes a horizontal line indicating max pitch limit.
        """
        print('\nFinal State after Climb:')
        print(self)
        print('\n Trajectory Log Head:')
        print(df.head())
        print('\n Trajectory Log Tail:')
        print(df.tail())
        print('\nPlotting Altitude vs Time...')
        fig_alt = px.line(df, x='time_s', y='alt_m', title=
            'Altitude during Climb Phase')
        fig_alt.update_layout(xaxis_title='Time (seconds)', yaxis_title=
            'Altitude (meters)')
        fig_alt.show()
        fig_spd = px.line(df, x='time_s', y='speed_ms', title=
            'Speed during Climb Phase')
        fig_spd.update_layout(xaxis_title='Time (seconds)', yaxis_title=
            'Speed (m/s)')
        fig_spd.add_hline(y=self.target_speed_m_s, line_dash='dot',
            annotation_text='Target Speed', annotation_position='bottom right')
        fig_spd.show()
        fig_pitch = px.line(df, x='time_s', y='pitch_deg', title=
            'Pitch Angle during Climb Phase')
        fig_pitch.update_layout(xaxis_title='Time (seconds)', yaxis_title=
            'Pitch (degrees)')
        fig_pitch.add_hline(y=self.max_pitch, line_dash='dot',
            annotation_text='Max Pitch', annotation_position='bottom right')
        fig_pitch.show()

    def plot_3d_flight_path(self, df):
        """
        Visualizes the 3D flight path of the aircraft using Plotly, plotting latitude,
        longitude, and altitude with markers colored by altitude and hover information.

        Parameters:
            df (pd.DataFrame): DataFrame containing flight data with required columns:
                'alt_m', 'latitude', 'longitude', 'phase', 'roll_deg', 'pitch_deg',
                'bearing_deg', 'speed_ms'.

        Returns:
            None: Displays an interactive 3D plot of the flight path.

        Explanation:
            - Uses scatter3d with lines and markers colored by altitude.
            - Normalizes axis scales to maintain aspect ratio between lat/lon.
            - Provides detailed hover info for each point including flight phase and attitudes.
        """
        required_columns = ['alt_m', 'latitude', 'longitude', 'phase',
            'roll_deg', 'pitch_deg', 'bearing_deg', 'speed_ms']
        if not all(col in df.columns for col in required_columns):
            raise ValueError(f'DataFrame must contain {required_columns}')
        fig = go.Figure(data=[go.Scatter3d(x=df['longitude'], y=df[
            'latitude'], z=df['alt_m'], mode='lines+markers', marker=dict(
            size=4, color=df['alt_m'], colorscale='Viridis', opacity=0.8),
            line=dict(color='blue', width=2), customdata=df[['phase',
            'roll_deg', 'pitch_deg', 'bearing_deg', 'speed_ms']].values,
            hovertemplate='Longitude: %{x}<br>' + 'Latitude: %{y}<br>' +
            'Altitude: %{z} m<br>' + 'Phase: %{customdata[0]}<br>' +
            'Roll: %{customdata[1]}°<br>' + 'Pitch: %{customdata[2]}°<br>' +
            'Bearing: %{customdata[3]}°<br>' +
            'Speed: %{customdata[4]} m/s<br>' + '<extra></extra>')])
        delta_x = abs(df['longitude'].max() - df['longitude'].min())
        delta_y = abs(df['latitude'].max() - df['latitude'].min())
        delta_z = abs(df['alt_m'].max() - df['alt_m'].min())
        max_base = max(delta_x, delta_y)
        aspect_ratio = dict(x=delta_x / max_base, y=delta_y / max_base, z=0.05)
        fig.update_layout(title='3D Flight Path', scene=dict(xaxis_title=
            'Longitude', yaxis_title='Latitude', zaxis_title='Altitude (m)',
            aspectmode='manual', aspectratio=aspect_ratio), margin=dict(l=0,
            r=0, b=0, t=40))
        fig.show()

    def calculate_trajectory(self, dt=1, plot=False, plot_3D=False):
        """
        Computes the full flight trajectory by simulating takeoff, climb, cruise, turns,
        and descent phases, aggregating the results into a comprehensive flight log.

        Parameters:
            dt (float): Time step in seconds for simulation steps.
            plot (bool): If True, generates 2D plots of altitude, speed, and pitch.
            plot_3D (bool): If True, generates a 3D interactive plot of the flight path.

        Returns:
            pd.DataFrame: Combined DataFrame logging aircraft state through all flight phases,
            including positions, speeds, attitudes, and flight phases.

        Explanation:
            - Simulates takeoff and climb if climb enabled.
            - Simulates turns and cruise legs between waypoints.
            - Optionally simulates descent and landing.
            - Supports visual output for deeper insight into trajectory and flight dynamics.
        """
        if self.enable_climb:
            trajectory_log_df = self.simulate_takeoff_and_climb(dt=dt,
                pitch_threshold=0.05)
            turn_log_df = self.perform_turn_to_next_waypoint(dt=dt)
            trajectory_log_df = pd.concat([trajectory_log_df, turn_log_df],
                ignore_index=True)
        else:
            trajectory_log_df = pd.DataFrame([{'plane_id': self.flight_id,
                'time_s': self.time, 'speed_ms': self.speed, 'alt_m': self.
                alt, 'roll_deg': self.roll, 'pitch_deg': self.pitch,
                'yaw_deg': self.yaw, 'bearing_deg': self.bearing,
                'latitude': self.coords[0], 'longitude': self.coords[1],
                'distance': self.distance, 'phase': 'initial State',
                'plane_type': self.plane_type}])
            trajectory_log_df = trajectory_log_df.reindex(columns=self.
                df_col_names)
        while self.current_waypoint_index < len(self.waypoints) - 1:
            print(
                f'Calculating for waypoint {self.current_waypoint_index} coords: {self.waypoints[self.current_waypoint_index]}'
                )
            cruise_log_df = self.simulate_cruise_to_waypoint(dt=dt)
            trajectory_log_df = pd.concat([trajectory_log_df, cruise_log_df
                ], ignore_index=True)
            turn_log_df = self.perform_turn_to_next_waypoint(dt=dt)
            trajectory_log_df = pd.concat([trajectory_log_df, turn_log_df],
                ignore_index=True)
        if self.enable_descent:
            descent_log_df = self.cruise_to_destination(dt=dt)
            trajectory_log_df = pd.concat([trajectory_log_df,
                descent_log_df], ignore_index=True)
        else:
            cruise_log_df = self.simulate_cruise_to_waypoint(dt=dt)
            trajectory_log_df = pd.concat([trajectory_log_df, cruise_log_df
                ], ignore_index=True)
        if plot:
            self.plot(trajectory_log_df)
        if plot_3D:
            self.plot_3d_flight_path(trajectory_log_df)
        return trajectory_log_df


def haversine(lon1, lat1, lon2, lat2):
    """
    Calculate the great-circle distance between two points
    on the Earth specified by longitude and latitude.
    Returns distance in kilometers.
    """
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(
        dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    R = 6371.0
    return R * c


class FlightCloneWorker(PolarsWorker):
    """Class derived from AgiDataWorker"""
    pool_vars = {}
    _DEFAULT_ARGS = FlightCloneArgs().model_dump(mode='python')
    _SAT_DEFAULT_DURATION = 5400

    def start(self):
        global global_vars
        if not isinstance(self.args, _MutableNamespace):
            payload = self.args if isinstance(self.args, dict) else vars(self
                .args)
            self.args = _MutableNamespace(**payload)
        for key, value in self._DEFAULT_ARGS.items():
            if not hasattr(self.args, key):
                setattr(self.args, key, value)
        source_root = getattr(self.args, 'data_in', None)
        if source_root is None:
            raise ValueError(
                "FlightCloneWorker requires a 'data_in' argument")
        data_paths = self.setup_data_directories(source_path=source_root,
            target_path=getattr(self.args, 'data_out', None), target_subdir
            ='dataframe', reset_target=True)
        self.data_in = data_paths.input_path
        self.data_out = data_paths.output_path
        self.args['data_in'] = data_paths.normalized_input
        self.args['data_out'] = data_paths.normalized_output
        self.waypoints = self.args.waypoints
        self.beam_file = self.args.beam_file
        self.sat_file = self.args.sat_file
        self.flight_label = None
        self.flight_numeric_id = None
        self._beam_paths: dict[str, mpath.Path] = {}
        self._beam_centers: dict[str, tuple[float, float]] = {}
        self._satellite_meta: pd.DataFrame | None = None
        self._sat_track_cache: dict[str, pd.DataFrame] = {}
        self._tle_catalog: dict[str, TLEEntry] = {}
        self._setup_reference_assets()
        logging.info(f'from: {__file__}')
        if self.verbose > 1:
            logging.info(
                f'Worker #{self._worker_id} dataframe root path = {self.data_out}'
                )
        if self.verbose > 0:
            logging.info(f'start worker_id {self._worker_id}\n')
        args = self.args
        self._numeric_counter = 0
        self.pool_vars['args'] = self.args
        self.pool_vars['verbose'] = self.verbose
        global_vars = self.pool_vars

    def work_init(self):
        """Initialize work by reading from shared space."""
        global global_vars
        pass

    def pool_init(self, worker_vars):
        """Initialize the pool with worker variables.

        Args:
            worker_vars (dict): Variables specific to the worker.

        """
        global global_vars
        global_vars = worker_vars

    def work_pool(self, flight_reference):
        """Parse waypoint slices and generate a trajectory dataframe."""
        global global_vars
        args = global_vars['args']
        data_path = Path(BaseWorker.normalize_dataset_path(args['data_in']))

        def _unpack_reference(item):
            if isinstance(item, dict):
                return item.get('flight_index') or item.get('index'), item
            if isinstance(item, (list, tuple)):
                if len(item) == 1:
                    return _unpack_reference(item[0])
                if len(item) >= 2:
                    return item[0], item[1]
            return None, item
        flight_id, waypoint_entry = _unpack_reference(flight_reference)
        inline_feature = None
        if isinstance(waypoint_entry, dict):
            inline_feature = waypoint_entry.get('waypoint_feature')
            waypoint_token = waypoint_entry.get('path') or waypoint_entry.get(
                'absolute_path') or waypoint_entry.get('waypoints_file'
                ) or waypoint_entry.get('waypoints')
        else:
            waypoint_token = waypoint_entry
        if isinstance(waypoint_token, (list, tuple)) and waypoint_token:
            waypoint_token = waypoint_token[0]
        waypoint_path = Path(str(waypoint_token)) if waypoint_token else Path(
            self.waypoints)
        if not waypoint_path.is_absolute():
            waypoint_path = data_path / waypoint_path
        feature = None
        if waypoint_path.exists():
            with open(waypoint_path, 'r') as waypoints_list:
                waypoint_geojson = json.load(waypoints_list)
            features = waypoint_geojson.get('features', [])
            if not features:
                raise ValueError(f'No features found in {waypoint_path}')
            feature = features[0]
        elif inline_feature is not None:
            feature = inline_feature
        else:
            raise FileNotFoundError(waypoint_path)
        coordinates = feature.get('geometry', {}).get('coordinates', [])
        if not coordinates:
            raise ValueError(f'No coordinates found in {waypoint_path}')
        data = coordinates[0] if isinstance(coordinates[0][0], list
            ) else coordinates
        properties = feature.get('properties', {})
        loop_group_size = int(properties.get('loop_group_size', 1) or 1)
        loop_position = int(properties.get('loop_position', 0) or 0)
        looped_data = self._apply_loop_pattern(data, loop_group_size,
            loop_position)
        flight_label = feature.get('properties', {}).get('flight_id')
        resolved_label = flight_label or Path(waypoint_path).stem
        self.flight_label = resolved_label
        try:
            numeric_flight_id = int(flight_id
                ) if flight_id is not None else int(resolved_label)
        except (TypeError, ValueError):
            match = re.match('^(\\\\d+)', str(resolved_label))
            if match:
                numeric_flight_id = int(match.group(1))
            else:
                numeric_flight_id = getattr(self, '_numeric_counter', 0)
                self._numeric_counter = numeric_flight_id + 1
        self.flight_numeric_id = numeric_flight_id
        waypoint_sequence = looped_data
        try:
            plane = plane_trajectory(flight_id=numeric_flight_id, waypoints
                =waypoint_sequence, yaw_angular_speed=args[
                'yaw_angular_speed'], roll_angular_speed=args[
                'roll_angular_speed'], pitch_angular_speed=args[
                'pitch_angular_speed'], vehicle_acceleration=args[
                'vehicule_acceleration'], max_speed=args['max_speed'],
                max_roll=args['max_roll'], max_pitch=args['max_pitch'],
                target_climbup_pitch=args['target_climbup_pitch'],
                pitch_enable_speed_ratio=args['pitch_enable_speed_ratio'],
                altitude_loss_speed_threshold=args[
                'altitude_loss_speed_threshold'], descent_pitch_target=args
                ['descent_pitch_target'], landing_pitch_target=args[
                'landing_pitch_target'], cruising_pitch_max=args[
                'cruising_pitch_max'], descent_altitude_threshold_landing=
                args['descent_altitude_threshold_landing'],
                max_speed_ratio_while_turining=args[
                'max_speed_ratio_while_turining'], enable_climb=args[
                'enable_climb'], enable_descent=args['enable_descent'],
                default_alt_value=args['default_alt_value'], plane_type=
                args['plane_type'])
            df = plane.calculate_trajectory(dt=1)
            converted_id = pd.to_numeric(df['plane_id'], errors='coerce')
            if converted_id.isna().all():
                df['plane_id'] = numeric_flight_id
            else:
                df['plane_id'] = converted_id.astype('Int64')
            df['plane_label'] = resolved_label
            df['plane_id'] = df['plane_id'].astype(int)
            col_name = df.columns.tolist()
            if 'time_s' in col_name:
                col_name.remove('time_s')
                col_name.insert(0, 'time_s')
                df = df.reindex(columns=col_name)
            if 'sat' in args['plane_type'].lower():
                df['roll_deg'] = 0
                df['pitch_deg'] = 0
                df['bearing_deg'] = 0
                df['yaw_deg'] = 0
            df = self._enrich_dataframe(df)
            return pl.from_pandas(df)
        except ValueError as exc:
            logging.warning(
                'Loop pattern invalid for %s (%s); retrying with original waypoints.'
                , resolved_label, exc)
            plane = plane_trajectory(flight_id=numeric_flight_id, waypoints
                =data, yaw_angular_speed=args['yaw_angular_speed'],
                roll_angular_speed=args['roll_angular_speed'],
                pitch_angular_speed=args['pitch_angular_speed'],
                vehicle_acceleration=args['vehicule_acceleration'],
                max_speed=args['max_speed'], max_roll=args['max_roll'],
                max_pitch=args['max_pitch'], target_climbup_pitch=args[
                'target_climbup_pitch'], pitch_enable_speed_ratio=args[
                'pitch_enable_speed_ratio'], altitude_loss_speed_threshold=
                args['altitude_loss_speed_threshold'], descent_pitch_target
                =args['descent_pitch_target'], landing_pitch_target=args[
                'landing_pitch_target'], cruising_pitch_max=args[
                'cruising_pitch_max'], descent_altitude_threshold_landing=
                args['descent_altitude_threshold_landing'],
                max_speed_ratio_while_turining=args[
                'max_speed_ratio_while_turining'], enable_climb=args[
                'enable_climb'], enable_descent=args['enable_descent'],
                default_alt_value=args['default_alt_value'], plane_type=
                args['plane_type'])
            df = plane.calculate_trajectory(dt=1)
            converted_id = pd.to_numeric(df['plane_id'], errors='coerce')
            if converted_id.isna().all():
                df['plane_id'] = numeric_flight_id
            else:
                df['plane_id'] = converted_id.astype('Int64')
            df['plane_label'] = resolved_label
            df['plane_id'] = df['plane_id'].astype(int)
            col_name = df.columns.tolist()
            if 'time_s' in col_name:
                col_name.remove('time_s')
                col_name.insert(0, 'time_s')
                df = df.reindex(columns=col_name)
            if 'sat' in args['plane_type'].lower():
                df['roll_deg'] = 0
                df['pitch_deg'] = 0
                df['bearing_deg'] = 0
                df['yaw_deg'] = 0
            df = self._enrich_dataframe(df)
            return pl.from_pandas(df)

    def work_done(self, worker_df):
        """Concatenate dataframe if any and save the results.

        Args:
            worker_df (pl.DataFrame): Output dataframe for one plane.

        """
        if worker_df.is_empty():
            return
        os.makedirs(self.data_out, exist_ok=True)
        raw_format = getattr(self.args, 'dataset_format', None)
        if raw_format is None and isinstance(self.args, dict):
            raw_format = self.args.get('dataset_format')
        if raw_format is None:
            raw_format = 'csv'
        dataset_format = str(raw_format).lower()
        if dataset_format not in {'csv', 'parquet'}:
            logging.info("Unsupported dataset_format '%s', falling back to csv"
                , dataset_format)
            dataset_format = 'csv'
        if 'plane_label' in worker_df.columns:
            plane_label = worker_df['plane_label'][0]
        elif 'plane_id' in worker_df.columns:
            plane_label = str(worker_df['plane_id'][0])
        else:
            plane_label = self.args['plane_type']
        timestamp = dt.now().strftime('%Y-%m-%d_%H-%M-%S')
        filename = Path(self.data_out
            ) / f'{plane_label}_{timestamp}.{dataset_format}'
        try:
            if dataset_format == 'parquet':
                worker_df.write_parquet(str(filename))
            else:
                worker_df.write_csv(str(filename))
            if self.verbose > 0:
                logging.info(f'Saved dataframe for {plane_label}: {filename}')
        except Exception as err:
            logging.info(traceback.format_exc())
            logging.info(f'Error saving dataframe for {plane_label}: {err}')

    def _enrich_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Attach derived metadata (beam / satellite overlays) to the payload."""
        df = self._assign_beams(df)
        df = self._attach_satellite_tracks(df)
        df = self._compute_distance_metrics(df)
        return df

    def _dataset_root(self) -> Path:
        return Path(self.data_in).expanduser()

    def _setup_reference_assets(self) -> None:
        dataset_root = self._dataset_root()
        self._beam_paths, self._beam_centers = self._load_beam_polygons(
            dataset_root / self.beam_file)
        self._satellite_meta = self._load_satellite_catalog(dataset_root / 
            self.sat_file)
        if load_tle_catalog is not None:
            tle_path = dataset_root / 'norad_3le.txt'
            if tle_path.exists():
                self._tle_catalog = load_tle_catalog(tle_path)
        else:  # pragma: no cover - optional dependency
            self._tle_catalog = {}

    def _load_satellite_catalog(self, path: Path) -> pd.DataFrame | None:
        if not path.exists():
            logging.info('Satellite catalog %s is missing; skipping merge.',
                path)
            return None
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            logging.warning('Unable to read %s: %s', path, exc)
            return None
        df['beam'] = df['beam'].astype(str)
        return df

    def _load_beam_polygons(self, path: Path) -> tuple[dict[str, mpath.Path],
        dict[str, tuple[float, float]]]:
        if not path.exists():
            logging.info('Beam definition file %s missing; skipping.', path)
            return {}, {}
        points: dict[str, list[tuple[float, float]]] = {}
        try:
            with path.open(encoding='utf-8') as handle:
                for line in handle:
                    parts = [entry.strip() for entry in line.split(',')]
                    if len(parts) < 3:
                        continue
                    beam_id, lon, lat = parts[:3]
                    points.setdefault(beam_id, []).append((float(lon), float(lat)))
        except Exception as exc:
            logging.warning('Unable to parse %s: %s', path, exc)
            return {}, {}
        polygons: dict[str, mpath.Path] = {}
        centers: dict[str, tuple[float, float]] = {}
        for beam_id, coords in points.items():
            if len(coords) < 3:
                continue
            arr = np.asarray(coords, dtype=float)
            polygons[beam_id] = mpath.Path(arr)
            centers[beam_id] = (float(arr[:, 0].mean()), float(arr[:, 1].mean()))
        return polygons, centers

    def _assign_beams(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self._beam_paths or 'longitude' not in df.columns or 'latitude' not in df.columns:
            df['beam'] = df.get('beam', pd.Series([pd.NA] * len(df)))
            return df
        coords = df[['longitude', 'latitude']].to_numpy(dtype=float)
        assignments = np.zeros(len(df), dtype=int)
        for beam_id, polygon in self._beam_paths.items():
            inside = polygon.contains_points(coords)
            assignments = np.where((assignments == 0) & inside, int(beam_id), assignments)
        beam_series = pd.Series(assignments).replace({0: pd.NA})
        df['beam'] = beam_series.astype('Int64')
        if self._satellite_meta is not None:
            sat_df = self._satellite_meta.rename(columns={'beam': '_beam_key'})
            df['_beam_key'] = df['beam'].astype('Int64').astype('string')
            df = df.merge(sat_df, how='left', on='_beam_key')
            df.drop(columns=['_beam_key'], inplace=True)
            df['beam_sat_ant'] = df.apply(
                lambda row: f"{row['beam']} {row['sat']}.{row['ant']}" if pd.notna(row.get('beam')) and pd.notna(row.get('sat')) and pd.notna(row.get('ant')) else None,
                axis=1,
            )
        return df

    def _attach_satellite_tracks(self, df: pd.DataFrame) -> pd.DataFrame:
        for column in ('sat_track_lat', 'sat_track_long', 'sat_track_alt_m',
            'sat_speed_ms'):
            if column not in df.columns:
                df[column] = np.nan
        if compute_trajectory is None or not self._tle_catalog or 'sat' not in df.columns:
            return df
        if 'time_s' not in df.columns:
            logging.debug('Missing time_s column; skipping satellite overlay.')
            return df
        max_time = int(df['time_s'].max() or 0)
        for sat_name in sorted(set(df['sat'].dropna())):
            entry = self._tle_catalog.get(sat_name)
            if entry is None:
                continue
            track = self._get_sat_track(sat_name, entry, max_time + 60)
            if track is None or track.empty:
                continue
            track = track.set_index('time_s')[['sat_track_lat',
                'sat_track_long', 'sat_track_alt_m', 'sat_speed_ms']]
            mask = df['sat'] == sat_name
            lookup_times = df.loc[mask, 'time_s'].astype(int)
            aligned = track.reindex(lookup_times).values
            df.loc[mask, ['sat_track_lat', 'sat_track_long',
                'sat_track_alt_m', 'sat_speed_ms']] = aligned
        return df

    def _get_sat_track(self, sat_name: str, entry: TLEEntry, duration: int
        ) -> pd.DataFrame | None:
        cached = self._sat_track_cache.get(sat_name)
        if cached is not None and cached['time_s'].max() >= duration:
            return cached
        if compute_trajectory is None:
            return None
        try:
            track = compute_trajectory(entry, duration_s=duration,
                step_s=1, epoch=DEFAULT_EPOCH)
        except Exception as exc:  # pragma: no cover - defensive guard
            logging.warning('Unable to compute satellite track for %s: %s',
                sat_name, exc)
            return None
        self._sat_track_cache[sat_name] = track
        return track

    def _compute_distance_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        if 'beam_long' in df.columns and 'beam_lat' in df.columns:
            distances = []
            for lat, lon, beam_lat, beam_lon in df[['latitude', 'longitude',
                'beam_lat', 'beam_long']].itertuples(index=False, name=None):
                if any(pd.isna(value) for value in (lat, lon, beam_lat,
                    beam_lon)):
                    distances.append(np.nan)
                    continue
                distances.append(Geodistance((lat, lon), (beam_lat, beam_lon)
                    ).km)
            df['beam_center_distance_km'] = distances
        else:
            df['beam_center_distance_km'] = np.nan
        valid_mask = df[['latitude', 'longitude', 'sat_track_lat',
            'sat_track_long']].notna().all(axis=1)
        ground_km = np.full(len(df), np.nan)
        if valid_mask.any():
            subset = df.loc[valid_mask, ['latitude', 'longitude',
                'sat_track_lat', 'sat_track_long']]
            ground_values = []
            for lat, lon, sat_lat, sat_lon in subset.itertuples(index=False,
                name=None):
                ground_values.append(Geodistance((lat, lon), (sat_lat,
                    sat_lon)).km)
            ground_km[valid_mask.values] = ground_values
        df['sat_ground_distance_km'] = ground_km
        alt_diff_km = (df['sat_track_alt_m'] - df.get('alt_m', 0.0)) / 1000.0
        with np.errstate(divide='ignore', invalid='ignore'):
            df['sat_look_angle_deg'] = np.degrees(np.arctan2(alt_diff_km,
                df['sat_ground_distance_km']))
        return df

    def _apply_loop_pattern(self, sequence, group_size, group_position):
        if group_size <= 1 or len(sequence) < 3:
            return sequence
        seq = []
        for coord in sequence:
            if len(coord) >= 3:
                seq.append([coord[0], coord[1], coord[2]])
            else:
                seq.append([coord[0], coord[1], float(self.args[
                    'default_alt_value'])])
        loops_to_add = max(1, group_size - 1)
        path_length = self._estimate_path_length(seq)
        radius_km = max(20.0, min(60.0, path_length / max(loops_to_add + 1,
            1) / 4))
        indices = [max(1, min(len(seq) - 2, int(len(seq) * (k + 1) / (
            loops_to_add + 1)))) for k in range(loops_to_add)]
        augmented = []
        for idx, point in enumerate(seq):
            augmented.append(point)
            if idx in indices:
                loop_points = self._build_loop_points(point, radius_km,
                    group_size, group_position, loops_to_add)
                augmented.extend(loop_points)
        return augmented

    def _estimate_path_length(self, sequence):
        total = 0.0
        for (lon1, lat1, *_), (lon2, lat2, *_) in zip(sequence, sequence[1:]):
            total += haversine(lon1, lat1, lon2, lat2)
        return total

    def _build_loop_points(self, point, radius_km, group_size,
        group_position, loops_to_add):
        lon, lat, alt = point
        if loops_to_add <= 0:
            loops_to_add = 1
        lat_radius_deg = radius_km / 111.0
        cos_lat = math.cos(math.radians(lat))
        lon_radius_deg = lat_radius_deg / cos_lat if abs(cos_lat
            ) > 1e-06 else lat_radius_deg
        phase = group_position % group_size * (2 * math.pi / group_size
            ) if group_size > 0 else 0.0
        steps = max(4, group_size * 2)
        loop_points = []
        for step in range(steps):
            angle = phase + 2 * math.pi * step / steps
            loop_lon = lon + lon_radius_deg * math.cos(angle)
            loop_lat = lat + lat_radius_deg * math.sin(angle)
            loop_alt = alt + 250.0 * math.sin(angle)
            loop_points.append([loop_lon, loop_lat, loop_alt])
        loop_points.append(loop_points[0])
        return loop_points
