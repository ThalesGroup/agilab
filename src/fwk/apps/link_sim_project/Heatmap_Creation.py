import numpy as np
from noise import pnoise2
import multiprocessing as mp
import matplotlib.pyplot as plt
from pathlib import Path
import os

class SpatialHeatmap:
    def __init__(
        self,
        x_min, x_max, z_min, z_max,
        step,
        center=(0,0),
        cloud_presence_threshold=0.0,
        cloud_noise_scale=None,
        density_noise_scale=None,
        cloud_amplitude=1.5,
        tile_size_x=50,
        tile_size_z=50,
        num_cores=None,
        heatmap=None
    ):
        self.x_min = x_min
        self.x_max = x_max
        self.z_min = z_min
        self.z_max = z_max
        self.step = step
        self.center = center
        self.cloud_presence_threshold = cloud_presence_threshold
        self.cloud_noise_scale = cloud_noise_scale or 1 / 200_000.0
        self.density_noise_scale = density_noise_scale or 1 / 300_000.0
        self.cloud_amplitude = cloud_amplitude
        self.tile_size_x = tile_size_x
        self.tile_size_z = tile_size_z
        self.num_cores = num_cores or mp.cpu_count()

        self.x_coords = np.arange(x_min, x_max, step)
        self.z_coords = np.arange(z_min, z_max, step)

        self.nx = len(self.x_coords)
        self.nz = len(self.z_coords)

        if heatmap is not None:
            self.heatmap = heatmap
        else:
            self.heatmap = self._generate_heatmap()
    @classmethod
    def load(cls, filename):
        path = Path(filename)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {filename}")
        data = np.load(filename)
        obj = cls(
            x_min=data['x_min'].item(),
            x_max=data['x_max'].item(),
            z_min=data['z_min'].item(),
            z_max=data['z_max'].item(),
            step=data['step'].item(),
            center=tuple(data['center']),
            cloud_presence_threshold=data['cloud_presence_threshold'].item(),
            cloud_noise_scale=data['cloud_noise_scale'].item(),
            density_noise_scale=data['density_noise_scale'].item(),
            cloud_amplitude=data['cloud_amplitude'].item(),
            tile_size_x=data['tile_size_x'].item(),
            tile_size_z=data['tile_size_z'].item(),
            heatmap=data['heatmap'],  # Pass the heatmap directly
        )
        return obj
    @classmethod
    def from_file_or_generate(cls, save_location, **kwargs):
        """
        Factory method: load from file if exists, else generate new heatmap
        kwargs are passed to __init__ if generating.
        """
        path = Path(save_location)
        if save_location and path.is_file():
            print(f"Loading heatmap from {save_location}")
            return cls.load(save_location)
        else:
            if save_location:
                print(f"Save file does not exist: {save_location}, generating new heatmap.")
            return cls(**kwargs)
    def _perlin2d_scalar(self, x, z, octaves, persistence=0.5, lacunarity=2.0):
        return pnoise2(x, z, octaves=octaves, persistence=persistence, lacunarity=lacunarity)
    def _process_tile(self, tile_bounds):
        z_start, z_end, x_start, x_end = tile_bounds
        rows = z_end - z_start
        cols = x_end - x_start

        tile_heatmap = np.zeros((rows, cols), dtype=np.float32)

        for i_local, i in enumerate(range(z_start, z_end)):
            z = self.z_coords[i]
            for j_local, j in enumerate(range(x_start, x_end)):
                x = self.x_coords[j]

                nx_presence = (x + self.center[0]) * self.cloud_noise_scale
                nz_presence = (z + self.center[1]) * self.cloud_noise_scale
                presence_val = self._perlin2d_scalar(nx_presence, nz_presence, octaves=4, persistence=0.5, lacunarity=2.0)

                if presence_val > self.cloud_presence_threshold:
                    nx_density = (x + self.center[0]) * self.density_noise_scale
                    nz_density = (z + self.center[1]) * self.density_noise_scale
                    density_val = self._perlin2d_scalar(nx_density, nz_density, octaves=2)
                    density_norm = (density_val+0.5) / 2
                    density = density_norm * self.cloud_amplitude
                    tile_heatmap[i_local, j_local] = np.clip(density, 0,9999)
                else:
                    tile_heatmap[i_local, j_local] = 0

        return (z_start, z_end, x_start, x_end, tile_heatmap)
    def _generate_heatmap(self):
        # Create tile bounds
        tile_bounds_list = []
        for z_start in range(0, self.nz, self.tile_size_z):
            z_end = min(z_start + self.tile_size_z, self.nz)
            for x_start in range(0, self.nx, self.tile_size_x):
                x_end = min(x_start + self.tile_size_x, self.nx)
                tile_bounds_list.append((z_start, z_end, x_start, x_end))

        print(f"Generating heatmap with {len(tile_bounds_list)} tiles on {self.num_cores} cores...")

        with mp.Pool(self.num_cores) as pool:
            results = pool.map(self._process_tile, tile_bounds_list)

        heatmap = np.zeros((self.nz, self.nx), dtype=np.float32)
        for z_start, z_end, x_start, x_end, tile in results:
            heatmap[z_start:z_end, x_start:x_end] = tile

        return heatmap
    def query_points(self, points: np.ndarray) -> np.ndarray:
        """
        Query heatmap values at multiple (X, Y, Z) points.
        Returns an array of heatmap values sampled at the (X, Z) coordinates of the points.

        Args:
            points (np.ndarray): Array of shape (N, 3), with columns [X, Y, Z].

        Returns:
            np.ndarray: Array of length N with heatmap values at corresponding (X, Z) points.
        """
        if points.shape[1] != 3:
            raise ValueError("Input points array must have shape (N, 3)")

        # Extract X and Z from points
        xs = points[:, 0]
        zs = points[:, 2]

        # Convert coords to indices
        rows, cols = self.coord_to_index(xs, zs)

        # Prepare output array
        values = np.zeros(len(points), dtype=np.float32)

        # For each point, fetch heatmap value if in bounds
        for i, (row, col) in enumerate(zip(rows, cols)):
            if 0 <= row < self.nz and 0 <= col < self.nx:
                values[i] = self.heatmap[row, col]
            else:
                values[i] = 0.0

        return values
    def coord_to_index(self, x, z):
        """
        Vectorized coordinate to index conversion.
        Accepts scalar or numpy arrays for x and z.
        Returns rows and cols as numpy arrays.
        """
        x = np.asarray(x)
        z = np.asarray(z)

        cols = np.round(((x - self.center[0]) + (self.x_max - self.x_min) / 2) / self.step).astype(int)
        rows = np.round(((z - self.center[1]) + (self.z_max - self.z_min) / 2) / self.step).astype(int)
        return rows, cols
    def __getitem__(self, coords):
        if isinstance(coords, tuple) and len(coords) == 2:
            x, z = coords
            # Shift query coords by center offset because the grid coords exclude center:
            # The grid coordinates self.x_coords are absolute world coords,
            # so no shift is necessary here.
            row, col = self.coord_to_index(x, z)
            print(row,col)
            if 0 <= row < self.nz and 0 <= col < self.nx:
                return self.heatmap[row, col]
            else:
                return 0.0  # Out of bounds return 0
        else:
            raise KeyError("Coordinates must be a tuple (x, z)")
    def plot(self):
        plt.figure(figsize=(10, 10))
        plt.imshow(self.heatmap, origin='lower', cmap='viridis',
                extent=[self.x_min, self.x_max, self.z_min, self.z_max],
                vmax=self.heatmap.max())  # <-- set vmax dynamically here
        plt.colorbar(label='Cloud Density')
        plt.title('Generated Cloud Density Heatmap')
        plt.xlabel('X (meters)')
        plt.ylabel('Z (meters)')
        plt.tight_layout()
        plt.show()
    def save_png(self, filename):
        plt.imsave(filename, self.heatmap, cmap='viridis')
        print(f"Heatmap saved to {filename}")
    def save(self, filename):
        if os.path.exists(filename):
            os.remove(filename)
            print("File removed.")
        else:
            print("File does not exist.")
        np.savez_compressed(
            filename,
            heatmap=self.heatmap,
            x_min=self.x_min,
            x_max=self.x_max,
            z_min=self.z_min,
            z_max=self.z_max,
            step=self.step,
            center=self.center,
            cloud_presence_threshold=self.cloud_presence_threshold,
            cloud_noise_scale=self.cloud_noise_scale,
            density_noise_scale=self.density_noise_scale,
            cloud_amplitude=self.cloud_amplitude,
            tile_size_x=self.tile_size_x,
            tile_size_z=self.tile_size_z,
        )
        print(f"Heatmap data and properties saved to {filename}")

# === Example usage ===
if __name__ == "__main__":
    heatmap_obj = SpatialHeatmap.from_file_or_generate(
        save_location="CloudMapIvdl.npz",
        x_min=-1_000_000, x_max=1_000_000,
        z_min=-1_000_000, z_max=1_000_000,
        step=500,
        cloud_amplitude=50.0,
        tile_size_x=50,
        tile_size_z=50,
        density_noise_scale=0.000005,
        cloud_noise_scale=0.000006,
        center=(264_768.0, 5_278_273.0),
    )
    
    heatmap_obj.save("CloudMapSat.npz")
    # heatmap_obj.plot()