# Flight Clone Project

This application has been generated at 100% by Codex cli in half a workday from 2 others humanly develop applications.

## Quick start

```bash
cd src/agilab/examples/flight_clone
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python AGI_get_distrib_flight_clone.py
```

```bash
cd src/agilab/apps/flight_clone_project
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python ../../examples/flight_clone/AGI_run_flight_clone.py
```

## Ukraine satellite overlay

- The cloning workflow now recenters every dataset over Ukraine (Kyiv → Dnipro/Lviv/Odesa). The manager renormalises `waypoints.geojson`, `beams.csv`, and `satellites.csv` once per dataset and drops a `.ukraine_localized` marker so subsequent runs keep your manual tweaks intact.
- Worker preprocessing matches every telemetry row with the closest antenna beam polygon and merges the `satellites.csv` metadata so `beam_sat_ant`, `beam_long/lat/alt`, and distance-to-beam metrics are persisted inside each exported dataframe.
- When `norad_3le.txt` is present the worker calls `sat_trajectory_worker.compute_trajectory` to attach `sat_track_lat/long/alt_m`, `sat_speed_ms`, `sat_ground_distance_km`, and `sat_look_angle_deg` columns. The `view_maps` page can overlay the satellite path (toggle in the sidebar) and the beam filter includes a coverage summary table for quick QA.

## Test suite

Run these commands from `src/agilab/apps/flight_clone_project`:

```bash
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python app_test.py
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python test/_test_call_worker.py
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python test/_test_flight_clone_manager.py
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python test/_test_flight_clone_worker.py
```

## Worker packaging

```bash
cd src/agilab/apps/flight_clone_project
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python build.py \
  bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" \
  -d "$HOME/wenv/flight_clone_worker"
```

```bash
cd "$HOME/wenv/flight_clone_worker"
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python build.py \
  build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" \
  -b "$HOME/wenv/flight_clone_worker"
```

## Waypoint regeneration

- Set `regenerate_waypoints = true` in the Streamlit form or `app_settings.toml` to rebuild `waypoints.geojson` before a run. The freshly generated USWC templates are immediately translated over Ukraine by the manager, so you always end up with Kyiv-centric flight paths.
- When triggered, the runtime first executes `tools/uswc_trajectory_forward.py` and `tools/uswc_trajectory_reverse.py` (when present) so the reference tracks stay in sync with the latest generator logic. These helpers live inside this app and never reach into `agilab/src`.
- The refreshed forward/reverse templates are loaded exclusively from the active dataset directory (for example `flight_clone/dataset/uswc_trajectories_forward.geojson`); the source tree is never consulted when regenerating waypoints.
- All runtime runs now synthesize fresh waypoint variants for every requested flight. The original templates act purely as seeds; the split catalog (`waypoints_split/…`) only contains the generated `*-S###` variants sized to match `num_flights`.
- Disable the flag after bootstrapping to avoid overwriting manual edits to the waypoint catalog.
- Worker outputs are written to a sibling directory named `dataframe` next to the configured dataset folder (for example `flight_clone/dataframe` when your dataset lives at `flight_clone/dataset`).

## Post-install checks

```bash
cd src/agilab/apps/flight_clone_project
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python "$HOME/wenv/flight_clone_worker/src/flight_clone_worker/post_install.py" \
  src/agilab/apps/flight_clone_project 1 "$HOME/flight_clone"
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python src/flight_clone_worker/pre_install.py \
  remove_decorators --verbose --worker_path "$HOME/wenv/flight_clone_worker/src/flight_clone_worker/flight_clone_worker.py"
```

Refer to `src/agilab/apps/README.md` for the complete launch matrix.

---

## Appendix: Trajectory model notes
## Overview

The `plane_trajectory` class models the flight of an aircraft through a series of geographic waypoints, simulating phases such as takeoff roll, climb, cruising, turns, and descent. It logs key state variables (position, speed, attitude angles) at each time step, allowing analysis and visualization of the trajectory.

---

## 1. Initialization & Plane Characteristics

When you instantiate the class, you provide flight-specific parameters:

* **Waypoints**: List of `(latitude, longitude, altitude)` triplets defining the path.

* **Max Speed** $V_{max}$: in km/h, converted to m/s by

  $V_{max, m/s} = \frac{V_{max}\times1000}{3600}$

* **Acceleration** $a$: in m/s².

* **Angular speeds**:

  * **Pitch**: $\omega_{pitch}$ in °/s
  * **Roll**: $\omega_{roll}$ in °/s
  * **Yaw**: $\omega_{yaw}$ in °/s

These parameters allow differentiation between aircraft with varying performance envelopes (faster climb rates, sharper turns, higher cruise speeds, etc).

