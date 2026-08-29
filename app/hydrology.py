"""
Hydrology Engine Module
Implements Priority-Flood depression filling, D8 flow routing, vectorized flow accumulation,
stream network extraction, topographic sink detection, and upstream watershed delineation.
"""

import os
os.environ['MPLCONFIGDIR'] = '/tmp/matplotlib'

import heapq
from typing import Dict, Any, Tuple, List, Optional
import numpy as np
from scipy.ndimage import label, find_objects
from shapely.geometry import Polygon, MultiPolygon, LineString, MultiLineString, mapping
from shapely.ops import unary_union
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from app.dem_generator import DEMGrid


# D8 Neighbor Offsets: (d_row, d_col, distance_multiplier)
# Directions: 0: East, 1: North-East, 2: North, 3: North-West,
#             4: West, 5: South-West, 6: South, 7: South-East
D8_NEIGHBORS = [
    (0, 1, 1.0),
    (1, 1, np.sqrt(2.0)),
    (1, 0, 1.0),
    (1, -1, np.sqrt(2.0)),
    (0, -1, 1.0),
    (-1, -1, np.sqrt(2.0)),
    (-1, 0, 1.0),
    (-1, 1, np.sqrt(2.0))
]


class HydrologyEngine:
    """
    Comprehensive hydrological analysis engine for digital elevation models.
    """

    def __init__(self):
        pass

    def analyze(self, dem: DEMGrid, stream_threshold_percentile: float = 98.0) -> Dict[str, Any]:
        """
        Runs complete hydrological simulation on the DEM:
        1. Depression filling & depression depth calculation
        2. D8 flow direction calculation
        3. Vectorized flow accumulation routing
        4. Stream network extraction
        5. Topographic depression/sink detection
        """
        filled_dem, depression_depth = self.fill_depressions(dem)
        flow_dir = self.compute_flow_direction(filled_dem, dem.resolution_m)
        flow_acc = self.compute_flow_accumulation(filled_dem, flow_dir)
        streams = self.extract_stream_network(dem, flow_acc, flow_dir, threshold_percentile=stream_threshold_percentile)
        depressions = self.detect_depressions(dem, filled_dem, depression_depth)

        return {
            'filled_elevation': filled_dem,
            'depression_depth': depression_depth,
            'flow_direction': flow_dir,
            'flow_accumulation': flow_acc,
            'streams': streams,
            'depressions': depressions
        }

    def fill_depressions(self, dem: DEMGrid) -> Tuple[np.ndarray, np.ndarray]:
        """
        Priority-Flood depression filling algorithm (Barnes et al. / Wang & Liu).
        Fills all internal sinks to their spillover saddle elevation so surface runoff routes continuously.
        """
        elev = dem.elevation.copy()
        rows, cols = elev.shape
        filled = np.full((rows, cols), np.inf, dtype=np.float64)
        pq: List[Tuple[float, int, int]] = []

        # Push edge boundary cells to the priority queue
        for r in range(rows):
            for c in (0, cols - 1):
                filled[r, c] = elev[r, c]
                heapq.heappush(pq, (elev[r, c], r, c))
        for c in range(cols):
            for r in (0, rows - 1):
                if filled[r, c] == np.inf:
                    filled[r, c] = elev[r, c]
                    heapq.heappush(pq, (elev[r, c], r, c))

        # 8-connectivity offsets
        offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

        # Priority-flood wavefront propagation
        while pq:
            z, r, c = heapq.heappop(pq)
            for dr, dc in offsets:
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols and filled[nr, nc] == np.inf:
                    # Maintain slight gradient to prevent flat routing loops
                    filled[nr, nc] = max(elev[nr, nc], z + 1e-5)
                    heapq.heappush(pq, (filled[nr, nc], nr, nc))

        depression_depth = np.maximum(0.0, filled - elev)
        return filled, depression_depth

    def compute_flow_direction(self, filled_dem: np.ndarray, resolution_m: float) -> np.ndarray:
        """
        Calculates D8 flow direction for each cell based on steepest slope descent.
        Returns 2D int array where value in [0..7] represents index in D8_NEIGHBORS, or -1 for boundary.
        """
        rows, cols = filled_dem.shape
        flow_dir = np.full((rows, cols), -1, dtype=np.int32)

        for r in range(rows):
            for c in range(cols):
                z_curr = filled_dem[r, c]
                max_slope = 0.0
                best_dir = -1
                for d, (dr, dc, dist) in enumerate(D8_NEIGHBORS):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols:
                        slope = (z_curr - filled_dem[nr, nc]) / (dist * resolution_m)
                        if slope > max_slope:
                            max_slope = slope
                            best_dir = d
                flow_dir[r, c] = best_dir

        return flow_dir

    def compute_flow_accumulation(self, filled_dem: np.ndarray, flow_dir: np.ndarray) -> np.ndarray:
        """
        Computes flow accumulation matrix using topological sort (elevation descending order).
        Each cell accumulates flow from all its upstream contributing cells in O(N) time.
        """
        rows, cols = filled_dem.shape
        order = np.argsort(-filled_dem.ravel())
        flow_acc = np.ones((rows, cols), dtype=np.float64)

        for idx in order:
            r, c = divmod(idx, cols)
            d = flow_dir[r, c]
            if d >= 0:
                dr, dc, _ = D8_NEIGHBORS[d]
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    flow_acc[nr, nc] += flow_acc[r, c]

        return flow_acc

    def extract_stream_network(self, dem: DEMGrid, flow_acc: np.ndarray, flow_dir: np.ndarray, threshold_percentile: float = 98.0) -> Dict[str, Any]:
        """
        Extracts stream flow channels where flow accumulation exceeds threshold.
        Returns GeoJSON MultiLineString of stream paths.
        """
        threshold = np.percentile(flow_acc, threshold_percentile)
        # Ensure threshold is reasonable (at least 100 cells)
        threshold = max(threshold, 50.0)

        rows, cols = flow_acc.shape
        stream_mask = flow_acc >= threshold

        line_segments = []
        for r in range(rows):
            for c in range(cols):
                if stream_mask[r, c]:
                    d = flow_dir[r, c]
                    if d >= 0:
                        dr, dc, _ = D8_NEIGHBORS[d]
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < rows and 0 <= nc < cols and stream_mask[nr, nc]:
                            lon1, lat1 = dem.grid_to_wgs84(r, c)
                            lon2, lat2 = dem.grid_to_wgs84(nr, nc)
                            line_segments.append([(lon1, lat1), (lon2, lat2)])

        geojson = {
            "type": "Feature",
            "properties": {
                "name": "Drainage / Stream Network",
                "threshold_cells": float(threshold),
                "threshold_area_m2": float(threshold * (dem.resolution_m ** 2))
            },
            "geometry": {
                "type": "MultiLineString",
                "coordinates": line_segments
            }
        }
        return geojson

    def detect_depressions(self, dem: DEMGrid, filled_dem: np.ndarray, depression_depth: np.ndarray,
                           min_depth_m: float = 0.2, min_area_m2: float = 100.0) -> List[Dict[str, Any]]:
        """
        Identifies connected topographic hollows/depressions (natural storage basins).
        """
        cell_area = dem.resolution_m ** 2
        min_cells = int(np.ceil(min_area_m2 / cell_area))

        sink_mask = depression_depth >= min_depth_m
        labeled_mask, num_features = label(sink_mask)

        depressions = []
        for feat_idx in range(1, num_features + 1):
            mask_feat = (labeled_mask == feat_idx)
            cell_count = np.sum(mask_feat)
            if cell_count < min_cells:
                continue

            r_indices, c_indices = np.where(mask_feat)
            depths = depression_depth[mask_feat]
            elevs = dem.elevation[mask_feat]

            max_depth = float(np.max(depths))
            mean_depth = float(np.mean(depths))
            min_elev = float(np.min(elevs))
            spill_elev = min_elev + max_depth
            volume_m3 = float(np.sum(depths) * cell_area)
            area_m2 = float(cell_count * cell_area)

            # Find lowest bottom cell
            min_idx = np.argmin(elevs)
            bottom_r = int(r_indices[min_idx])
            bottom_c = int(c_indices[min_idx])
            bottom_lon, bottom_lat = dem.grid_to_wgs84(bottom_r, bottom_c)
            bottom_easting, bottom_northing = dem.grid_to_utm(bottom_r, bottom_c)

            depressions.append({
                'id': f"depression_{feat_idx}",
                'bottom_grid': (bottom_r, bottom_c),
                'coordinates': {
                    'longitude': float(bottom_lon),
                    'latitude': float(bottom_lat),
                    'elevation_m': float(min_elev)
                },
                'utm_coordinates': {
                    'easting': float(bottom_easting),
                    'northing': float(bottom_northing)
                },
                'max_depth_m': round(max_depth, 2),
                'mean_depth_m': round(mean_depth, 2),
                'spill_elevation_m': round(spill_elev, 2),
                'surface_area_sq_m': round(area_m2, 1),
                'surface_area_ha': round(area_m2 / 10000.0, 3),
                'estimated_volume_m3': round(volume_m3, 1),
                'estimated_volume_liters': round(volume_m3 * 1000.0, 0),
                'cell_count': int(cell_count)
            })

        # Sort depressions by storage volume descending
        depressions.sort(key=lambda d: d['estimated_volume_m3'], reverse=True)
        return depressions

    def delineate_catchment(self, pour_point_grid: Tuple[int, int], flow_dir: np.ndarray, dem: DEMGrid) -> Dict[str, Any]:
        """
        Traces all upstream cells draining to the specified pour point (r0, c0) using BFS traversal.
        Extracts vector boundary polygon (GeoJSON), calculates surface area, perimeter, and elevation profile.
        """
        rows, cols = flow_dir.shape
        pr, pc = pour_point_grid
        pr = max(0, min(rows - 1, pr))
        pc = max(0, min(cols - 1, pc))

        # 1. Build inverted flow graph (target -> list of upstream sources)
        upstream_map: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
        for r in range(rows):
            for c in range(cols):
                d = flow_dir[r, c]
                if d >= 0:
                    dr, dc, _ = D8_NEIGHBORS[d]
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols:
                        upstream_map.setdefault((nr, nc), []).append((r, c))

        # 2. BFS Traversal to collect all upstream contributing cells
        catchment_mask = np.zeros((rows, cols), dtype=bool)
        queue = [(pr, pc)]
        catchment_mask[pr, pc] = True

        while queue:
            curr = queue.pop(0)
            for up in upstream_map.get(curr, []):
                if not catchment_mask[up[0], up[1]]:
                    catchment_mask[up[0], up[1]] = True
                    queue.append(up)

        cell_count = int(np.sum(catchment_mask))
        cell_area = dem.resolution_m ** 2
        area_sq_m = float(cell_count * cell_area)
        area_ha = float(area_sq_m / 10000.0)
        area_acres = float(area_sq_m / 4046.85642)

        # 3. Elevation & Terrain Statistics within Catchment
        catchment_elevs = dem.elevation[catchment_mask]
        catchment_slopes = dem.slope_percent[catchment_mask]

        min_elev = float(np.min(catchment_elevs))
        max_elev = float(np.max(catchment_elevs))
        mean_elev = float(np.mean(catchment_elevs))
        elev_range = float(max_elev - min_elev)
        mean_slope_pct = float(np.mean(catchment_slopes))
        mean_slope_deg = float(np.mean(dem.slope_degrees[catchment_mask]))

        # 4. Extract Vector Polygon boundary
        polygon_geojson, perimeter_m, bounds_wgs84 = self._polygonize_mask(catchment_mask, dem)

        # Catchment centroid
        mask_r, mask_c = np.where(catchment_mask)
        mean_r = float(np.mean(mask_r))
        mean_c = float(np.mean(mask_c))
        centroid_lon, centroid_lat = dem.grid_to_wgs84(int(round(mean_r)), int(round(mean_c)))

        return {
            'area_sq_meters': round(area_sq_m, 1),
            'area_hectares': round(area_ha, 3),
            'area_acres': round(area_acres, 3),
            'perimeter_meters': round(perimeter_m, 1),
            'cell_count': cell_count,
            'min_elevation_m': round(min_elev, 2),
            'max_elevation_m': round(max_elev, 2),
            'mean_elevation_m': round(mean_elev, 2),
            'elevation_range_m': round(elev_range, 2),
            'average_slope_percent': round(mean_slope_pct, 2),
            'average_slope_degrees': round(mean_slope_deg, 2),
            'centroid_wgs84': {
                'longitude': round(centroid_lon, 6),
                'latitude': round(centroid_lat, 6)
            },
            'bounds_wgs84': bounds_wgs84,
            'geojson': polygon_geojson,
            'catchment_mask': catchment_mask
        }

    def _polygonize_mask(self, mask: np.ndarray, dem: DEMGrid) -> Tuple[Dict[str, Any], float, Dict[str, float]]:
        """
        Converts 2D binary raster mask to a vector GeoJSON Polygon in WGS84 coordinates.
        Calculates exact metric perimeter in meters.
        """
        # Matplotlib contour extraction at level 0.5
        fig, ax = plt.subplots(figsize=(4, 4))
        cs = ax.contour(mask.astype(float), levels=[0.5])
        paths = cs.collections[0].get_paths() if cs.collections else []
        plt.close(fig)

        polygons_utm = []
        polygons_wgs = []

        for path in paths:
            v = path.vertices
            if len(v) < 4:
                continue

            grid_cols = v[:, 0]
            grid_rows = v[:, 1]

            eastings = dem.x_coords[0] + grid_cols * dem.resolution_m
            northings = dem.y_coords[0] + grid_rows * dem.resolution_m

            lons, lats = dem.transformer_to_wgs84.transform(eastings, northings)

            pts_utm = list(zip(eastings, northings))
            pts_wgs = list(zip(lons, lats))

            # Ensure ring is closed
            if pts_utm[0] != pts_utm[-1]:
                pts_utm.append(pts_utm[0])
                pts_wgs.append(pts_wgs[0])

            poly_u = Polygon(pts_utm)
            poly_w = Polygon(pts_wgs)

            if poly_u.is_valid and poly_u.area > 0:
                polygons_utm.append(poly_u)
                polygons_wgs.append(poly_w)

        if not polygons_utm:
            # Fallback: create bounding box polygon from mask cells
            r_idx, c_idx = np.where(mask)
            if len(r_idx) == 0:
                return {"type": "Polygon", "coordinates": []}, 0.0, {}
            r_min, r_max = int(np.min(r_idx)), int(np.max(r_idx))
            c_min, c_max = int(np.min(c_idx)), int(np.max(c_idx))
            p1 = dem.grid_to_wgs84(r_min, c_min)
            p2 = dem.grid_to_wgs84(r_max, c_min)
            p3 = dem.grid_to_wgs84(r_max, c_max)
            p4 = dem.grid_to_wgs84(r_min, c_max)
            coords = [[p1, p2, p3, p4, p1]]
            return {"type": "Polygon", "coordinates": coords}, 0.0, {}

        # Merge multiple polygon parts into single or multi-polygon
        union_utm = unary_union(polygons_utm)
        union_wgs = unary_union(polygons_wgs)

        # Simplify slightly to remove micro pixel steps while preserving area
        union_utm = union_utm.simplify(dem.resolution_m * 0.5, preserve_topology=True)
        perimeter_m = float(union_utm.length)

        geojson_geom = mapping(union_wgs)

        bounds = union_wgs.bounds
        bounds_dict = {
            'min_lon': float(bounds[0]),
            'min_lat': float(bounds[1]),
            'max_lon': float(bounds[2]),
            'max_lat': float(bounds[3])
        }

        geojson_feature = {
            "type": "Feature",
            "properties": {
                "name": "Catchment Boundary",
                "perimeter_m": round(perimeter_m, 1)
            },
            "geometry": geojson_geom
        }

        return geojson_feature, perimeter_m, bounds_dict

    def estimate_runoff(self, catchment_area_sq_m: float, annual_rainfall_mm: float = 1000.0, runoff_coefficient: float = 0.35) -> Dict[str, float]:
        """
        Estimates total annual water yield / runoff volume using the Rational Method.
        V = C * P * A
        where:
          C = runoff coefficient (dimensionless, 0.2-0.5 for rural/agricultural soil)
          P = precipitation in meters (annual_rainfall_mm / 1000)
          A = catchment area in m^2
        """
        precip_m = annual_rainfall_mm / 1000.0
        runoff_vol_m3 = catchment_area_sq_m * precip_m * runoff_coefficient
        runoff_liters = runoff_vol_m3 * 1000.0

        # Peak discharge rate estimation for 50mm/hr design storm (Q = C * I * A / 360 in m^3/s)
        design_intensity_mm_hr = 50.0
        # Q (m3/s) = (C * I * A_ha) / 360
        area_ha = catchment_area_sq_m / 10000.0
        peak_discharge_m3_s = (runoff_coefficient * design_intensity_mm_hr * area_ha) / 360.0

        return {
            'annual_rainfall_mm': float(annual_rainfall_mm),
            'runoff_coefficient': float(runoff_coefficient),
            'estimated_annual_runoff_m3': round(runoff_vol_m3, 1),
            'estimated_annual_runoff_liters': round(runoff_liters, 0),
            'estimated_annual_runoff_million_liters': round(runoff_liters / 1e6, 2),
            'estimated_peak_discharge_m3_per_sec': round(peak_discharge_m3_s, 2)
        }
