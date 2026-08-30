"""
Pond Siting and Sizing Module
Implements Multi-Criteria Decision Analysis (MCDA) to evaluate terrain for optimal
farm/village pond placement and catchment delineation.
Identifies the primary central village watershed and tributary storage hollows.
"""

from typing import Dict, Any, List, Tuple, Optional
import numpy as np
from app.dem_generator import DEMGrid
from app.hydrology import D8_NEIGHBORS


class PondSitingEngine:
    """
    Evaluates topographic, hydrological, and geotechnical factors to rank optimal pond sites.
    """

    def __init__(
        self,
        weight_catchment: float = 0.40,
        weight_depression: float = 0.30,
        weight_slope: float = 0.20,
        weight_twi: float = 0.10,
    ):
        self.w_catchment = weight_catchment
        self.w_depression = weight_depression
        self.w_slope = weight_slope
        self.w_twi = weight_twi

    def find_optimal_sites(
        self,
        dem: DEMGrid,
        hydro_results: Dict[str, Any],
        num_candidates: int = 5,
        target_catchment_ha: Optional[float] = None,
        boundary_margin_cells: int = 8,
    ) -> List[Dict[str, Any]]:
        """
        Identifies, evaluates, and ranks candidate village pond storage sites across the terrain.
        """
        flow_acc = hydro_results["flow_accumulation"]
        flow_dir = hydro_results["flow_direction"]
        dep_depth = hydro_results["depression_depth"]
        slope = dem.slope_percent
        rows, cols = dem.rows, dem.cols
        cell_area = dem.resolution_m ** 2
        area_ha = (flow_acc * cell_area) / 10000.0

        if target_catchment_ha is None or target_catchment_ha <= 0:
            target_catchment_ha = 40.0

        # 1. Mask out outer perimeter cells to avoid boundary edge effects
        valid_mask = np.zeros((rows, cols), dtype=bool)
        m = max(3, boundary_margin_cells)
        valid_mask[m:rows - m, m:cols - m] = True

        # 2. Compute Topographic Wetness Index (TWI)
        slope_rad = np.deg2rad(np.maximum(0.1, dem.slope_degrees))
        twi = np.log((flow_acc * dem.resolution_m) / np.tan(slope_rad))

        raw_candidates: List[Dict[str, Any]] = []

        # -------------------------------------------------------------------------
        # Strategy A: Natural Depressions & Sinks with Viable Catchments
        # -------------------------------------------------------------------------
        for dep in hydro_results.get("depressions", []):
            br, bc = dep["bottom_grid"]
            if not valid_mask[br, bc]:
                continue

            # Trace downstream to find the spillway pour point
            curr_r, curr_c = br, bc
            for _ in range(35):
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
            raw_candidates.append({
                "type": "natural_depression",
                "pond_grid": (int(br), int(bc)),
                "pour_grid": (int(pour_r), int(pour_c))
            })

        # -------------------------------------------------------------------------
        # Strategy B: Valley Convergence Basins & Stream Confluences
        # -------------------------------------------------------------------------
        stream_thresh = np.percentile(flow_acc, 97.0)
        high_acc_idx = np.where((flow_acc >= stream_thresh) & valid_mask)

        for pr, pc in zip(high_acc_idx[0], high_acc_idx[1]):
            # Pour point is on the stream channel
            # Find the neighboring gentle storage hollow
            best_pond = (int(pr), int(pc))
            best_local_score = -1e9
            pour_elev = dem.elevation[pr, pc]

            for dr in range(-4, 5):
                for dc in range(-4, 5):
                    nr, nc = pr + dr, pc + dc
                    if 0 <= nr < rows and 0 <= nc < cols and valid_mask[nr, nc]:
                        dist_m = np.sqrt(dr**2 + dc**2) * dem.resolution_m
                        if dist_m > 45.0:
                            continue
                        slp = slope[nr, nc]
                        dep_d = dep_depth[nr, nc]
                        elev = dem.elevation[nr, nc]

                        slp_s = max(0.0, 1.0 - (slp / 8.0))
                        dep_s = min(1.0, dep_d / 2.0)
                        elev_diff = abs(elev - pour_elev)
                        elev_s = max(0.0, 1.0 - (elev_diff / 4.0))

                        local_score = (0.50 * slp_s) + (0.35 * dep_s) + (0.15 * elev_s)
                        if local_score > best_local_score:
                            best_local_score = local_score
                            best_pond = (int(nr), int(nc))

            raw_candidates.append({
                "type": "valley_storage",
                "pond_grid": best_pond,
                "pour_grid": (int(pr), int(pc))
            })

        # -------------------------------------------------------------------------
        # 3. Spatial Deduplication & Minimum Spacing between Candidates
        # -------------------------------------------------------------------------
        min_cell_spacing = max(6, int(60.0 / dem.resolution_m))  # ~60 meters separation
        unique_candidates: List[Dict[str, Any]] = []

        for cand in raw_candidates:
            pr, pc = cand["pond_grid"]
            if any(
                abs(pr - u["pond_grid"][0]) < min_cell_spacing and abs(pc - u["pond_grid"][1]) < min_cell_spacing
                for u in unique_candidates
            ):
                continue
            unique_candidates.append(cand)

        # -------------------------------------------------------------------------
        # 4. Multi-Criteria Decision Analysis (MCDA) Scoring
        # -------------------------------------------------------------------------
        scored_sites = []
        for cand in unique_candidates:
            pond_r, pond_c = cand["pond_grid"]
            pour_r, pour_c = cand["pour_grid"]

            # Hydrological catchment metrics from the associated pour point
            catchment_cells = float(flow_acc[pour_r, pour_c])
            catchment_area_m2 = catchment_cells * cell_area
            catchment_area_ha = catchment_area_m2 / 10000.0

            # Local terrain metrics at the physical pond storage location
            dep_d = float(dep_depth[pond_r, pond_c])
            slp = float(slope[pond_r, pond_c])
            tw = float(twi[pond_r, pond_c])
            pond_elev = float(dem.elevation[pond_r, pond_c])
            pour_elev = float(dem.elevation[pour_r, pour_c])

            # Catchment score (peaks when catchment provides substantial village yield)
            score_catchment = min(1.0, catchment_area_ha / target_catchment_ha)

            # Depression storage depth score (0.0 to 1.0)
            score_depression = min(1.0, dep_d / 2.5)

            # Slope stability score (gentle slope < 3% is ideal; penalize steep slopes > 10%)
            score_slope = max(0.0, 1.0 - (slp / 10.0))

            # Topographic wetness index score (0.0 to 1.0)
            score_twi = min(1.0, max(0.0, (tw - 4.0) / 10.0))

            # Composite Suitability Score (0 - 100)
            suitability_score = round(
                100.0 * (
                    self.w_catchment * score_catchment
                    + self.w_depression * score_depression
                    + self.w_slope * score_slope
                    + self.w_twi * score_twi
                ),
                1
            )

            # Coordinates
            pond_lon, pond_lat = dem.grid_to_wgs84(pond_r, pond_c)
            pond_easting, pond_northing = dem.grid_to_utm(pond_r, pond_c)

            pour_lon, pour_lat = dem.grid_to_wgs84(pour_r, pour_c)
            pour_easting, pour_northing = dem.grid_to_utm(pour_r, pour_c)

            # Dynamic Engineering Selection Rationale
            rationale_parts = []
            if dep_d >= 1.0:
                rationale_parts.append(
                    f"Located in a natural topographic bowl ({dep_d:.1f}m depth) reducing excavation"
                )
            else:
                rationale_parts.append(
                    f"Valley storage basin adjacent to drainage convergence"
                )

            rationale_parts.append(
                f"Substantial upstream drainage ({catchment_area_ha:.1f} ha at pour point)"
            )

            if slp < 2.0:
                rationale_parts.append(
                    f"flat bed slope ({slp:.1f}%) for stable embankment"
                )
            else:
                rationale_parts.append(
                    f"gentle bed slope ({slp:.1f}%)"
                )

            rationale = "; ".join(rationale_parts) + "."

            scored_sites.append({
                "grid_index": {"row": int(pond_r), "col": int(pond_c)},
                "candidate_type": cand["type"],
                "coordinates": {
                    "longitude": round(float(pond_lon), 6),
                    "latitude": round(float(pond_lat), 6),
                    "elevation_m": round(float(pond_elev), 2)
                },
                "utm_coordinates": {
                    "easting": round(float(pond_easting), 1),
                    "northing": round(float(pond_northing), 1),
                    "epsg": dem.utm_epsg,
                    "zone": dem.utm_zone
                },
                "associated_pour_point": {
                    "coordinates": {
                        "longitude": round(float(pour_lon), 6),
                        "latitude": round(float(pour_lat), 6),
                        "elevation_m": round(float(pour_elev), 2)
                    },
                    "utm_coordinates": {
                        "easting": round(float(pour_easting), 1),
                        "northing": round(float(pour_northing), 1),
                        "epsg": dem.utm_epsg,
                        "zone": dem.utm_zone
                    },
                    "grid_index": {"row": int(pour_r), "col": int(pour_c)},
                    "flow_accumulation_cells": float(catchment_cells),
                    "drainage_area_ha": round(float(catchment_area_ha), 3)
                },
                "suitability_score": float(suitability_score),
                "criteria_breakdown": {
                    "catchment_score": round(float(score_catchment * 100), 1),
                    "depression_score": round(float(score_depression * 100), 1),
                    "slope_stability_score": round(float(score_slope * 100), 1),
                    "wetness_index_score": round(float(score_twi * 100), 1)
                },
                "local_terrain": {
                    "slope_percent": round(float(slp), 2),
                    "depression_depth_m": round(float(dep_d), 2),
                    "topographic_wetness_index": round(float(tw), 2),
                    "elevation_m": round(float(pond_elev), 2)
                },
                "catchment_area_ha": round(float(catchment_area_ha), 3),
                "catchment_area_sq_m": round(float(catchment_area_m2), 1),
                "selection_rationale": rationale
            })

        # Sort by suitability score descending
        scored_sites.sort(key=lambda s: s["suitability_score"], reverse=True)

        for idx, site in enumerate(scored_sites[:num_candidates], 1):
            site["site_id"] = f"pond_site_{idx}"
            site["rank"] = idx

        return scored_sites[:num_candidates]

    def compute_design_recommendations(
        self,
        catchment_area_sq_m: float,
        annual_runoff_m3: float,
        depression_depth_m: float = 1.0,
        target_pond_depth_m: float = 3.0,
    ) -> Dict[str, Any]:
        """
        Computes civil engineering sizing recommendations for the pond structure.
        """
        target_capacity_m3 = min(50000.0, max(2500.0, annual_runoff_m3 * 0.20))
        depth_m = max(1.5, min(5.0, target_pond_depth_m))

        required_surface_area_sq_m = target_capacity_m3 / (depth_m * 0.75)
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

        household_days = int(storage_liters / (5 * 150))
        irrigation_hectares_supported = round(target_capacity_m3 / 4000.0, 2)

        return {
            "recommended_depth_m": round(depth_m, 2),
            "recommended_surface_area_sq_m": round(required_surface_area_sq_m, 1),
            "recommended_surface_area_hectares": round(
                required_surface_area_sq_m / 10000.0, 3
            ),
            "estimated_dimensions_m": {
                "length_m": round(length_m, 1),
                "width_m": round(width_m, 1),
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
                    min(5.0, annual_runoff_m3 / target_capacity_m3), 1
                ),
            },
            "construction_notes": [
                "Clay puddle lining or 300-500 micron LDPE geomembrane recommended if soil permeability > 10^-5 cm/s.",
                "Inlet silt trap / sediment basin recommended to capture runoff sediment before entering main storage.",
                "Earthen surplus weir / emergency spillway required with 0.6m freeboard above maximum water level.",
            ],
        }