---

## 2. Initialization & Key Aircraft Parameters

When you instantiate `plane_trajectory`, several core state variables and performance limits are set up without diving into full code:

1. **Waypoint Setup**: Ensures at least two waypoints; missing altitudes default to a preset value.

2. **Initial Flight State**: Assigns starting position (latitude, longitude), altitude, and zeros for speed, roll, pitch, yaw, time, and cumulative distance.

3. **Performance Conversion**:

   * **Max speed** (km/h) → **m/s** via
   $$
   V_{\text{max},\text{m/s}} \;=\; \frac{V_{\text{max}}\times 1000}{3600}
   $$
   * **Angular rates** (°/s) and **linear acceleration** (m/s²) are stored directly.

4. **Threshold Derivation**:

   * **Pitch enable speed**: fraction of cruise speed below which pitch changes are blocked.
   * **Waypoint arrival radius**: half the cruise speed in meters.
   * **Landing and stall speeds** converted to m/s from km/h.

5. **Climb/Descent Flags**: Boolean switches allow skipping climb or descent phases if set to False.

## 3. Geographic & Angular Calculations

Time-Step Simulation & Physics

Each simulation phase advances in fixed time steps $\Delta t$ (default 1 s). At each step:

1. **Control Laws**

   * **Pitch target** set by flight phase (e.g. climb uses `max_pitch`).
   * **Speed target** is constant cruise speed $V_{max}$.
   * Angular adjustments limited by $\omega_{pitch}$, $\omega_{roll}$:

     $\Delta \theta = \operatorname{clip}(\theta_{target}-\theta, \pm\omega\,\Delta t)$

2. **Velocity Components**

   * **Vertical speed**: $V_v = V\sin(pitch)$
   * **Horizontal speed**: $V_h = V\cos(pitch)$

3. **State Updates**

   * **Altitude**: $h_{new} = h + V_v\Delta t$

   * **Speed**: accelerate or decelerate toward target using:

     $V_{new} = \min\bigl(V + a\Delta t\,\sin(0.05\pi + 0.95\pi\tfrac{V}{V_{max}}),\,V_{max}\bigr)$

   * **Attitude angles** adjusted incrementally.

4. **Geographic Position**

   Using `geopy.geodesic`, we move $V_h\Delta t$ meters from the current lat/lon along the current bearing:

   ```python
   dest = geodesic(meters=V_h*dt).destination(start_point, bearing)
   (lat, lon) = (dest.latitude, dest.longitude)
   ```

---

## 4. Phase Logic & Level-Off Prediction

### 4.1. Climb & Level-Off

To smoothly transition from climb to level flight at target altitude $h^*$, we predict altitude overshoot due to pitch reduction:

1. **Time to level**: $t_{level} = \tfrac{pitch}{\omega_{pitch}}$
2. **Average pitch**: $p_{avg} = \tfrac{pitch}{2}$
3. **Vertical gain during leveling**:

   $\Delta h_{est} = V\sin(p_{avg})\,t_{level}$

Thus we begin leveling-off when $h \ge h^* - \Delta h_{est}$.

### 4.2. Turning & Roll Dynamics

* Before a turn, compute needed rotation $\alpha$ to new waypoint bearing.
* Reduce speed to $V(1 - (1 - r)\sin(\alpha/180))$ where $r=$ max speed ratio while turning.
* Roll in small steps $\omega_{roll}\,\Delta t$ until desired bank angle.

---

## 5. Differentiating Aircraft

By varying:

* **`max_speed` and `vehicule_acceleration`**: faster climbs and cruise speeds.
* **`pitch_angular_speed` / `roll_angular_speed`**: quicker or slower attitude changes.
* **`max_pitch` / `max_roll`**: limits on climb angle and turn sharpness.
* **Landing & descent targets**: safe stall speed and pitch settings.

you can simulate different plane models, from agile fighters to heavy transports.

---

## 6. Usage & Outputs

1. Instantiate:

   ```python
   plane = plane_trajectory(waypoints=[...], max_speed=850, vehicule_acceleration=4.5)
   ```
2. Compute trajectory:

   ```python
   df = plane.calculate_trajectory(dt=1)
   ```
3. Visualize:

   * 2D plots via Plotly Express (`plot`)
   * 3D path via Plotly Graph Objects (`plot_3d_flight_path`)

The resulting `DataFrame` logs each second:

| time\_s | speed\_ms | alt\_m | roll\_deg | pitch\_deg | bearing\_deg | latitude | longitude | distance | phase |
| ------- | --------- | ------ | --------- | ---------- | ------------ | -------- | --------- | -------- | ----- |
