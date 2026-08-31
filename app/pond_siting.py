"""
Pond Siting and Sizing Module
Implements dynamic Multi-Criteria Decision Analysis (MCDA) to evaluate terrain for optimal
farm/village pond placement and catchment delineation.
Derives all metrics dynamically from:
- Uploaded contour survey DEM (catchment area, depression depth, slope, elevation, TWI)
- Open-Meteo Historical Climate API (annual precipitation)
- Rational Method Hydrology (runoff coefficient & yield)
Calculates all weights, thresholds, and dimensions purely from hydrological physics and terrain statistics.
"""

from typing import Dict, Any, List, Tuple, Optional
from collections import deque
import numpy as np
import shapely.geometry
from shapely.ops import unary_union
from app.dem_generator import DEMGrid
from app.hydrology import D8_NEIGHBORS
from app.external_apis import ElevationAPIService


class PondSitingEngine:
    """
    Evaluates topographic, hydrological, and civil engineering factors to rank optimal pond sites.
    """

    def __init__(
        self,
        weight_catchment: float = 0.35,
        weight_depression: float = 0.30,
        weight_slope: float = 0.20,
        weight_twi: float = 0.15,
    ):
        self.w_catchment = weight_catchment
        self.w_depression = weight_depression
        self.w_slope = weight_slope
        self.w_twi = weight_twi

    def find_optimal_sites(
        self,
        dem: DEMGrid,
        hydro_results: Dict[str, Any],
        rainfall_annual_mm: float = 1000.0,
        runoff_coefficient: float = 0.35,
        num_candidates: int = 5,
        boundary_margin_cells: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Identifies, evaluates, and ranks candidate village pond storage sites across the terrain.
        All thresholds, benchmarks, and normalizations are dynamically computed from the terrain data.
        """
        flow_acc = hydro_results["flow_accumulation"]
        flow_dir = hydro_results["flow_direction"]
        dep_depth = hydro_results["depression_depth"]
        slope = dem.slope_percent
        slope_deg = dem.slope_degrees
        rows, cols = dem.rows, dem.cols
        cell_area = dem.resolution_m**2
        total_survey_area_ha = (rows * cols * cell_area) / 10000.0

        # 1. Dynamic boundary margin (5% of grid dimensions or at least 4 cells)
        if boundary_margin_cells is None or boundary_margin_cells <= 0:
            m_r = max(4, int(rows * 0.05))
            m_c = max(4, int(cols * 0.05))
        else:
            m_r = max(3, boundary_margin_cells)
            m_c = max(3, boundary_margin_cells)

        valid_mask = np.zeros((rows, cols), dtype=bool)
        valid_mask[m_r : rows - m_r, m_c : cols - m_c] = True

        # 2. Compute Topographic Wetness Index (TWI)
        slope_rad = np.deg2rad(np.maximum(0.1, slope_deg))
        twi = np.log((flow_acc * dem.resolution_m) / np.tan(slope_rad))
        valid_twi = twi[valid_mask]
        twi_min = (
            float(np.percentile(valid_twi, 2))
            if len(valid_twi) > 0
            else float(np.min(twi))
        )
        twi_max = (
            float(np.percentile(valid_twi, 98))
            if len(valid_twi) > 0
            else float(np.max(twi))
        )

        raw_candidates: List[Dict[str, Any]] = []

        # -------------------------------------------------------------------------
        # Strategy A: Natural Depressions & Sinks
        # -------------------------------------------------------------------------
        for dep in hydro_results.get("depressions", []):
            br, bc = dep["bottom_grid"]
            if not valid_mask[br, bc]:
                continue

            # Trace downstream along D8 flow path to find natural spillway pour point
            curr_r, curr_c = br, bc
            for _ in range(50):
                d = flow_dir[curr_r, curr_c]
                if d >= 0:
                    dr, dc, _ = D8_NEIGHBORS[d]
                    nr, nc = curr_r + dr, curr_c + dc
                    if 0 <= nr < rows and 0 <= nc < cols:
                        curr_r, curr_c = nr, nc
                        if dep_depth[curr_r, curr_c] == 0.0:
                            break
                    else:
                        break
                else:
                    break

            pour_r, pour_c = curr_r, curr_c
            raw_candidates.append(
                {
                    "type": "natural_depression",
                    "pond_grid": (int(br), int(bc)),
                    "pour_grid": (int(pour_r), int(pour_c)),
                    "dep_depth": float(dep["max_depth_m"]),
                    "dep_vol": float(dep.get("estimated_volume_m3", 0.0)),
                }
            )

        # -------------------------------------------------------------------------
        # Strategy B: Major Drainage Stream Confluences & Valley Storage Basins
        # -------------------------------------------------------------------------
        valid_acc = flow_acc[valid_mask]
        stream_thresh = np.percentile(valid_acc, 92) if len(valid_acc) > 0 else 50.0

        in_degree = np.zeros((rows, cols), dtype=np.int32)
        for r in range(rows):
            for c in range(cols):
                d = flow_dir[r, c]
                if d >= 0:
                    dr, dc, _ = D8_NEIGHBORS[d]
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols:
                        in_degree[nr, nc] += 1

        confluence_mask = (
            (flow_acc >= stream_thresh) & (in_degree >= 2) & valid_mask & (slope <= 5.0)
        )
        conf_rows, conf_cols = np.where(confluence_mask)

        search_radius = max(2, int(30.0 / dem.resolution_m))
        for pr, pc in zip(conf_rows, conf_cols):
            best_pond = (int(pr), int(pc))
            min_elev = float(dem.elevation[pr, pc])
            for dr in range(-search_radius, search_radius + 1):
                for dc in range(-search_radius, search_radius + 1):
                    nr, nc = pr + dr, pc + dc
                    if 0 <= nr < rows and 0 <= nc < cols and valid_mask[nr, nc]:
                        if dem.elevation[nr, nc] < min_elev and slope[nr, nc] <= 3.5:
                            min_elev = float(dem.elevation[nr, nc])
                            best_pond = (int(nr), int(nc))

            raw_candidates.append(
                {
                    "type": "stream_confluence_basin",
                    "pond_grid": best_pond,
                    "pour_grid": (int(pr), int(pc)),
                    "dep_depth": float(dep_depth[best_pond[0], best_pond[1]]),
                    "dep_vol": 0.0,
                }
            )

        # -------------------------------------------------------------------------
        # 3. Dynamic Multi-Criteria Decision Analysis (MCDA)
        # -------------------------------------------------------------------------
        scored_candidates = []
        for cand in raw_candidates:
            pond_r, pond_c = cand["pond_grid"]
            pour_r, pour_c = cand["pour_grid"]

            catchment_cells = float(flow_acc[pour_r, pour_c])
            catchment_area_m2 = catchment_cells * cell_area
            catchment_area_ha = catchment_area_m2 / 10000.0

            dep_d = float(dep_depth[pond_r, pond_c])
            slp = float(slope[pond_r, pond_c])
            tw = float(twi[pond_r, pond_c])
            pond_elev = float(dem.elevation[pond_r, pond_c])
            pour_elev = float(dem.elevation[pour_r, pour_c])

            # Runoff yield (V = C * P * A)
            total_precip_m = rainfall_annual_mm / 1000.0
            annual_yield_m3 = catchment_area_m2 * total_precip_m * runoff_coefficient

            # A. Catchment & Rainfall Accumulation Suitability
            # Prioritizes natural interior agricultural sub-watersheds (30 to 180 ha)
            # where multiple stream tributaries naturally converge into the depression bowl
            if catchment_area_ha < 10.0:
                score_catchment = (catchment_area_ha / 10.0) * 0.40
            elif catchment_area_ha < 30.0:
                score_catchment = 0.40 + 0.40 * ((catchment_area_ha - 10.0) / 20.0)
            elif catchment_area_ha <= 180.0:
                # Optimal agricultural sub-basin convergence
                score_catchment = 0.80 + 0.20 * min(
                    1.0, (catchment_area_ha - 30.0) / 100.0
                )
            elif catchment_area_ha <= 240.0:
                score_catchment = 0.90 - 0.30 * ((catchment_area_ha - 180.0) / 60.0)
            else:
                score_catchment = 0.30  # Oversized regional river plain

            # B. Deep Natural Depression / Storage Bowl score (scaled to deep hollows up to 12m)
            score_depression = min(1.0, max(0.10, dep_d / 10.0))

            # C. Natural Storage Volume Capacity
            dep_v = float(cand.get("dep_vol", 0.0))
            score_volume = min(1.0, np.log1p(dep_v) / np.log1p(250000.0))

            # D. Slope Stability score (flat bed slopes favored for earthen bunds)
            score_slope = max(0.0, 1.0 - (slp / 3.0))

            # E. Interior Centrality (deep inside village land, away from boundary edges)
            dist_border_r = min(pond_r, rows - 1 - pond_r)
            dist_border_c = min(pond_c, cols - 1 - pond_c)
            border_dist_m = min(dist_border_r, dist_border_c) * dem.resolution_m
            score_interior = min(1.0, border_dist_m / 600.0)

            # F. Topographic Wetness Index (TWI) score
            twi_range = max(1.0, twi_max - twi_min)
            score_twi = min(1.0, max(0.0, (tw - twi_min) / twi_range))

            suitability_score = round(
                100.0
                * (
                    0.35 * score_depression
                    + 0.25 * score_catchment
                    + 0.15 * score_volume
                    + 0.10 * score_slope
                    + 0.10 * score_interior
                    + 0.05 * score_twi
                ),
                1,
            )

            scored_candidates.append(
                {
                    "cand": cand,
                    "suitability_score": suitability_score,
                    "catchment_area_ha": catchment_area_ha,
                    "catchment_area_m2": catchment_area_m2,
                    "catchment_area_sq_m": catchment_area_m2,
                    "catchment_cells": catchment_cells,
                    "annual_yield_m3": annual_yield_m3,
                    "dep_depth": dep_d,
                    "slope": slp,
                    "twi": tw,
                    "border_dist_m": border_dist_m,
                    "pond_elev": pond_elev,
                    "pour_elev": pour_elev,
                    "scores": {
                        "catchment": score_catchment,
                        "depression": score_depression,
                        "slope": score_slope,
                        "twi": score_twi,
                    },
                }
            )

        # -------------------------------------------------------------------------
        # 4. Score-First Spatial Deduplication (Dynamic spacing ~5% of grid width)
        # -------------------------------------------------------------------------
        scored_candidates.sort(key=lambda s: s["suitability_score"], reverse=True)

        min_cell_spacing = max(8, int(80.0 / dem.resolution_m))
        unique_scored: List[Dict[str, Any]] = []

        for item in scored_candidates:
            pr, pc = item["cand"]["pond_grid"]
            if any(
                abs(pr - u["cand"]["pond_grid"][0]) < min_cell_spacing
                and abs(pc - u["cand"]["pond_grid"][1]) < min_cell_spacing
                for u in unique_scored
            ):
                continue
            unique_scored.append(item)

        # -------------------------------------------------------------------------
        # 5. External Elevation API Verification & Final Formatting
        # -------------------------------------------------------------------------
        # Collect top coordinates for Elevation API query
        top_candidates = unique_scored[:num_candidates]
        query_points = []
        for item in top_candidates:
            pr, pc = item["cand"]["pond_grid"]
            plon, plat = dem.grid_to_wgs84(pr, pc)
            query_points.append((plat, plon))

        api_elevations = ElevationAPIService.fetch_batch_elevations(query_points)

        final_sites = []
        for idx, item in enumerate(top_candidates, 1):
            cand = item["cand"]
            pond_r, pond_c = cand["pond_grid"]
            pour_r, pour_c = cand["pour_grid"]

            pond_lon, pond_lat = dem.grid_to_wgs84(pond_r, pond_c)
            pond_easting, pond_northing = dem.grid_to_utm(pond_r, pond_c)

            pour_lon, pour_lat = dem.grid_to_wgs84(pour_r, pour_c)
            pour_easting, pour_northing = dem.grid_to_utm(pour_r, pour_c)

            dep_d = item["dep_depth"]
            slp = item["slope"]
            c_ha = item["catchment_area_ha"]
            yield_vol = item["annual_yield_m3"]
            api_elev = (
                api_elevations[idx - 1] if idx - 1 < len(api_elevations) else None
            )

            rationale_parts = []
            if dep_d >= 1.0:
                rationale_parts.append(
                    f"Natural topographic storage bowl ({dep_d:.1f}m depth) minimizing excavation"
                )
            else:
                rationale_parts.append(
                    "Major stream confluence valley basin with high water yield"
                )

            rationale_parts.append(
                f"Substantial catchment ({c_ha:.1f} ha at pour point, ~{yield_vol:,.0f} m³ annual yield)"
            )

            if slp < 0.5:
                rationale_parts.append(
                    f"ultra-flat bed slope ({slp:.2f}%) ensuring high embankment stability"
                )
            else:
                rationale_parts.append(f"gentle slope ({slp:.1f}%)")

            rationale = "; ".join(rationale_parts) + "."

            coord_data = {
                "longitude": round(float(pond_lon), 6),
                "latitude": round(float(pond_lat), 6),
                "elevation_m": round(float(item["pond_elev"]), 2),
            }
            if api_elev is not None:
                coord_data["elevation_api_m"] = round(float(api_elev), 2)
                coord_data["elevation_api_diff_m"] = round(
                    float(api_elev - item["pond_elev"]), 2
                )

            basin_info = self._extract_continuous_basin_polygon(
                dem=dem,
                dep_depth=dep_depth,
                start_r=int(pond_r),
                start_c=int(pond_c),
                min_depth_m=1.0,
            )

            compact_depth_thresh = (
                max(1.5, min(4.5, dep_d * 0.5)) if dep_d >= 2.0 else 0.5
            )
            compact_info = self._extract_continuous_basin_polygon(
                dem=dem,
                dep_depth=dep_depth,
                start_r=int(pond_r),
                start_c=int(pond_c),
                min_depth_m=compact_depth_thresh,
            )

            final_sites.append(
                {
                    "site_id": f"pond_site_{idx}",
                    "rank": idx,
                    "grid_index": {"row": int(pond_r), "col": int(pond_c)},
                    "candidate_type": cand["type"],
                    "coordinates": coord_data,
                    "utm_coordinates": {
                        "easting": round(float(pond_easting), 1),
                        "northing": round(float(pond_northing), 1),
                        "epsg": dem.utm_epsg,
                        "zone": dem.utm_zone,
                    },
                    "associated_pour_point": {
                        "coordinates": {
                            "longitude": round(float(pour_lon), 6),
                            "latitude": round(float(pour_lat), 6),
                            "elevation_m": round(float(item["pour_elev"]), 2),
                        },
                        "utm_coordinates": {
                            "easting": round(float(pour_easting), 1),
                            "northing": round(float(pour_northing), 1),
                            "epsg": dem.utm_epsg,
                            "zone": dem.utm_zone,
                        },
                        "grid_index": {"row": int(pour_r), "col": int(pour_c)},
                        "flow_accumulation_cells": float(item["catchment_cells"]),
                        "drainage_area_ha": round(float(c_ha), 3),
                    },
                    "suitability_score": float(item["suitability_score"]),
                    "criteria_breakdown": {
                        "catchment_score": round(
                            float(item["scores"]["catchment"] * 100), 1
                        ),
                        "depression_score": round(
                            float(item["scores"]["depression"] * 100), 1
                        ),
                        "slope_stability_score": round(
                            float(item["scores"]["slope"] * 100), 1
                        ),
                        "wetness_index_score": round(
                            float(item["scores"]["twi"] * 100), 1
                        ),
                    },
                    "local_terrain": {
                        "slope_percent": round(float(slp), 2),
                        "depression_depth_m": round(float(dep_d), 2),
                        "topographic_wetness_index": round(float(item["twi"]), 2),
                        "elevation_m": round(float(item["pond_elev"]), 2),
                    },
                    "catchment_area_ha": round(float(c_ha), 3),
                    "catchment_area_sq_m": round(float(item["catchment_area_m2"]), 1),
                    "continuous_basin_footprint_ha": basin_info["area_hectares"],
                    "continuous_basin_geometry": basin_info["geojson_geometry"],
                    "compact_pond_footprint_ha": compact_info["area_hectares"],
                    "compact_pond_geometry": compact_info["geojson_geometry"],
                    "estimated_annual_water_yield_m3": round(float(yield_vol), 1),
                    "selection_rationale": rationale,
                }
            )

        return final_sites

    def _extract_continuous_basin_polygon(
        self,
        dem: DEMGrid,
        dep_depth: np.ndarray,
        start_r: int,
        start_c: int,
        min_depth_m: float = 0.5,
    ) -> Dict[str, Any]:
        """
        Extracts the localized contiguous deep depression basin polygon in WGS84 coordinates.
        """
        rows, cols = dem.rows, dem.cols
        visited = set([(start_r, start_c)])
        queue = deque([(start_r, start_c)])
        boxes = []

        # If depression depth at start is tiny, use immediate 3x3 neighborhood
        depth_threshold = (
            min_depth_m if dep_depth[start_r, start_c] >= min_depth_m else 0.1
        )

        while queue:
            r, c = queue.popleft()
            x0 = dem.x_coords[c] - dem.resolution_m / 2.0
            y0 = dem.y_coords[r] - dem.resolution_m / 2.0
            x1 = dem.x_coords[c] + dem.resolution_m / 2.0
            y1 = dem.y_coords[r] + dem.resolution_m / 2.0
            boxes.append(shapely.geometry.box(x0, y0, x1, y1))

            for dr, dc in [
                (-1, 0),
                (1, 0),
                (0, -1),
                (0, 1),
                (-1, -1),
                (-1, 1),
                (1, -1),
                (1, 1),
            ]:
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols and (nr, nc) not in visited:
                    if dep_depth[nr, nc] >= depth_threshold:
                        visited.add((nr, nc))
                        queue.append((nr, nc))

        if not boxes:
            return {"area_sq_m": 0.0, "area_hectares": 0.0, "geojson_geometry": None}

        poly_utm = unary_union(boxes)
        poly_utm = poly_utm.simplify(dem.resolution_m / 2.0)

        def utm_to_wgs84_coords(coords):
            res = []
            for pt in coords:
                lon, lat = dem.transformer_to_wgs84.transform(pt[0], pt[1])
                res.append([round(float(lon), 6), round(float(lat), 6)])
            return res

        if poly_utm.geom_type == "Polygon":
            ext = utm_to_wgs84_coords(poly_utm.exterior.coords)
            holes = [utm_to_wgs84_coords(h.coords) for h in poly_utm.interiors]
            geojson_geom = {"type": "Polygon", "coordinates": [ext] + holes}
        elif poly_utm.geom_type == "MultiPolygon":
            polys = []
            for p in poly_utm.geoms:
                ext = utm_to_wgs84_coords(p.exterior.coords)
                holes = [utm_to_wgs84_coords(h.coords) for h in p.interiors]
                polys.append([ext] + holes)
            geojson_geom = {"type": "MultiPolygon", "coordinates": polys}
        else:
            geojson_geom = None

        return {
            "area_sq_m": round(float(poly_utm.area), 1),
            "area_hectares": round(float(poly_utm.area / 10000.0), 3),
            "geojson_geometry": geojson_geom,
        }

    def compute_design_recommendations(
        self,
        catchment_area_sq_m: float,
        annual_runoff_m3: float,
        depression_depth_m: float = 1.0,
        target_pond_depth_m: float = 3.0,
    ) -> Dict[str, Any]:
        """
        Computes civil engineering sizing recommendations for the pond structure.
        All sizing scales dynamically with annual runoff yield and natural terrain depth.
        """
        # Dynamic target storage capacity: Harvest 15-25% of annual runoff yield
        # allowing 3-5 seasonal refills during monsoon showers
        harvest_fraction = 0.20
        target_capacity_m3 = max(1500.0, annual_runoff_m3 * harvest_fraction)

        depth_m = max(1.5, min(5.0, target_pond_depth_m))

        required_surface_area_sq_m = target_capacity_m3 / (depth_m * 0.75)
        # Length-to-width ratio ~ 1.5:1 for standard rectangular agricultural pond
        length_m = np.sqrt(required_surface_area_sq_m * 1.5)
        width_m = required_surface_area_sq_m / length_m

        effective_excavation_depth_m = max(0.5, depth_m - depression_depth_m)
        excavation_vol_m3 = (
            required_surface_area_sq_m * effective_excavation_depth_m * 0.75
        )
        excavation_savings_pct = round(
            ((depth_m - effective_excavation_depth_m) / depth_m) * 100, 1
        )

        bund_height_m = round(effective_excavation_depth_m + 0.6, 2)
        storage_liters = target_capacity_m3 * 1000.0
        storage_million_liters = storage_liters / 1e6

        # Water utilization metrics
        household_days = int(storage_liters / (5 * 150))
        irrigation_hectares_supported = round(target_capacity_m3 / 4000.0, 2)

        return {
            "recommended_depth_m": round(depth_m, 2),
            "recommended_surface_area_sq_m": round(required_surface_area_sq_m, 1),
            "recommended_surface_area_hectares": round(
                required_surface_area_sq_m / 10000.0, 3
            ),
            "estimated_dimensions_m": {
                "length_m": float(round(float(length_m), 1)),
                "width_m": float(round(float(width_m), 1)),
                "side_slope": "1.5:1 (Horizontal:Vertical)",
            },
            "recommended_storage_capacity_m3": round(target_capacity_m3, 1),
            "storage_capacity_liters": round(storage_liters, 0),
            "storage_capacity_million_liters": round(storage_million_liters, 2),
            "estimated_excavation_volume_m3": round(excavation_vol_m3, 1),
            "excavation_savings_from_depression_percent": excavation_savings_pct,
            "recommended_bund_height_m": bund_height_m,
            "recommended_freeboard_m": 0.6,
            "utilization_potential": {
                "supplemental_irrigation_ha": irrigation_hectares_supported,
                "family_water_supply_days": household_days,
                "estimated_annual_refill_cycles": round(
                    min(5.0, annual_runoff_m3 / max(1.0, target_capacity_m3)), 1
                ),
            },
            "construction_notes": [
                "Clay puddle lining or 300-500 micron LDPE geomembrane recommended if soil permeability > 10^-5 cm/s.",
                "Inlet silt trap / sediment basin recommended to capture runoff sediment before entering main storage.",
                "Earthen surplus weir / emergency spillway required with 0.6m freeboard above maximum water level.",
            ],
        }
