"""
Digital Elevation Model (DEM) Generator Module
Performs automatic UTM projection and interpolates continuous high-resolution
topographic elevation grids from sparse or dense 3D contour lines.
"""

from typing import Dict, Any, Tuple, Optional
import numpy as np
from pyproj import Transformer, CRS
from scipy.interpolate import griddata
from scipy.ndimage import gaussian_filter


class DEMGrid:
    """
    Encapsulates a regular 2D Digital Elevation Model grid with spatial georeferencing,
    metric projection transformers, and derived terrain gradients.
    """

    def __init__(self,
                 elevation: np.ndarray,
                 x_coords: np.ndarray,
                 y_coords: np.ndarray,
                 resolution_m: float,
                 utm_epsg: int,
                 utm_zone: int,
                 is_northern: bool):
        self.elevation = elevation
        self.x_coords = x_coords  # 1D array of UTM Easting
        self.y_coords = y_coords  # 1D array of UTM Northing (increasing from south to north)
        self.resolution_m = float(resolution_m)
        self.utm_epsg = int(utm_epsg)
        self.utm_zone = int(utm_zone)
        self.is_northern = is_northern

        self.rows, self.cols = elevation.shape

        # Coordinate transformers
        self.transformer_to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{self.utm_epsg}", always_xy=True)
        self.transformer_to_wgs84 = Transformer.from_crs(f"EPSG:{self.utm_epsg}", "EPSG:4326", always_xy=True)

        # Compute slope, aspect and terrain metrics
        self.slope_percent, self.slope_degrees, self.aspect_degrees = self._compute_gradients()

    def _compute_gradients(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Compute terrain slope (percent & degrees) and aspect using central differences."""
        # Gradient along y (rows) and x (cols)
        # Note: y_coords typically increases with row index if sorted ascending
        dy, dx = np.gradient(self.elevation, self.resolution_m, self.resolution_m)
        slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))
        slope_deg = np.rad2deg(slope_rad)
        slope_pct = np.tan(slope_rad) * 100.0

        # Aspect: direction of steepest slope (0 = North, 90 = East, etc.)
        aspect_rad = np.arctan2(-dx, dy)
        aspect_deg = (np.rad2deg(aspect_rad) + 360.0) % 360.0

        return slope_pct, slope_deg, aspect_deg

    def grid_to_utm(self, row: int, col: int) -> Tuple[float, float]:
        """Convert 2D grid index (row, col) to UTM (Easting, Northing) coordinates."""
        row_clamped = max(0, min(self.rows - 1, row))
        col_clamped = max(0, min(self.cols - 1, col))
        return float(self.x_coords[col_clamped]), float(self.y_coords[row_clamped])

    def utm_to_grid(self, easting: float, northing: float) -> Tuple[int, int]:
        """Convert UTM (Easting, Northing) to closest grid index (row, col)."""
        col = int(np.clip(np.round((easting - self.x_coords[0]) / self.resolution_m), 0, self.cols - 1))
        row = int(np.clip(np.round((northing - self.y_coords[0]) / self.resolution_m), 0, self.rows - 1))
        return row, col

    def grid_to_wgs84(self, row: int, col: int) -> Tuple[float, float]:
        """Convert grid index (row, col) to geographic (Longitude, Latitude) in WGS84."""
        easting, northing = self.grid_to_utm(row, col)
        lon, lat = self.transformer_to_wgs84.transform(easting, northing)
        return float(lon), float(lat)

    def wgs84_to_grid(self, lon: float, lat: float) -> Tuple[int, int]:
        """Convert geographic (Longitude, Latitude) to grid index (row, col)."""
        easting, northing = self.transformer_to_utm.transform(lon, lat)
        return self.utm_to_grid(easting, northing)

    @property
    def stats(self) -> Dict[str, float]:
        """Summary statistics of the elevation grid."""
        valid_elev = self.elevation[~np.isnan(self.elevation)]
        return {
            'min_elevation': float(np.min(valid_elev)),
            'max_elevation': float(np.max(valid_elev)),
            'mean_elevation': float(np.mean(valid_elev)),
            'std_elevation': float(np.std(valid_elev)),
            'relief': float(np.max(valid_elev) - np.min(valid_elev)),
            'mean_slope_percent': float(np.nanmean(self.slope_percent)),
            'mean_slope_degrees': float(np.nanmean(self.slope_degrees)),
            'resolution_m': self.resolution_m,
            'grid_rows': int(self.rows),
            'grid_cols': int(self.cols),
            'total_grid_cells': int(self.rows * self.cols)
        }


class DEMGenerator:
    """
    Generates high-resolution Digital Elevation Model grids from parsed KML/KMZ contour data.
    """

    def __init__(self, default_resolution_m: float = 10.0):
        self.default_resolution_m = default_resolution_m

    def generate_dem(self, parsed_data: Dict[str, Any], resolution_m: Optional[float] = None, smooth_sigma: float = 0.5) -> DEMGrid:
        """
        Builds a georeferenced DEMGrid from parsed contour points.
        """
        pts = parsed_data.get('point_cloud')
        if pts is None or len(pts) == 0:
            raise ValueError("No 3D points available for DEM generation.")

        res_m = float(resolution_m if resolution_m and resolution_m > 0 else self.default_resolution_m)

        # 1. Determine optimal UTM Zone
        center_lon = parsed_data['bounds']['center_lon']
        center_lat = parsed_data['bounds']['center_lat']
        utm_zone = int(np.floor((center_lon + 180.0) / 6.0)) + 1
        is_northern = center_lat >= 0
        epsg = (32600 + utm_zone) if is_northern else (32700 + utm_zone)

        # 2. Project points from WGS84 (Lon, Lat) to UTM (Easting, Northing)
        transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
        eastings, northings = transformer.transform(pts[:, 0], pts[:, 1])
        elevations = pts[:, 2]

        # 3. Subsample if points are extremely dense to optimize Delaunay triangulation
        num_points = len(eastings)
        if num_points > 80000:
            step = int(np.ceil(num_points / 60000))
            sample_idx = np.arange(0, num_points, step)
            pts_utm = np.column_stack([eastings[sample_idx], northings[sample_idx]])
            vals = elevations[sample_idx]
        else:
            pts_utm = np.column_stack([eastings, northings])
            vals = elevations

        # 4. Generate regular metric meshgrid
        x_min, x_max = float(np.min(eastings)), float(np.max(eastings))
        y_min, y_max = float(np.min(northings)), float(np.max(northings))

        # Pad bounding box slightly to avoid edge boundary artifacts
        padding = res_m * 1.5
        x_coords = np.arange(x_min - padding, x_max + padding + res_m, res_m)
        y_coords = np.arange(y_min - padding, y_max + padding + res_m, res_m)
        grid_x, grid_y = np.meshgrid(x_coords, y_coords)

        # 5. Interpolate continuous elevation surface
        # Use linear interpolation (TIN barycentric) with nearest neighbor fallback for outer hull
        dem_linear = griddata(pts_utm, vals, (grid_x, grid_y), method='linear')

        # Fill any outer NaN regions with nearest neighbor
        nan_mask = np.isnan(dem_linear)
        if np.any(nan_mask):
            dem_nearest = griddata(pts_utm, vals, (grid_x[nan_mask], grid_y[nan_mask]), method='nearest')
            dem_linear[nan_mask] = dem_nearest

        # 6. Apply gentle spatial smoothing filter to eliminate digital stepping artifacts
        if smooth_sigma > 0:
            dem_elevation = gaussian_filter(dem_linear, sigma=smooth_sigma)
        else:
            dem_elevation = dem_linear

        return DEMGrid(
            elevation=dem_elevation,
            x_coords=x_coords,
            y_coords=y_coords,
            resolution_m=res_m,
            utm_epsg=epsg,
            utm_zone=utm_zone,
            is_northern=is_northern
        )
