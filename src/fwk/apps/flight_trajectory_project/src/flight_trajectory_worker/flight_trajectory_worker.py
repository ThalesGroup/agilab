import getpass
import glob
import os
import re
import shutil
import subprocess
import traceback
import warnings
from datetime import datetime as dt
from pathlib import Path
from agi_node.polars_worker import PolarsWorker
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
logger = logging.getLogger(__name__)
import plotly.graph_objects as go
import plotly.express as px


class plane_trajectory:
    df_col_names = [  # Log columns
        "plane_id",
        "time_s",
        "speed_ms",
        "alt_m",
        "roll_deg",
        "pitch_deg",
        "yaw_deg",
        "bearing_deg",
        "latitude",
        "longitude",
        "distance",
        "phase",
        "plane_type"
    ]

    def __init__(self,
                 flight_id: int = 1,
                 waypoints: list = [(0, 0, 0), (1, 0, 10000), (2, 1, 9000), (3, 3, 5000), (-3, -3, 5000)],
                 yaw_angular_speed: float = 1.0,
                 roll_angular_speed: float = 3.0,
                 pitch_angular_speed: float = 2.0,
                 vehicle_acceleration: float = 5.0,
                 max_speed: float = 900.0,
                 max_roll: float = 30.0,
                 max_pitch: float = 12.0,
                 target_climbup_pitch: float = 8.0,
                 pitch_enable_speed_ratio: float = 0.30,
                 altitude_loss_speed_treshold: float = 400.0,
                 landing_speed_target: float = 200.0,
                 descent_pitch_target: float = -3,
                 landing_pitch_target: float = 3,
                 cruising_pitch_max: float = 3,
                 descent_alt_treshold_landing: float = 500,
                 max_speed_ratio_while_turining: float = 0.3,
                 enable_climb: bool = True,
                 enable_descent: bool = True,
                 default_alt_value: float = 4000.0,
                 plane_type: str = "classique_plane"
                 ):
        self.speed = 0
        self.alt = 0
        self.roll = 0
        self.pitch = 0
        self.yaw = 0
        self.bearing = 0
        self.distance = 0
        self.current_waypoint_index = 1
        self.time = 0
        self.enable_climb = enable_climb  # enable the scenario where the plane climb up
        self.enable_descent = enable_descent  # enable the scenario where the plane descent
        self.flight_id = flight_id  # the ID of the flight
        self.waypoints = waypoints  # list of points to pass
        if len(self.waypoints) < 2:
            raise ValueError(f"Expected at least 2 waypoints, but got {len(self.waypoints)}")
        else:
            for i in range(len(self.waypoints)):
                if len(self.waypoints[i]) < 2:
                    raise ValueError(
                        f"Expected at least 2 coords (lat,lon) but got {len(self.waypoints[i])} args at index {i}")
                if len(self.waypoints[i]) < 3:
                    self.waypoints[i] = (self.waypoints[i][1], self.waypoints[i][0], default_alt_value)
                else:
                    self.waypoints[i] = (self.waypoints[i][1], self.waypoints[i][0], self.waypoints[i][2])
        self.coords = list(self.waypoints[0][:2])
        self.yaw_angular_speed = yaw_angular_speed  # in deg but not used.
        self.roll_angular_speed = roll_angular_speed  # in deg
        self.pitch_angular_speed = pitch_angular_speed  # in deg
        self.vehicle_acceleration = vehicle_acceleration  # in m/s
        self.max_speed_kmh = max_speed  # in Km/h
        self.target_speed_m_s = max_speed * 1000 / 3600  # in m/s
        self.target_altitude_m = self.waypoints[1][2]  # in meter
        self.max_roll = max_roll  # in deg
        self.max_pitch = max_pitch  # in deg
        self.cruising_pitch_max = cruising_pitch_max  # cruising pitch in deg
        self.plane_type = plane_type  # type of vehicle
        # --- Pitch Enable Speed ---
        self.pitch_enable_speed_ratio = pitch_enable_speed_ratio  # at what speed (ratio from max speed) does the plane began to climb
        self.pitch_enable_speed_m_s = self.pitch_enable_speed_ratio * self.target_speed_m_s  # actual speed that the plane is allow to pitch up
        # --- detect waypoints ---
        self.waypoint_arrival_threshold_m = self.target_speed_m_s / 2  # threshold for the passage of the waypoints
        # --- landing charact ---
        self.vehicle_deceleration = vehicle_acceleration * 1.2  # not editable but give the plane deceleration
        self.landing_speed_kmh = landing_speed_target  # speed that we are targetting for the landing
        self.landing_speed_m_s = landing_speed_target * 1000 / 3600  # convert kilometer per seconds to meter per seconds
        self.stall_speed_threshold_kmh = altitude_loss_speed_treshold  # speed where the plane began to stall, plane lose altitude due to low speed
        self.stall_speed_threshold_m_s = altitude_loss_speed_treshold * 1000 / 3600  # convert the previous speed from kilometer per seconds to meter per seconds
        self.descent_pitch_target_deg = descent_pitch_target  # descent pitch target in deg
        self.descent_altitude_threshold_landing_m = descent_alt_treshold_landing  # give the threshold where the plane prepare for landing (nose pitch up a bit)
        self.landing_pitch_target_deg = landing_pitch_target  # the finale pitch (nose up) for the landing in degree
        self.climb_pitch_target_deg = target_climbup_pitch  # pitch of the climbup in degree
        # --- Turning charac ---
        self.max_speed_ratio_while_turning = max_speed_ratio_while_turining  # lower speed for turns ratio from max speed eg 0.3 give 0.3*maxspeed
        # --- init case No climb ---
        if not enable_climb:
            self.alt = self.waypoints[0][2]
            self.speed = self.target_speed_m_s
            self.bearing = self.calculate_bearing(tuple(self.coords), tuple(self.waypoints[1][:2]))

        min_distance = self.get_min_waypoints_distance()
        for idx in range(1, len(waypoints)):
            lat1, lon1, _ = waypoints[idx - 1]
            lat2, lon2, _ = waypoints[idx]

            distance = self.haversine_distance(lat1, lon1, lat2, lon2)


            if distance < min_distance:
                print(f"Distance between waypoint {idx - 1} and {idx}: {distance:.2f}m")
                raise ValueError(
                    f"Waypoints #{idx - 1} and #{idx} are too close: {distance:.2f}m < {min_distance:.2f}m, change their positions or decrease the max speed"
                )

    def __str__(self):
        return (
            f"TrajectoryLogger(\n"
            f"  time = {self.time} s\n"
            f"  speed = {self.speed} m/s\n"
            f"  alt = {self.alt} m\n"
            f"  roll = {self.roll}°\n"
            f"  pitch = {self.pitch}°\n"
            f"  yaw = {self.yaw}°\n"
            f"  bearing = {self.bearing}°\n"
            f"  coords = {self.coords}\n"
            f"  waypoints = {self.waypoints}\n"
            f"  yaw_angular_speed = {self.yaw_angular_speed}°/s\n"
            f"  roll_angular_speed = {self.roll_angular_speed}°/s\n"
            f"  pitch_angular_speed = {self.pitch_angular_speed}°/s\n"
            f"  vehicule_acceleration = {self.vehicle_acceleration} m/s²\n"
            f"  max_speed = {self.max_speed_kmh} km/h ({self.target_speed_m_s:.2f} m/s)\n"
            f"  Alt_Target = {self.target_altitude_m} m\n"
            f"  max_roll = {self.max_roll}°\n"
            f"  max_pitch = {self.max_pitch}°\n"
            f")"
        )

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
        y = (math.cos(lat1_rad) * math.sin(lat2_rad) -
             math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(diff_long_rad))

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
        if self.pitch <= 0 or self.pitch_angular_speed <= 1e-6:
            return 0

        time_to_level = self.pitch / self.pitch_angular_speed
        avg_pitch_deg = self.pitch / 2.0
        avg_pitch_rad = math.radians(avg_pitch_deg)

        # Predict using target speed as plane should be near target speed when leveling off
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
        print(f"--- Starting Takeoff Roll, Climb & Predictive Level Off Simulation ---")
        print(f"Using Geographic Coordinates (Lat/Lon). Pitch enabled > {self.pitch_enable_speed_m_s:.1f} m/s")
        print(
            f"Target Alt: {self.target_altitude_m} m, Target Speed: {self.target_speed_m_s:.2f} m/s, Max Pitch: {self.max_pitch}°")
        print(f"-----------------------------------------------------------------------")

        log_entries = []
        time_elapsed = 0
        phase = "Takeoff Roll"  # Start phase
        level_off_initiated = False
        pitch_enabled = False  # Flag: can pitch yet?

        # Set initial bearing toward next checkpoint
        if len(self.waypoints) > 1:
            self.bearing = self.calculate_bearing(self.coords, self.waypoints[1][:2])
            self.yaw = self.bearing  # Assume instant runway alignment
            print(f"Initial bearing calculated using class method: {self.bearing:.2f}°")
        else:
            print("Warning: Only one checkpoint. Cannot calculate bearing. Setting to 0.")
            self.bearing = 0
            self.yaw = 0

        while True:
            predicted_altitude_gain = 0.0
            trigger_altitude = self.target_altitude_m  # Default

            # Enable pitch if speed threshold reached
            if not pitch_enabled and self.speed >= self.pitch_enable_speed_m_s:
                print(
                    f"Time {time_elapsed:.1f}s: Speed ({self.speed:.1f} m/s) reached threshold ({self.pitch_enable_speed_m_s:.1f} m/s). Pitch enabled.")
                pitch_enabled = True
                phase = "Climb"

            # Determine target pitch based on phase
            if phase == "Takeoff Roll":
                target_pitch = 0.0  # Keep pitch flat on ground
            elif phase == "Climb":
                predicted_altitude_gain = self.estimate_level_off_alt_gain()
                trigger_altitude = self.target_altitude_m - predicted_altitude_gain
                if self.alt >= trigger_altitude:
                    print(
                        f"Time {time_elapsed:.1f}s: Alt ({self.alt:.1f}m) reached trigger ({trigger_altitude:.1f}m) for level off. Initiating Level Off.")
                    phase = "Level Off"
                    level_off_initiated = True
                    target_pitch = 0.0
                else:
                    target_pitch = self.max_pitch if pitch_enabled else 0.0
            else:  # Level Off
                target_pitch = 0.0
                level_off_initiated = True

            target_speed = self.target_speed_m_s

            # Log current state
            current_pitch_rad = math.radians(self.pitch)
            initial_vs = self.speed * math.sin(current_pitch_rad)
            initial_hs = self.speed * math.cos(current_pitch_rad)
            log_entry = {
                "plane_id": self.flight_id,
                "time_s": time_elapsed,
                "speed_ms": self.speed,
                "alt_m": self.alt,
                "roll_deg": self.roll,
                "pitch_deg": self.pitch,
                "yaw_deg": self.yaw,
                "bearing_deg": self.bearing,
                "latitude": self.coords[0],
                "longitude": self.coords[1],
                "distance": self.distance,
                "phase": "Initial Climb",
                "plane_type": self.plane_type,
            }
            log_entries.append(log_entry)

            # Control adjustments for pitch and speed
            pitch_error = target_pitch - self.pitch
            delta_pitch = np.clip(pitch_error, -self.pitch_angular_speed * dt, self.pitch_angular_speed * dt)
            next_pitch = self.pitch + delta_pitch
            next_pitch = np.clip(next_pitch, -self.climb_pitch_target_deg / 2, self.climb_pitch_target_deg)

            if self.speed < target_speed:
                delta_speed = self.vehicle_acceleration * dt
                next_speed = min(
                    self.speed + delta_speed * math.sin(math.pi * 0.05 + math.pi * (self.speed / target_speed) * 0.95),
                    target_speed)
            else:
                next_speed = target_speed

            # Simulate physics for next step
            next_pitch_rad = math.radians(next_pitch)
            vertical_speed = next_speed * math.sin(next_pitch_rad)
            horizontal_speed = next_speed * math.cos(next_pitch_rad)

            # Update altitude
            delta_alt = vertical_speed * dt
            next_alt = self.alt + delta_alt
            if phase != "Takeoff Roll" and next_alt < 0:
                next_alt = 0

            # Update coordinates with geopy if available, else fallback
            distance_meters = horizontal_speed * dt
            if distance_meters > 1e-3:
                if 'Point' in globals() and 'geodesic' in globals():
                    start_point = Point(latitude=self.coords[0], longitude=self.coords[1])
                    destination = geodesic(meters=distance_meters).destination(point=start_point, bearing=self.bearing)
                    next_coords = [destination.latitude, destination.longitude]
                else:
                    lat1_rad = math.radians(self.coords[0])
                    lon1_rad = math.radians(self.coords[1])
                    bearing_rad = math.radians(self.bearing)
                    earth_radius_m = 6371000  # Earth radius approx

                    ang_dist = distance_meters / earth_radius_m

                    lat2_rad = math.asin(math.sin(lat1_rad) * math.cos(ang_dist) +
                                         math.cos(lat1_rad) * math.sin(ang_dist) * math.cos(bearing_rad))
                    lon2_rad = lon1_rad + math.atan2(math.sin(bearing_rad) * math.sin(ang_dist) * math.cos(lat1_rad),
                                                     math.cos(ang_dist) - math.sin(lat1_rad) * math.sin(lat2_rad))

                    next_coords = [math.degrees(lat2_rad), math.degrees(lon2_rad)]
            else:
                next_coords = list(self.coords)

            # Update state for next iteration
            self.speed = next_speed
            self.pitch = next_pitch
            self.alt = next_alt
            self.coords = next_coords
            self.yaw = self.bearing
            self.distance += next_speed
            time_elapsed += dt

            # Check for end of simulation
            if level_off_initiated and abs(self.pitch) < pitch_threshold:
                alt_error = abs(self.alt - self.target_altitude_m)
                print(f"--- Level Off Complete. Pitch ({self.pitch:.2f}°) near zero at time {time_elapsed:.1f}s. "
                      f"Final Alt: {self.alt:.1f}m (Error: {alt_error:.1f}m) ---")
                final_log_entry = {
                    "plane_id": self.flight_id,
                    "time_s": time_elapsed,
                    "speed_ms": self.speed,
                    "alt_m": self.alt,
                    "roll_deg": self.roll,
                    "pitch_deg": self.pitch,
                    "yaw_deg": self.yaw,
                    "bearing_deg": self.bearing,
                    "latitude": self.coords[0],
                    "longitude": self.coords[1],
                    "distance": self.distance,
                    "phase": "Initial Climb",
                    "plane_type": self.plane_type
                }
                log_entries.append(final_log_entry)
                break

            # Safety break for max simulation time
            if time_elapsed > 72000:
                print("Warning: Simulation exceeded maximum time limit (20hr).")
                final_log_entry = {
                    "plane_id": self.flight_id,
                    "time_s": time_elapsed,
                    "speed_ms": self.speed,
                    "alt_m": self.alt,
                    "roll_deg": self.roll,
                    "pitch_deg": self.pitch,
                    "yaw_deg": self.yaw,
                    "bearing_deg": self.bearing,
                    "latitude": self.coords[0],
                    "longitude": self.coords[1],
                    "distance": self.distance,
                    "phase": "Initial Climb",
                    "plane_type": self.plane_type
                }
                log_entries.append(final_log_entry)
                break

        trajectory_log_df = pd.DataFrame(log_entries)
        trajectory_log_df = trajectory_log_df.reindex(columns=self.df_col_names)
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

            horizontal_distance = self.speed * math.cos(math.radians(pitch)) * dt
            distance_traveled += horizontal_distance

            destination = Geodistance(meters=horizontal_distance).destination(
                point=Point(self.coords[0], self.coords[1]),
                bearing=self.bearing
            )

            self.alt += self.speed * math.sin(math.radians(pitch)) * dt
            self.time += 1
            self.distance = distance_traveled
            self.pitch = pitch
            self.coords[0], self.coords[1] = destination.latitude, destination.longitude

            log_entries.append({
                "plane_id": self.flight_id,
                "time_s": self.time,
                "speed_ms": self.speed,
                "alt_m": self.alt,
                "roll_deg": self.roll,
                "pitch_deg": self.pitch,
                "yaw_deg": self.yaw,
                "bearing_deg": self.bearing,
                "latitude": self.coords[0],
                "longitude": self.coords[1],
                "distance": self.distance,
                "phase": "Pitch_to_Center",
                "plane_type": self.plane_type,
            })

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
                altitude_difference += self.speed * math.sin(math.radians(pitch)) * dt

            if pitch < 0:
                pitch += pitch_delta
                if pitch > 0:
                    pitch = 0
                altitude_difference -= self.speed * math.sin(math.radians(pitch)) * dt

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
        self.bearing = self.calculate_bearing(self.coords, self.waypoints[self.current_waypoint_index][:2])
        log_entries = []

        prev_altitude = -1
        prev_delta_altitude = -1
        do_log = True
        adapt_altitude_to_target = True  # Stage 1: adjust altitude to target

        distance_to_waypoint = geodesic(tuple(self.coords), self.waypoints[self.current_waypoint_index][:2]).meters
        altitude_diff = abs(self.alt - self.waypoints[self.current_waypoint_index][2])
        hypotenuse = math.sqrt(altitude_diff ** 2 + distance_to_waypoint ** 2)
        min_angle = abs(math.degrees(math.acos(distance_to_waypoint / hypotenuse)))

        # Determine target pitch based on min_angle and pitch limits
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

        pitch_direction_up = self.waypoints[self.current_waypoint_index][2] > self.alt

        while True:
            new_bearing = self.calculate_bearing(self.coords, self.waypoints[self.current_waypoint_index][:2])
            yaw_change = new_bearing - self.bearing
            self.bearing = new_bearing

            # Accelerate towards target speed if needed
            if self.speed < self.target_speed_m_s:
                speed_increment = self.vehicle_acceleration * dt
                self.speed += speed_increment
                if self.speed > self.target_speed_m_s:
                    self.speed = self.target_speed_m_s

            if adapt_altitude_to_target:
                delta_altitude = abs(self.alt - self.waypoints[self.current_waypoint_index][2])

                if (self.estimate_altitude_change_for_pitch_correction(dt=dt) >= delta_altitude
                        or (prev_delta_altitude != -1 and delta_altitude > prev_delta_altitude)):
                    log_entries.extend(self.perform_pitch_correction_to_level(dt=dt))
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
                horizontal_distance = self.speed * math.cos(math.radians(self.pitch)) * dt
                self.distance += horizontal_distance
                destination = Geodistance(meters=horizontal_distance).destination(
                    point=Point(self.coords[0], self.coords[1]),
                    bearing=self.bearing
                )
                self.alt += self.speed * math.sin(math.radians(self.pitch)) * dt
                self.coords[0], self.coords[1] = destination.latitude, destination.longitude
                self.time += 1

                log_entries.append({
                    "plane_id": self.flight_id,
                    "time_s": self.time,
                    "speed_ms": self.speed,
                    "alt_m": self.alt,
                    "roll_deg": self.roll,
                    "pitch_deg": self.pitch,
                    "yaw_deg": yaw_change,
                    "bearing_deg": self.bearing,
                    "latitude": self.coords[0],
                    "longitude": self.coords[1],
                    "distance": self.distance,
                    "phase": f"Cruise to waypoint {self.current_waypoint_index}",
                    "plane_type": self.plane_type,
                })
            else:
                do_log = True

            # Break loop when close enough to waypoint (half target speed)
            if geodesic(tuple(self.coords),
                        self.waypoints[self.current_waypoint_index][:2]).meters < self.target_speed_m_s / 2:
                break

        self.current_waypoint_index += 1
        trajectory_log_df = pd.DataFrame(log_entries)
        # Ensure columns match df_col_names
        trajectory_log_df = trajectory_log_df.reindex(columns=self.df_col_names)
        return trajectory_log_df

    def estimate_descent_distance(self, dt=1.0, target_angle=-3, descent_altitude_threshold_landing=500,
                                  pitch_angular_speed=1):
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

        alt_loss_max_acceleration = -1.5 * speed * math.sin(math.radians(target_angle)) * dt

        while True:
            new_bearing = self.calculate_bearing(self.coords, self.waypoints[self.current_waypoint_index][:2])
            yaw_change = new_bearing - self.bearing
            self.bearing = new_bearing

            if altitude > descent_altitude_threshold_landing:
                if pitch > target_angle:
                    pitch_delta = dt * self.pitch_angular_speed
                    pitch -= pitch_delta
                    pitch = max(pitch, target_angle)

                horizontal_distance = speed * math.cos(math.radians(pitch)) * dt
                distance_traveled += horizontal_distance
                destination = Geodistance(meters=horizontal_distance).destination(
                    point=Point(coords[0], coords[1]),
                    bearing=self.bearing
                )
                altitude += speed * math.sin(math.radians(pitch)) * dt
                coords[0], coords[1] = destination.latitude, destination.longitude

            else:
                if pitch < self.landing_pitch_target_deg and speed < self.stall_speed_threshold_m_s:
                    pitch_delta = dt * self.pitch_angular_speed * 0.10 * pitch_angular_speed
                    pitch += pitch_delta
                    pitch = min(pitch, self.landing_pitch_target_deg)
                elif pitch < 0 and speed >= self.stall_speed_threshold_m_s:
                    pitch_delta = dt * self.pitch_angular_speed * 0.10 * pitch_angular_speed
                    pitch += pitch_delta
                    pitch = min(pitch, 0)

                if speed > self.landing_speed_m_s:
                    deceleration = dt * self.vehicle_deceleration
                    speed_reduction_factor = math.sin(
                        0.1 * math.pi +
                        0.9 * math.pi *
                        (
                                (self.target_speed_m_s - self.landing_speed_m_s) -
                                (self.speed - self.landing_speed_m_s)
                        ) / (self.target_speed_m_s - self.landing_speed_m_s)
                    )
                    speed -= deceleration * speed_reduction_factor
                    speed = max(speed, self.landing_speed_m_s)

                if speed < self.stall_speed_threshold_m_s:
                    altitude -= alt_loss_max_acceleration / (speed - self.landing_speed_m_s + 1)

                horizontal_distance = speed * math.cos(math.radians(pitch)) * dt
                distance_traveled += horizontal_distance
                destination = Geodistance(meters=horizontal_distance).destination(
                    point=Point(coords[0], coords[1]),
                    bearing=self.bearing
                )
                altitude += speed * math.sin(math.radians(pitch)) * dt
                coords[0], coords[1] = destination.latitude, destination.longitude

                if altitude < 0:
                    altitude = 0
                    break

        return distance_traveled

    def perform_descent(self, dt=1.0, target_angle=-3, descent_altitude_threshold_landing=500, pitch_angular_speed=1):
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
        self.bearing = self.calculate_bearing(self.coords, self.waypoints[-1][:2])
        log_entries = []

        speed = self.speed
        altitude = self.alt
        distance_traveled = self.distance
        pitch = self.pitch

        alt_loss_max_acceleration = -1.5 * speed * math.sin(math.radians(target_angle)) * dt

        while True:
            new_bearing = self.calculate_bearing(self.coords, self.waypoints[self.current_waypoint_index][:2])
            yaw_change = new_bearing - self.bearing
            self.bearing = new_bearing

            if altitude > descent_altitude_threshold_landing:
                if pitch > target_angle:
                    pitch_delta = dt * self.pitch_angular_speed
                    pitch -= pitch_delta
                    pitch = max(pitch, target_angle)

                horizontal_distance = speed * math.cos(math.radians(pitch)) * dt
                distance_traveled += horizontal_distance
                destination = Geodistance(meters=horizontal_distance).destination(
                    point=Point(self.coords[0], self.coords[1]),
                    bearing=self.bearing
                )
                altitude += speed * math.sin(math.radians(pitch)) * dt
            else:
                if pitch < self.landing_pitch_target_deg and speed < self.stall_speed_threshold_m_s:
                    pitch_delta = dt * self.pitch_angular_speed * 0.10 * pitch_angular_speed
                    pitch += pitch_delta
                    pitch = min(pitch, self.landing_pitch_target_deg)
                elif pitch < 0 and speed >= self.stall_speed_threshold_m_s:
                    pitch_delta = dt * self.pitch_angular_speed * 0.10 * pitch_angular_speed
                    pitch += pitch_delta
                    pitch = min(pitch, 0)

                if speed > self.landing_speed_m_s:
                    deceleration = dt * self.vehicle_deceleration
                    speed_reduction_factor = math.sin(
                        0.1 * math.pi +
                        0.9 * math.pi *
                        (
                                (self.target_speed_m_s - self.landing_speed_m_s) -
                                (self.speed - self.landing_speed_m_s)
                        ) / (self.target_speed_m_s - self.landing_speed_m_s)
                    )
                    speed -= deceleration * speed_reduction_factor
                    speed = max(speed, self.landing_speed_m_s)

                if speed < self.stall_speed_threshold_m_s:
                    altitude -= alt_loss_max_acceleration / (speed - self.landing_speed_m_s + 1)

                horizontal_distance = speed * math.cos(math.radians(pitch)) * dt
                distance_traveled += horizontal_distance
                destination = Geodistance(meters=horizontal_distance).destination(
                    point=Point(self.coords[0], self.coords[1]),
                    bearing=self.bearing
                )
                altitude += speed * math.sin(math.radians(pitch)) * dt

                if altitude < 0:
                    altitude = 0

            # Update state variables
            self.speed = speed
            self.time += 1
            self.distance = distance_traveled
            self.alt = altitude
            self.pitch = pitch
            self.coords[0], self.coords[1] = destination.latitude, destination.longitude

            log_entries.append({
                "plane_id": self.flight_id,
                "time_s": self.time,
                "speed_ms": self.speed,
                "alt_m": self.alt,
                "roll_deg": self.roll,
                "pitch_deg": self.pitch,
                "yaw_deg": yaw_change,
                "bearing_deg": self.bearing,
                "latitude": self.coords[0],
                "longitude": self.coords[1],
                "distance": self.distance,
                "phase": f"Descending to the final waypoint {self.current_waypoint_index}",
                "plane_type": self.plane_type,
            })

            if altitude == 0:
                break

        trajectory_log_df = pd.DataFrame(log_entries)
        # Ensure exact columns using reindex before returning
        trajectory_log_df = trajectory_log_df.reindex(columns=self.df_col_names)
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
        self.bearing = self.calculate_bearing(self.coords, self.waypoints[-1][:2])
        log_entries = []

        dist_needed_for_landing = self.estimate_descent_distance(
            dt=dt,
            target_angle=self.descent_pitch_target_deg,
            descent_alt_treshold_landing=self.descent_altitude_threshold_landing_m,
            pitch_angular_speed=1
        )
        distance_to_final_waypoint = geodesic(tuple(self.coords), self.waypoints[-1][:2]).meters
        initial_descent_pitch_target = self.descent_pitch_target_deg
        pitch_angular_speed = 1

        if dist_needed_for_landing > distance_to_final_waypoint:
            print(
                "Landing setup with current plane simulation parameters not possible, attempting more aggressive parameters to land at last waypoint")

        # Adjust descent parameters if distance needed to land is too large
        while dist_needed_for_landing > distance_to_final_waypoint:
            if self.speed < self.target_speed_m_s:
                speed_increment = self.vehicle_acceleration * dt
                self.speed += speed_increment
                if self.speed > self.target_speed_m_s:
                    self.speed = self.target_speed_m_s

            self.descent_pitch_target_deg -= 1
            self.descent_altitude_threshold_landing_m += 100
            pitch_angular_speed = abs(initial_descent_pitch_target) / abs(self.descent_pitch_target_deg)
            dist_needed_for_landing = self.estimate_descent_distance(
                dt=dt,
                target_angle=self.descent_pitch_target_deg,
                descent_alt_treshold_landing=self.descent_altitude_threshold_landing_m,
                pitch_angular_speed=pitch_angular_speed
            )

        # Cruise until within descent distance, then perform descent
        while True:
            current_distance_to_waypoint = geodesic(tuple(self.coords), self.waypoints[-1][:2]).meters
            if current_distance_to_waypoint > dist_needed_for_landing:
                new_bearing = self.calculate_bearing(self.coords, self.waypoints[self.current_waypoint_index][:2])
                yaw_change = new_bearing - self.bearing
                self.bearing = new_bearing

                horizontal_speed = self.speed * math.cos(math.radians(self.pitch))
                self.distance += horizontal_speed * dt
                destination = Geodistance(meters=horizontal_speed * dt).destination(
                    point=Point(self.coords[0], self.coords[1]),
                    bearing=self.bearing
                )
                self.time += 1
                self.coords[0], self.coords[1] = destination.latitude, destination.longitude

                log_entries.append({
                    "plane_id": self.flight_id,
                    "time_s": self.time,
                    "speed_ms": self.speed,
                    "alt_m": self.alt,
                    "roll_deg": self.roll,
                    "pitch_deg": self.pitch,
                    "yaw_deg": yaw_change,
                    "bearing_deg": self.bearing,
                    "latitude": self.coords[0],
                    "longitude": self.coords[1],
                    "distance": self.distance,
                    "phase": f"Cruise to last waypoint ({self.current_waypoint_index})",
                    "plane_type": self.plane_type,
                })
            else:
                descent_log_df = self.perform_descent(
                    dt=dt,
                    target_angle=self.descent_pitch_target_deg,
                    descent_alt_treshold_landing=self.descent_altitude_threshold_landing_m,
                    pitch_angular_speed=pitch_angular_speed
                )
                break

        trajectory_log_df = pd.DataFrame(log_entries)
        # Ensure exact columns using reindex before returning
        trajectory_log_df = trajectory_log_df.reindex(columns=self.df_col_names)
        trajectory_log_df = pd.concat([trajectory_log_df, descent_log_df], ignore_index=True)
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
        else:
            if bearing_difference > 0:
                turn_right = True
                rotation_angle = abs(self.bearing - 360 - target_bearing)
            else:
                turn_right = False
                rotation_angle = abs(self.bearing + 360 - target_bearing)

        return turn_right, rotation_angle

    def haversine_distance(self, lat1, lon1, lat2, lon2):
        R = 6371000  # Earth radius in meters
        phi1 = np.radians(lat1)
        phi2 = np.radians(lat2)
        dphi = np.radians(lat2 - lat1)
        dlambda = np.radians(lon2 - lon1)

        a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0) ** 2
        c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))

        return R * c

    def estimate_roll_pitch_correction_rotation(self, dt=1.0, current_roll=None):
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

            incremental_rotation = (self.pitch_angular_speed * abs(roll) / self.max_roll) * math.sin(math.radians(roll))
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
        earth_gravity = 9.807  # Not currently used but could be useful for future physics

        while True:
            # Gradually reduce roll angle toward zero
            roll_change = self.roll_angular_speed * dt
            if self.roll > 0:
                self.roll -= roll_change
                if self.roll < 0:
                    self.roll = 0
            elif self.roll < 0:
                self.roll += roll_change
                if self.roll > 0:
                    self.roll = 0

            # Update bearing based on roll and pitch angular speeds
            bearing_increment = (self.pitch_angular_speed * abs(self.roll) / self.max_roll) * math.sin(
                math.radians(self.roll))
            self.bearing += bearing_increment

            # Calculate pitch from roll
            pitch = (self.pitch_angular_speed * abs(self.roll) / self.max_roll) * math.cos(math.radians(self.roll))
            self.pitch = pitch

            # Update altitude with a cap to limit unrealistic changes
            altitude_increment = self.speed * math.sin(math.radians(pitch)) * dt
            self.alt += min(altitude_increment, 0.5)

            # Update distance traveled along horizontal component
            horizontal_distance = self.speed * math.cos(math.radians(pitch)) * dt
            self.distance += horizontal_distance

            # Calculate new geographic coordinates based on movement and bearing
            destination = Geodistance(meters=horizontal_distance).destination(
                point=Point(self.coords[0], self.coords[1]),
                bearing=self.bearing
            )
            self.time += 1
            self.coords[0], self.coords[1] = destination.latitude, destination.longitude

            # Log current state
            log_entries.append({
                "plane_id": self.flight_id,
                "time_s": self.time,
                "speed_ms": self.speed,
                "alt_m": self.alt,
                "roll_deg": self.roll,
                "pitch_deg": self.pitch,
                "yaw_deg": self.yaw,
                "bearing_deg": self.bearing,
                "latitude": self.coords[0],
                "longitude": self.coords[1],
                "distance": self.distance,
                "phase": f"perform Roll-Pitch correction {self.current_waypoint_index}",
                "plane_type": self.plane_type,
            })

            # Stop when roll is fully corrected (zero)
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

        target_bearing = self.calculate_bearing(tuple(self.coords), self.waypoints[self.current_waypoint_index])
        turn_right, rotation_needed = self.calculate_turn_direction_and_angle(target_bearing)
        speed_ratio = rotation_needed / 180
        target_speed = self.target_speed_m_s * (1 - ((1 - self.max_speed_ratio_while_turning) * math.sin(speed_ratio)))

        while True:
            target_bearing = self.calculate_bearing(tuple(self.coords), self.waypoints[self.current_waypoint_index])
            _, rotation_needed = self.calculate_turn_direction_and_angle(target_bearing)

            # Reduce speed for sharper turns if needed
            if self.speed > target_speed:
                speed_decrement = dt * self.vehicle_deceleration
                self.speed -= speed_decrement
                if self.speed < target_speed:
                    self.speed = target_speed

            # Check if rotation required is less than estimated correction rotation
            if rotation_needed < self.estimate_roll_pitch_correction_rotation(dt=dt):
                log_entries.extend(self.perform_roll_pitch_correction(dt=dt))
                break

            # Adjust roll angle based on turn direction
            roll_delta = self.roll_angular_speed * dt
            if turn_right:
                self.roll += roll_delta
                if self.roll > self.max_roll:
                    self.roll = self.max_roll
            else:
                self.roll -= roll_delta
                if self.roll < -self.max_roll:
                    self.roll = -self.max_roll

            # Calculate incremental rotation based on roll and pitch angular speeds
            incremental_rotation = (self.pitch_angular_speed * abs(self.roll) / self.max_roll) * math.sin(
                math.radians(self.roll))
            total_rotation += incremental_rotation
            self.bearing += incremental_rotation

            # Keep bearing within [0, 360]
            if self.bearing > 360:
                self.bearing -= 360
            if self.bearing < 0:
                self.bearing += 360

            # Calculate pitch based on roll
            pitch = (self.pitch_angular_speed * abs(self.roll) / self.max_roll) * math.cos(math.radians(self.roll))
            self.pitch = pitch

            # Update altitude (capped) and distance traveled
            self.alt += min(self.speed * math.sin(math.radians(pitch)) * dt, 0.5)  # TODO: refine altitude calculation
            self.distance += self.speed * math.cos(math.radians(pitch)) * dt

            # Calculate new position based on distance and bearing
            displacement = self.speed * math.cos(math.radians(pitch)) * dt
            destination = Geodistance(meters=displacement).destination(
                point=Point(self.coords[0], self.coords[1]),
                bearing=self.bearing
            )
            self.time += 1
            self.coords[0], self.coords[1] = destination.latitude, destination.longitude

            # Log current state
            log_entries.append({
                "plane_id": self.flight_id,
                "time_s": self.time,
                "speed_ms": self.speed,
                "alt_m": self.alt,
                "roll_deg": self.roll,
                "pitch_deg": self.pitch,
                "yaw_deg": self.yaw,
                "bearing_deg": self.bearing,
                "latitude": self.coords[0],
                "longitude": self.coords[1],
                "distance": self.distance,
                "phase": f"Turn to waypoint {self.current_waypoint_index}",
                "plane_type": self.plane_type,
            })

        trajectory_log = pd.DataFrame(log_entries)
        # Ensure columns order matches df_col_names
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
            else:
                if bearing_difference > 0:
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
        coords = [0, 0]  # mutable copy
        distance = 0
        time = 0

        rotation_needed = 180
        turn_right = False
        speed_ratio = rotation_needed / 180
        target_speed = self.target_speed_m_s * (1 - ((1 - self.max_speed_ratio_while_turning) * math.sin(speed_ratio)))

        while True:
            target_bearing = self.calculate_bearing(tuple(coords), [-1, 0, 10000])
            _, rotation_needed = local_calculate_turn_direction_and_angle(bearing, target_bearing)
            # Reduce speed for sharper turns if needed
            if speed > target_speed:
                speed_decrement = dt * self.vehicle_deceleration
                speed -= speed_decrement
                if speed < target_speed:
                    speed = target_speed

            # Check if rotation required is less than estimated correction rotation
            if rotation_needed < self.estimate_roll_pitch_correction_rotation(dt=dt, current_roll=roll):
                # log_entries.extend(self.perform_roll_pitch_correction(dt=dt))
                break

            # Adjust roll angle based on turn direction
            roll_delta = self.roll_angular_speed * dt
            if turn_right:
                roll += roll_delta
                if roll > self.max_roll:
                    roll = self.max_roll
            else:
                roll -= roll_delta
                if roll < -self.max_roll:
                    roll = -self.max_roll

            # Calculate incremental rotation based on roll
            incremental_rotation = (self.pitch_angular_speed * abs(roll) / self.max_roll) * math.sin(math.radians(roll))
            total_rotation += incremental_rotation
            bearing += incremental_rotation

            # Keep bearing within [0, 360]
            if bearing > 360:
                bearing -= 360
            if bearing < 0:
                bearing += 360

            # Calculate pitch based on roll
            pitch = (self.pitch_angular_speed * abs(roll) / self.max_roll) * math.cos(math.radians(roll))

            # Update altitude and distance
            alt += min(speed * math.sin(math.radians(pitch)) * dt, 0.5)
            distance += speed * math.cos(math.radians(pitch)) * dt

            # Calculate new position
            displacement = speed * math.cos(math.radians(pitch)) * dt
            destination = Geodistance(meters=displacement).destination(
                point=Point(coords[0], coords[1]),
                bearing=bearing
            )
            coords[0], coords[1] = destination.latitude, destination.longitude
            time += 1

            # Log current state
            log_entries.append({
                "plane_id": self.flight_id,
                "time_s": time,
                "speed_ms": speed,
                "alt_m": alt,
                "roll_deg": roll,
                "pitch_deg": pitch,
                "yaw_deg": yaw,
                "bearing_deg": bearing,
                "latitude": coords[0],
                "longitude": coords[1],
                "distance": distance,
                "phase": f"Turn to waypoint {self.current_waypoint_index}",
                "plane_type": self.plane_type,
            })

        trajectory_log = pd.DataFrame(log_entries)
        trajectory_log = trajectory_log.reindex(columns=self.df_col_names)

        def haversine_distance(lat1, lon1, lat2, lon2):
            """
            Compute the Haversine distance between two points in decimal degrees.
            Returns distance in meters.
            """
            R = 6371000  # Earth radius in meters

            phi1 = np.radians(lat1)
            phi2 = np.radians(lat2)
            dphi = np.radians(lat2 - lat1)
            dlambda = np.radians(lon2 - lon1)

            a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0) ** 2
            c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))

            return R * c

        trajectory_log["distance_from_origin_m"] = haversine_distance(
            0, 0,
            trajectory_log["latitude"].values,
            trajectory_log["longitude"].values
        )
        return trajectory_log["distance_from_origin_m"].max()

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
        print("\nFinal State after Climb:")
        print(self)

        print("\n Trajectory Log Head:")
        print(df.head())
        print("\n Trajectory Log Tail:")
        print(df.tail())

        # Plot the altitude
        print("\nPlotting Altitude vs Time...")
        fig_alt = px.line(df, x='time_s', y='alt_m', title='Altitude during Climb Phase')
        fig_alt.update_layout(xaxis_title="Time (seconds)", yaxis_title="Altitude (meters)")
        fig_alt.show()

        # Optional: Plot speed
        fig_spd = px.line(df, x='time_s', y='speed_ms', title='Speed during Climb Phase')
        fig_spd.update_layout(xaxis_title="Time (seconds)", yaxis_title="Speed (m/s)")
        # Add target speed line
        fig_spd.add_hline(y=self.target_speed_m_s, line_dash="dot", annotation_text="Target Speed",
                          annotation_position="bottom right")
        fig_spd.show()

        # Optional: Plot Pitch
        fig_pitch = px.line(df, x='time_s', y='pitch_deg', title='Pitch Angle during Climb Phase')
        fig_pitch.update_layout(xaxis_title="Time (seconds)", yaxis_title="Pitch (degrees)")
        fig_pitch.add_hline(y=self.max_pitch, line_dash="dot", annotation_text="Max Pitch",
                            annotation_position="bottom right")
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
        required_columns = ['alt_m', 'latitude', 'longitude', 'phase', 'roll_deg', 'pitch_deg', 'bearing_deg',
                            'speed_ms']
        if not all(col in df.columns for col in required_columns):
            raise ValueError(f"DataFrame must contain {required_columns}")

        fig = go.Figure(data=[go.Scatter3d(
            x=df['longitude'],
            y=df['latitude'],
            z=df['alt_m'],
            mode='lines+markers',
            marker=dict(
                size=4,
                color=df['alt_m'],  # color based on altitude
                colorscale='Viridis',
                opacity=0.8
            ),
            line=dict(
                color='blue',
                width=2
            ),
            customdata=df[['phase', 'roll_deg', 'pitch_deg', 'bearing_deg', 'speed_ms']].values,
            hovertemplate=(
                    "Longitude: %{x}<br>" +
                    "Latitude: %{y}<br>" +
                    "Altitude: %{z} m<br>" +
                    "Phase: %{customdata[0]}<br>" +
                    "Roll: %{customdata[1]}°<br>" +
                    "Pitch: %{customdata[2]}°<br>" +
                    "Bearing: %{customdata[3]}°<br>" +
                    "Speed: %{customdata[4]} m/s<br>" +
                    "<extra></extra>"
            )
        )])

        # Calcul des plages
        delta_x = abs(df['longitude'].max() - df['longitude'].min())
        delta_y = abs(df['latitude'].max() - df['latitude'].min())
        delta_z = abs(df['alt_m'].max() - df['alt_m'].min())

        # Normalisation pour avoir une base XY à échelle 1:1
        max_base = max(delta_x, delta_y)
        aspect_ratio = dict(
            x=delta_x / max_base,
            y=delta_y / max_base,
            z=0.05  # ou fixe à 0.5 si trop grand
        )

        fig.update_layout(
            title='3D Flight Path',
            scene=dict(
                xaxis_title='Longitude',
                yaxis_title='Latitude',
                zaxis_title='Altitude (m)',
                aspectmode='manual',
                aspectratio=aspect_ratio
            ),
            margin=dict(l=0, r=0, b=0, t=40)
        )

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
            trajectory_log_df = self.simulate_takeoff_and_climb(dt=dt, pitch_threshold=0.05)
            turn_log_df = self.perform_turn_to_next_waypoint(dt=dt)
            trajectory_log_df = pd.concat([trajectory_log_df, turn_log_df], ignore_index=True)
        else:
            trajectory_log_df = pd.DataFrame([{
                "plane_id": self.flight_id,
                "time_s": self.time,
                "speed_ms": self.speed,
                "alt_m": self.alt,
                "roll_deg": self.roll,
                "pitch_deg": self.pitch,
                "yaw_deg": self.yaw,
                "bearing_deg": self.bearing,
                "latitude": self.coords[0],
                "longitude": self.coords[1],
                "distance": self.distance,
                "phase": "initial State",
                "plane_type": self.plane_type
            }])
            trajectory_log_df = trajectory_log_df.reindex(columns=self.df_col_names)

        while self.current_waypoint_index < len(self.waypoints) - 1:
            print(
                f"Calculating for waypoint {self.current_waypoint_index} coords: {self.waypoints[self.current_waypoint_index]}")
            cruise_log_df = self.simulate_cruise_to_waypoint(dt=dt)
            trajectory_log_df = pd.concat([trajectory_log_df, cruise_log_df], ignore_index=True)

            turn_log_df = self.perform_turn_to_next_waypoint(dt=dt)
            trajectory_log_df = pd.concat([trajectory_log_df, turn_log_df], ignore_index=True)

        if self.enable_descent:
            descent_log_df = self.cruise_to_destination(dt=dt)
            trajectory_log_df = pd.concat([trajectory_log_df, descent_log_df], ignore_index=True)
        else:
            cruise_log_df = self.simulate_cruise_to_waypoint(dt=dt)
            trajectory_log_df = pd.concat([trajectory_log_df, cruise_log_df], ignore_index=True)

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


