# Spatial Heatmap and Line-of-Sight Simulation

This documentation describes the modules for modeling cloud fields and line-of-sight communication between aircraft/satellites, including all signal, geometry, and physics calculations.

---

## Table of Contents

1. [SpatialHeatmap](#spatialheatmap)
2. [Plane](#plane)
3. [Standalone Functions](#standalone-functions)
4. [Math and Physics](#math-and-physics-references)

---

## SpatialHeatmap

### Overview

Simulates a 2D spatial field (e.g., cloud density) over a specified area using Perlin noise, with optional disk caching and multiprocessing. you can create your own clouds heatmap using the Heatmap_Creation.py script.

---

### `__init__`

**Purpose:**
Initializes a spatial grid and generates (or loads) a cloud field using Perlin noise.

**Key Inputs:**

* `x_min, x_max`, `z_min, z_max`: Bounds (meters)
* `step`: Grid resolution (meters)
* `center`: Noise offset
* `cloud_presence_threshold`: Presence threshold
* `cloud_noise_scale`, `density_noise_scale`: Noise frequency scaling
* `cloud_amplitude`: Max cloud density
* `tile_size_x, tile_size_z`: Tiling for multiprocessing

**Outputs:**
Creates attributes like `self.heatmap`, `self.x_coords`, etc.

**Math/Physics:**
Uses Perlin noise (see below) to produce fractal cloud fields.
Multiple octaves are summed:

$$
\text{noise}(x, z) = \sum_{i=0}^{\text{octaves}-1} \text{amplitude}_i \cdot \text{perlin}\big(\text{frequency}_i \cdot (x, z)\big)
$$

with

$$
\text{amplitude}_i = \text{persistence}^i, \qquad \text{frequency}_i = \text{lacunarity}^i
$$

---

### `load(filename)`

Loads a saved heatmap from disk as a compressed `.npz`.

---

### `from_file_or_generate(save_location, **kwargs)`

Loads heatmap from disk if available, else generates a new one and returns the `SpatialHeatmap`.

---

### `_perlin2d_scalar(x, z, octaves, ...)`

Returns the Perlin noise value at \$(x, z)\$ with the specified number of octaves.

---

### `_process_tile(tile_bounds)`

Computes heatmap values for a tile (rectangular subgrid), using Perlin noise for cloud presence and density.

---

### `_generate_heatmap()`

Generates the complete grid by computing tiles in parallel and combining them.

---

### `query_points(points)`

Returns heatmap values at given \$(X, Y, Z)\$ points (using only \$X, Z\$).

---

### `coord_to_index(x, z)`

Converts \$(x, z)\$ world coordinates to grid indices.

---

### `__getitem__(coords)`

Enables heatmap querying via `heatmap[x, z]` syntax.

---

### `save(filename)`

Saves the grid and all parameters to a `.npz` file.

---

## Plane

### Overview

Bundles all config and data for a scenario: cloud fields, service definitions, flights, and satellites.

---

### `__init__`

Loads input data and cloud heatmaps for the simulation.

---

### `calculate_line_of_sight_matrix(plane_id)`

For a given plane, computes the time series of communication and signal characteristics (including cloud loss, path loss, and more) to all other planes.

---

## Standalone Functions

---

### `compute_bearing_and_pitch(A, B)`

Given arrays \$A\$ and \$B\$ with geographic positions, computes:

#### Bearing

The compass bearing from \$A\$ to \$B\$ (in degrees):

$$
\theta = \arctan2\left( \sin(\Delta \lambda) \cdot \cos \phi_2, \ \cos \phi_1 \cdot \sin \phi_2 - \sin \phi_1 \cdot \cos \phi_2 \cdot \cos(\Delta \lambda) \right)
$$

where \$\phi\$ is latitude in radians, and \$\Delta \lambda\$ is the longitude difference.

#### Pitch

The elevation angle above the local horizontal from \$A\$ to \$B\$:

$$
\text{pitch} = \arctan2\left( h_2 - h_1, \ \text{surface distance} \right)
$$

---

### `calculate_cloud_loss(origins, target_origins, angles, max_d, heatmaps)`

Returns the (approximate) cloud attenuation loss along the path, by sampling a heatmap.

---

### `convert_angles_to_directions(angles)`

Converts \[bearing, pitch] in degrees to a 3D unit direction vector.

**Math:**
If bearing \$\beta\$ (deg) and pitch \$p\$ (deg):

$$
\begin{align*}
x &= \cos(p) \cdot \sin(\beta) \\
y &= \cos(p) \cdot \cos(\beta) \\
z &= \sin(p)
\end{align*}
$$

All angles are converted to radians first. Vectors are normalized.

---

### `geo_to_xyz(coords)`

Converts latitude, longitude, and altitude to Cartesian \$(X, Y, Z)\$ using a flat Earth approximation:

$$
\begin{align*}
x &= R \cdot \lambda \\
y &= R \cdot \phi \\
z &= h
\end{align*}
$$

where \$R\$ is Earth’s radius (meters), \$\phi\$ and \$\lambda\$ are latitude and longitude (radians), and \$h\$ is altitude.

---

### `combine_csvs_from_folder(flight_path, sat_path, index_column='time_s')`

Reads and combines all flight and satellite CSVs, aligning on the `index_column` and forward-filling gaps.

---

### `plot_1d_array_to_html(arr, filename, ...)`

Plots a 1D array using Plotly and saves as HTML.

---

### `calculate_capacity_from_snr_db(bandwidth_hz, snr_db)`

Computes the Shannon capacity (Mbps):

$$
C = B \cdot \log_2 \left( 1 + \text{SNR}_{\text{linear}} \right)
$$

where \$C\$ is capacity in Mbps, \$B\$ is bandwidth in Hz, and

$$
\text{SNR}_{\text{linear}} = 10^{\text{SNR}_{\text{dB}} / 10}
$$

---

### `watts_to_dBm(power_watts)`

Converts Watts to dBm:

$$
P_{\text{dBm}} = 10 \cdot \log_{10}(P_{\text{watts}} \times 1000)
$$

---

### `calculate_antenna_gain(hpowbw_deg, efficiency)`

Approximates antenna gain in dBi for given beamwidths and efficiency:

$$
G_{\text{linear}} = \eta \cdot \frac{41253}{\text{HPBW}_{az} \cdot \text{HPBW}_{el}}
$$

$$
G_{\text{dBi}} = 10 \cdot \log_{10}(G_{\text{linear}})
$$

where \$41253 = 4\pi\$ (steradians) converted to deg², and \$\eta\$ is efficiency \$(0 < \eta \leq 1)\$.

---

### `calculate_off_axis_loss_elliptical(hpbw_degrees, off_axis_angles, ref_loss_db, ref_frac)`

Models antenna off-axis loss (dB) as a 2D elliptical Gaussian:

$$
L(\theta) = k \theta^2
$$

where \$k\$ is calibrated such that:

$$
L(\text{ref\_frac} \cdot \text{HPBW}) = \text{ref\_loss\_db}
$$

and total loss is sum in azimuth and elevation.

---

### `calculate_fspl(frequency_mhz, distance_km)`

Computes free-space path loss (FSPL) in dB:

$$
\text{FSPL} = 32.44 + 20 \cdot \log_{10}(f_{\text{MHz}}) + 20 \cdot \log_{10}(d_{\text{km}})
$$

---

### `calculate_haversine_distance_3d(P, Q)`

Returns 3D distance between geographic points \$(\text{lat}, \text{lon}, h)\$:

* Surface distance (haversine):

  $$
  a = \sin^2\left( \frac{\Delta \phi}{2} \right) + \cos \phi_1 \cos \phi_2 \sin^2 \left( \frac{\Delta \lambda}{2} \right)
  $$

  $$
  \text{surface distance} = 2R \arctan2(\sqrt{a}, \sqrt{1-a})
  $$

* 3D:

  $$
  d_{3D} = \sqrt{(\text{surface distance})^2 + (h_2 - h_1)^2}
  $$

---

### `approximate_lat_lon_diff_meters(lat1, lon1, lat2, lon2)`

Equirectangular projection for small distances:

$$
\begin{align*}
dx &= R \cdot (\lambda_2 - \lambda_1) \cdot \cos\left(\frac{\phi_1 + \phi_2}{2}\right) \\
dy &= R \cdot (\phi_2 - \phi_1)
\end{align*}
$$

where \$R\$ is Earth’s radius, \$\phi\$ is latitude, \$\lambda\$ is longitude (in radians).

---

### `compute_az_el_error(P0, pitch_deg, yaw_deg, B)`

For each time-step, computes:

* **Azimuth error:**
  The signed angular difference between the sensor's yaw and the bearing to the target, weighted by \$\cos^2(\text{elevation})\$.

* **Elevation error:**
  The difference between the sensor's pitch and the actual elevation angle to the target.

---

### `compute_relative_orientation_matrix(plane, sensor)`

Combines the aircraft orientation and sensor mounting to compute the actual pointing direction.

---

### `compute_best_sensor_off_axis(plane_1, plane_2, sensors)`

Given all possible sensors, picks the one with minimal pointing error for each time, and computes the corresponding off-axis loss.

---

### `compute_line_of_sight(plane_1, plane_2, sensor, sensor_target, heatmaps)`

Computes the full radio link budget between two aircraft (or an aircraft and a satellite), including:

* Free-space path loss
* Antenna off-axis loss
* Cloud attenuation (via sampled heatmaps)
* Received power
* SNR
* Shannon capacity

**Signal equation:**

$$
P_r = P_t + G_t + G_r - (\text{off-axis loss}) - \text{FSPL} - (\text{target off-axis loss}) - (\text{cloud loss})
$$

SNR:

$$
\text{SNR}_{\text{dB}} = P_r - (N_0 + 10 \log_{10}(B))
$$

---

## Math and Physics References

* [Perlin Noise](https://en.wikipedia.org/wiki/Perlin_noise)
* [Friis Transmission Equation](https://en.wikipedia.org/wiki/Friis_transmission_equation)
* [Haversine Formula](https://en.wikipedia.org/wiki/Haversine_formula)
* [Antenna Gain](https://en.wikipedia.org/wiki/Antenna_gain)
* [Shannon-Hartley Theorem](https://en.wikipedia.org/wiki/Shannon%E2%80%93Hartley_theorem)

---

> **Tip:**
> For best equation rendering in VS Code, use the built-in Markdown preview (`Ctrl+Shift+V`).
> If using another editor, be sure it supports GitHub-flavored Markdown and KaTeX/MathJax math blocks.
