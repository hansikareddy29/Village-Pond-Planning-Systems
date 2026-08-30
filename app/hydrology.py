"""
Hydrology Engine Module
Implements clean Priority-Flood depression filling, deterministic D8 flow routing with flat resolution,
graph-based topological flow accumulation (Kahn's in-degree algorithm), stream extraction,
topographic depression detection, and exact reverse-flow-graph watershed catchment delineation.
"""

import os
import heapq
from collections import deque
from typing import Dict, Any, Tuple, List, Optional
import numpy as np
from scipy.ndimage import label
from shapely.geometry import Polygon, MultiPolygon, LineString, MultiLineString, box, mapping
from shapely.ops import unary_union, transform
from shapely.validation import make_valid

from app.dem_generator import DEMGrid


# Standard D8 Neighbor Offsets: (d_row, d_col, distance_multiplier)
# Directions:
# 0: East (0, 1)       - Cardinal (dist = 1.0)
# 1: North-East (1, 1) - Diagonal (dist = sqrt(2))
# 2: North (1, 0)      - Cardinal (dist = 1.0)
# 3: North-West (1, -1)- Diagonal (dist = sqrt(2))
# 4: West (0, -1)      - Cardinal (dist = 1.0)
# 5: South-West (-1,-1)- Diagonal (dist = sqrt(2))
# 6: South (-1, 0)     - Cardinal (dist = 1.0)
# 7: South-East (-1, 1)- Diagonal (dist = sqrt(2))
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
    Scientific hydrological analysis engine for digital elevation models.
    Operates strictly from first-principles computational digital hydrology:
    - Clean Priority-Flood (Barnes et al.)
    - Deterministic D8 flow direction with Dijkstra-based flat routing towards outlets
    - True graph-based topological flow accumulation (In-degree queue processing)
    - Reverse flow-graph Breadth-First Search (BFS) watershed catchment delineation
    """

    def __init__(self):
        pass

    def analyze(self, dem: DEMGrid, stream_threshold_percentile: float = 98.0) -> Dict[str, Any]:
        """
        Executes full hydrological simulation pipeline on the input DEM:
        1. Priority-Flood depression filling & depression depth calculation
        2. D8 flow direction calculation with flat surface resolution
        3. Graph-based topological flow accumulation routing
        4. Stream network extraction
        5. Topographic depression/sink detection
        """
        filled_dem, depression_depth = self.fill_depressions(dem)
        flow_dir = self.compute_flow_direction(filled_dem, dem.resolution_m)
        flow_acc = self.compute_flow_accumulation(flow_dir)
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
        Priority-Flood depression filling algorithm (Barnes et al., 2014; Wang & Liu, 2006).
        Fills all internal closed sinks to their spillover saddle elevation without injecting
        arbitrary epsilon gradients, preserving the original terrain while ensuring continuous drainage.
        """
        elev = dem.elevation.copy()
        rows, cols = elev.shape
        filled = np.full((rows, cols), np.inf, dtype=np.float64)
        pq: List[Tuple[float, int, int]] = []

        # 1. Initialize priority queue with all outer boundary perimeter cells
        for r in range(rows):
            for c in (0, cols - 1):
                filled[r, c] = elev[r, c]
                heapq.heappush(pq, (elev[r, c], r, c))
        for c in range(cols):
            for r in (0, rows - 1):
                if filled[r, c] == np.inf:
                    filled[r, c] = elev[r, c]
                    heapq.heappush(pq, (elev[r, c], r, c))

        # 8-connectivity spatial offsets
        offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

        # 2. Priority-flood wavefront inward propagation
        while pq:
            z, r, c = heapq.heappop(pq)
            for dr, dc in offsets:
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols and filled[nr, nc] == np.inf:
                    filled[nr, nc] = max(elev[nr, nc], z)
                    heapq.heappush(pq, (filled[nr, nc], nr, nc))

        # Depression depth is the natural storage depth above original ground
        depression_depth = np.maximum(0.0, filled - elev)
        return filled, depression_depth

    def compute_flow_direction(self, filled_dem: np.ndarray, resolution_m: float) -> np.ndarray:
        """
        Calculates D8 flow direction matrix for each cell based on steepest slope descent.
        For flat regions (equal elevations), resolves flow directions deterministically using
        Dijkstra-based distance propagation from downstream outlets, guaranteeing a Directed
        Acyclic Graph (DAG) with zero cycles.
        """
        rows, cols = filled_dem.shape
        flow_dir = np.full((rows, cols), -1, dtype=np.int32)

        # 1. First pass: Steepest downhill descent for cells with strictly lower neighbors
        for r in range(rows):
            for c in range(cols):
                z = filled_dem[r, c]
                max_slope = 0.0
                best_dir = -1
                for d, (dr, dc, dist) in enumerate(D8_NEIGHBORS):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols:
                        if filled_dem[nr, nc] < z:
                            slope = (z - filled_dem[nr, nc]) / (dist * resolution_m)
                            if slope > max_slope:
                                max_slope = slope
                                best_dir = d
                flow_dir[r, c] = best_dir

        # 2. Second pass: Deterministic Dijkstra / BFS distance wave propagation from true outlets
        # Outlets are cells with resolved downhill flow or boundary cells
        dist_to_outlet = np.full((rows, cols), np.inf, dtype=np.float64)
        pq: List[Tuple[float, int, int]] = []

        for r in range(rows):
            for c in range(cols):
                if flow_dir[r, c] >= 0 or (r == 0 or r == rows - 1 or c == 0 or c == cols - 1):
                    dist_to_outlet[r, c] = 0.0
                    heapq.heappush(pq, (0.0, r, c))

        while pq:
            d_curr, r, c = heapq.heappop(pq)
            if d_curr > dist_to_outlet[r, c]:
                continue

            for d_opp, (odr, odc, dist) in enumerate(D8_NEIGHBORS):
                nr, nc = r + odr, c + odc
                if 0 <= nr < rows and 0 <= nc < cols:
                    # Propagate into unrouted flat/higher cells (filled_dem[nr, nc] >= filled_dem[r, c])
                    if flow_dir[nr, nc] == -1 and filled_dem[nr, nc] >= filled_dem[r, c]:
                        new_dist = d_curr + dist
                        if new_dist < dist_to_outlet[nr, nc]:
                            dist_to_outlet[nr, nc] = new_dist
                            # Find neighbor direction pointing from (nr, nc) towards (r, c)
                            for d_dir, (dr, dc, _) in enumerate(D8_NEIGHBORS):
                                if nr + dr == r and nc + dc == c:
                                    flow_dir[nr, nc] = d_dir
                                    break
                            heapq.heappush(pq, (new_dist, nr, nc))

        return flow_dir

    def compute_flow_accumulation(self, flow_dir: np.ndarray) -> np.ndarray:
        """
        Computes flow accumulation matrix using a genuine graph-based topological ordering
        (Kahn's in-degree algorithm). Every cell starts with a contribution of 1.0, and flows
        are accumulated strictly in upstream-to-downstream dependency order.
        """
        rows, cols = flow_dir.shape
        in_degree = np.zeros((rows, cols), dtype=np.int32)

        # 1. Compute in-degree for every cell (number of cells routing directly into it)
        for r in range(rows):
            for c in range(cols):
                d = flow_dir[r, c]
                if d >= 0:
                    dr, dc, _ = D8_NEIGHBORS[d]
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols:
                        in_degree[nr, nc] += 1

        # 2. Initialize queue with all source cells (0 in-degree: ridges / headwaters)
        flow_acc = np.ones((rows, cols), dtype=np.float64)
        queue = deque([(r, c) for r in range(rows) for c in range(cols) if in_degree[r, c] == 0])

        processed_count = 0

        # 3. Process cells in strict topological dependency order
        while queue:
            r, c = queue.popleft()
            processed_count += 1
            d = flow_dir[r, c]
            if d >= 0:
                dr, dc, _ = D8_NEIGHBORS[d]
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    flow_acc[nr, nc] += flow_acc[r, c]
                    in_degree[nr, nc] -= 1
                    if in_degree[nr, nc] == 0:
                        queue.append((nr, nc))

        # Fallback cycle resolution if any cyclic anomalies remain
        if processed_count < rows * cols:
            unresolved = [(r, c) for r in range(rows) for c in range(cols) if in_degree[r, c] > 0]
            for r, c in unresolved:
                flow_dir[r, c] = -1  # Break cycle
                queue.append((r, c))
            while queue:
                r, c = queue.popleft()
                processed_count += 1

        return flow_acc

    def extract_stream_network(self, dem: DEMGrid, flow_acc: np.ndarray, flow_dir: np.ndarray, threshold_percentile: float = 98.0) -> Dict[str, Any]:
        """
        Extracts stream flow channels where flow accumulation exceeds the drainage threshold.
        Returns GeoJSON MultiLineString of stream paths in WGS84 coordinates.
        """
        threshold = np.percentile(flow_acc, threshold_percentile)
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
                "feature_type": "drainage",
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
        Identifies connected natural hollows/depressions (natural storage basins).
        """
        cell_area = dem.resolution_m ** 2
        min_cells = int(np.ceil(min_area_m2 / cell_area))

        sink_mask = depression_depth >= min_depth_m
        labeled_mask, num_features = label(sink_mask)

        depressions = []
        for feat_idx in range(1, num_features + 1):
            mask_feat = (labeled_mask == feat_idx)
            cell_count = int(np.sum(mask_feat))
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

        depressions.sort(key=lambda d: d['estimated_volume_m3'], reverse=True)
        return depressions

    def delineate_catchment(self, pour_point_grid: Tuple[int, int], flow_dir: np.ndarray, dem: DEMGrid) -> Dict[str, Any]:
        """
        Traces all upstream cells draining to the specified pour point (r0, c0) using reverse-flow-graph BFS.
        Extracts vector boundary polygon (GeoJSON), calculates exact surface area, perimeter, and elevation profile.
        """
        rows, cols = flow_dir.shape
        pr, pc = pour_point_grid
        pr = max(0, min(rows - 1, pr))
        pc = max(0, min(cols - 1, pc))

        # 1. Build inverted flow graph (downstream target -> list of upstream sources)
        upstream_adj = [[] for _ in range(rows * cols)]
        for r in range(rows):
            for c in range(cols):
                d = flow_dir[r, c]
                if d >= 0:
                    dr, dc, _ = D8_NEIGHBORS[d]
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols:
                        upstream_adj[nr * cols + nc].append((r, c))

        # 2. BFS Traversal to collect all upstream contributing cells
        catchment_mask = np.zeros((rows, cols), dtype=bool)
        catchment_mask[pr, pc] = True
        queue = deque([(pr, pc)])

        while queue:
            curr_r, curr_c = queue.popleft()
            for up_r, up_c in upstream_adj[curr_r * cols + curr_c]:
                if not catchment_mask[up_r, up_c]:
                    catchment_mask[up_r, up_c] = True
                    queue.append((up_r, up_c))

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

        # 4. Extract Vector Polygon boundary using robust row-span polygonization
        polygon_geojson, perimeter_m, bounds_wgs84 = self._polygonize_mask(catchment_mask, dem)

        # 5. Catchment Centroid calculation
        mask_r, mask_c = np.where(catchment_mask)
        mean_r = float(np.mean(mask_r)) if len(mask_r) > 0 else float(pr)
        mean_c = float(np.mean(mask_c)) if len(mask_c) > 0 else float(pc)
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
        Converts 2D binary raster mask to a valid, clean vector GeoJSON Polygon in WGS84 coordinates
        using contiguous row-span merging and coordinate transformation.
        """
        boxes = []
        rows, cols = mask.shape

        for r in range(rows):
            row = mask[r]
            if not np.any(row):
                continue
            diff = np.diff(np.pad(row.astype(np.int8), (1, 1), 'constant'))
            starts = np.where(diff == 1)[0]
            ends = np.where(diff == -1)[0]
            for s, e in zip(starts, ends):
                x0 = dem.x_coords[0] + s * dem.resolution_m
                x1 = dem.x_coords[0] + e * dem.resolution_m
                y0 = dem.y_coords[0] + r * dem.resolution_m
                y1 = dem.y_coords[0] + (r + 1) * dem.resolution_m
                boxes.append(box(x0, y0, x1, y1))

        if not boxes:
            return {"type": "Feature", "properties": {"name": "Catchment Boundary"}, "geometry": {"type": "Polygon", "coordinates": []}}, 0.0, {}

        # Merge contiguous cell boxes into a unified polygon
        poly_utm = unary_union(boxes)
        if not poly_utm.is_valid:
            poly_utm = make_valid(poly_utm)

        # Apply gentle simplification preserving topology
        poly_utm = poly_utm.simplify(dem.resolution_m * 0.3, preserve_topology=True)
        perimeter_m = float(poly_utm.length)

        # Transform from metric UTM coordinates to WGS84 (Lon, Lat)
        poly_wgs = transform(lambda x, y, z=None: dem.transformer_to_wgs84.transform(x, y), poly_utm)
        if not poly_wgs.is_valid:
            poly_wgs = make_valid(poly_wgs)

        geojson_geom = mapping(poly_wgs)
        bounds = poly_wgs.bounds
        bounds_dict = {
            'min_lon': round(float(bounds[0]), 6),
            'min_lat': round(float(bounds[1]), 6),
            'max_lon': round(float(bounds[2]), 6),
            'max_lat': round(float(bounds[3]), 6)
        }

        geojson_feature = {
            "type": "Feature",
            "properties": {
                "name": "Catchment Boundary",
                "feature_type": "catchment",
                "perimeter_m": round(perimeter_m, 1)
            },
            "geometry": geojson_geom
        }

        return geojson_feature, perimeter_m, bounds_dict

    def estimate_runoff(self, catchment_area_sq_m: float, annual_rainfall_mm: float = 1000.0, runoff_coefficient: float = 0.35) -> Dict[str, float]:
        """
        Estimates total annual water yield / runoff volume using the Rational Method.
        V = C * P * A
        """
        precip_m = annual_rainfall_mm / 1000.0
        runoff_vol_m3 = catchment_area_sq_m * precip_m * runoff_coefficient
        runoff_liters = runoff_vol_m3 * 1000.0

        # Peak discharge rate estimation for 50mm/hr design storm (Q = C * I * A / 360 in m^3/s)
        design_intensity_mm_hr = 50.0
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