class FlightTrajectoryWorker(PolarsWorker):
    """Class derived from AgiDataWorker"""
    pool_vars = {}

    def start(self):
        global global_vars
        self.pool_vars["args"] = self.args
        self.pool_vars["verbose"] = self.verbose
        global_vars = self.pool_vars
        data_out = Path(self.args['data_out']).expanduser()
        try:
            shutil.rmtree(data_out, ignore_errors=False, onerror=self.onerror)
            os.makedirs(data_out, exist_ok=True)
        except Exception as e:
            print(f'Error removing directory: {e}')
        if self.verbose > 0:
            print(f'from: {__file__}\n', end='')

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

    def work_pool(self, file):
        """Parse IVQ log files.

        Args:
            file (str): The log file to parse.

        Returns:
            pl.DataFrame: Parsed data.
        """
        global global_vars
        args = self.args
        verbose = self.verbose
        file = int(file)
        data_dir_path = Path(args['data_dir'])
        expanded_data_dir_path = data_dir_path.expanduser()
        full_waypoints_path = expanded_data_dir_path / args['waypoints']
        with open(full_waypoints_path, 'r') as waypoints_list:
            list_waypoints = json.load(waypoints_list)
        data = list_waypoints['features'][file]['geometry']['coordinates'][0
            ] if isinstance(list_waypoints['features'][file]['geometry'][
            'coordinates'][0][0], list) else list_waypoints['features'][file][
            'geometry']['coordinates']
        try:
            plane = plane_trajectory(flight_id=file, waypoints=data,
                yaw_angular_speed=args['yaw_angular_speed'],
                roll_angular_speed=args['roll_angular_speed'],
                pitch_angular_speed=args['pitch_angular_speed'],
                vehicle_acceleration=args['vehicule_acceleration'],
                max_speed=args['max_speed'], max_roll=args['max_roll'],
                max_pitch=args['max_pitch'], target_climbup_pitch=args[
                'target_climbup_pitch'], pitch_enable_speed_ratio=args[
                'pitch_enable_speed_ratio'], altitude_loss_speed_treshold=
                args['altitude_loss_speed_treshold'], descent_pitch_target=
                args['descent_pitch_target'], landing_pitch_target=args[
                'landing_pitch_target'], cruising_pitch_max=args[
                'cruising_pitch_max'], descent_alt_treshold_landing=args[
                'descent_alt_treshold_landing'],
                max_speed_ratio_while_turining=args[
                'max_speed_ratio_while_turining'], enable_climb=args[
                'enable_climb'], enable_descent=args['enable_descent'],
                default_alt_value=args['default_alt_value'], plane_type=
                args['plane_type'])
            df = plane.calculate_trajectory(dt=1)
            col_name = df.columns.tolist()
            col_name.remove('time_s')
            col_name.insert(0, 'time_s')
            df = df.reindex(columns=col_name)
            if ("sat" in args["plane_type"].lower()):
                df["roll_deg"] = 0
                df["pitch_deg"] = 0
                df["bearing_deg"] = 0
                df["yaw_deg"] = 0
            df = pl.from_pandas(df)
        except ValueError as e:
            print(f'Initialization failed: {e}')
        return df

    def work_done(self, worker_df):
        """Concatenate dataframe if any and save the results.

        Args:
            worker_df (pl.DataFrame): Output dataframe for one plane.

        """
        if worker_df.is_empty():
            return
        try:
            id = worker_df['plane_id'][0]
            self.data_out = Path(self.args['data_out']).expanduser()
            os.makedirs(self.data_out, exist_ok=True)
            timestamp = dt.now().strftime('%Y-%m-%d_%H-%M-%S')
            filename = f'{self.data_out}/{self.args["plane_type"]}_{id}_{timestamp}.csv'
            worker_df.write_csv(str(filename))
        except Exception as e:
            print(traceback.format_exc())
            print(f'Error saving dataframe for plane {id} : {e}')

    def stop(self):
        try:
            """Finalize the worker by listing saved dataframes."""
            files = glob.glob(os.path.join(self.data_out, '**'), recursive=True
                )
            df_files = [f for f in files if re.search('\\.(csv|parquet)$', f)]
            n_df = len(df_files)
            if self.verbose > 0:
                print(f'FlightTrajectoryWorker.worker_end - {n_df} dataframes:')
                for f in df_files:
                    print(Path(f))
                if not n_df:
                    print('No dataframe created')
        except Exception as err:
            print(f'Error while trying to find dataframes: {err}')
        super().stop()
