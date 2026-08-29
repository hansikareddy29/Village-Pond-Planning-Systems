"""
Pond Siting and Sizing Module
Implements Multi-Criteria Decision Analysis (MCDA) to evaluate terrain for optimal
farm/village pond placement, and computes engineering sizing and water storage estimates.
"""

from typing import Dict, Any, List, Tuple, Optional
import numpy as np
from app.dem_generator import DEMGrid


class PondSitingEngine:
    """
    Evaluates topographic, hydrological, and geotechnical factors to rank optimal pond sites
    and provide engineering design recommendations.
    """

    def __init__(
        self,
        weight_catchment: float = 0.40,
        weight_depression: float = 0.25,
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
        num_candidates: int = 5,
        target_catchment_ha: float = 10.0,
        boundary_margin_cells: int = 8,
    ) -> List[Dict[str, Any]]:
        """
        Scans DEM and hydrology results to identify and rank candidate pond sites.
        """
        flow_acc = hydro_results["flow_accumulation"]
        dep_depth = hydro_results["depression_depth"]
        slope = dem.slope_percent
        rows, cols = dem.rows, dem.cols
        cell_area = dem.resolution_m**2

        # 1. Mask out outer perimeter cells to avoid boundary truncation
        valid_mask = np.zeros((rows, cols), dtype=bool)
        m = max(2, boundary_margin_cells)
        valid_mask[m : rows - m, m : cols - m] = True

        # 2. Compute Topographic Wetness Index (TWI)
        slope_rad = np.deg2rad(dem.slope_degrees)
        twi = np.log(
            (flow_acc * dem.resolution_m) / (np.tan(np.maximum(slope_rad, 0.01)))
        )

        # 3. Gather candidate locations from:
        #    a) Top natural depressions (sinks)
        #    b) High accumulation confluence nodes (top 1% drainage cells)
        candidate_grids: List[Tuple[int, int]] = []

        # Depressions
        for dep in hydro_results.get("depressions", [])[:30]:
            candidate_grids.append(dep["bottom_grid"])

        # High accumulation points
        high_acc_threshold = np.percentile(flow_acc, 99.0)
        high_acc_idx = np.where((flow_acc >= high_acc_threshold) & valid_mask)
        for r, c in zip(high_acc_idx[0], high_acc_idx[1]):
            candidate_grids.append((int(r), int(c)))

        # 4. Spatially cluster / deduplicate candidates (minimum spacing between candidates)
        min_cell_spacing = max(4, int(50.0 / dem.resolution_m))  # ~50 meters separation
        unique_candidates: List[Tuple[int, int]] = []

        for r, c in candidate_grids:
            if not valid_mask[r, c]:
                continue
            if any(
                abs(r - ur) < min_cell_spacing and abs(c - uc) < min_cell_spacing
                for ur, uc in unique_candidates
            ):
                continue
            unique_candidates.append((r, c))

        # 5. Multi-Criteria Scoring for each candidate
        scored_sites = []
        for r, c in unique_candidates:
            catchment_area_m2 = float(flow_acc[r, c] * cell_area)
            catchment_area_ha = catchment_area_m2 / 10000.0
            dep_d = float(dep_depth[r, c])
            slp = float(slope[r, c])
            tw = float(twi[r, c])
            elev = float(dem.elevation[r, c])

            # Catchment score (peaks when catchment is substantial, >= target_catchment_ha)
            score_catchment = min(
                1.0, catchment_area_ha / max(1.0, target_catchment_ha)
            )

            # Depression score (natural storage capacity, 0 to 3m depth)
            score_depression = min(1.0, dep_d / 2.5)

            # Slope score (gentle slope < 5% is ideal, slopes > 15% penalized)
            score_slope = max(0.0, 1.0 - (slp / 15.0))

            # TWI score (higher moisture retention / wetness is better)
            score_twi = min(1.0, max(0.0, (tw - 4.0) / 10.0))

            # Weighted composite suitability score (0 - 100)
            suitability_score = round(
                100.0
                * (
                    self.w_catchment * score_catchment
                    + self.w_depression * score_depression
                    + self.w_slope * score_slope
                    + self.w_twi * score_twi
                ),
                1,
            )

            lon, lat = dem.grid_to_wgs84(r, c)
            easting, northing = dem.grid_to_utm(r, c)

            # Generate natural language engineering rationale
            rationale_parts = []
            if catchment_area_ha >= 10.0:
                rationale_parts.append(
                    f"Substantial upstream drainage ({catchment_area_ha:.1f} ha)"
                )
            else:
                rationale_parts.append(
                    f"Moderate upstream catchment ({catchment_area_ha:.1f} ha)"
                )

            if dep_d >= 1.0:
                rationale_parts.append(
                    f"Located in a natural topographic bowl ({dep_d:.1f}m depth) reducing excavation"
                )
            elif dep_d > 0.1:
                rationale_parts.append(f"Mild natural hollow ({dep_d:.1f}m)")
            else:
                rationale_parts.append("Even valley bed")

            if slp < 3.0:
                rationale_parts.append(
                    f"very gentle bed slope ({slp:.1f}%) for stable embankment"
                )
            elif slp < 8.0:
                rationale_parts.append(f"moderate slope ({slp:.1f}%)")
            else:
                rationale_parts.append(f"steep terrain ({slp:.1f}%)")

            rationale = "; ".join(rationale_parts) + "."

            scored_sites.append(
                {
                    "grid_index": {"row": int(r), "col": int(c)},
                    "coordinates": {
                        "longitude": round(float(lon), 6),
                        "latitude": round(float(lat), 6),
                        "elevation_m": round(float(elev), 2),
                    },
                    "utm_coordinates": {
                        "easting": round(float(easting), 1),
                        "northing": round(float(northing), 1),
                        "epsg": dem.utm_epsg,
                        "zone": dem.utm_zone,
                    },
                    "suitability_score": float(suitability_score),
                    "criteria_breakdown": {
                        "catchment_score": round(float(score_catchment * 100), 1),
                        "depression_score": round(float(score_depression * 100), 1),
                        "slope_stability_score": round(float(score_slope * 100), 1),
                        "wetness_index_score": round(float(score_twi * 100), 1),
                    },
                    "local_terrain": {
                        "slope_percent": round(float(slp), 2),
                        "depression_depth_m": round(float(dep_d), 2),
                        "topographic_wetness_index": round(float(tw), 2),
                        "elevation_m": round(float(elev), 2),
                    },
                    "catchment_area_ha": round(float(catchment_area_ha), 3),
                    "catchment_area_sq_m": round(float(catchment_area_m2), 1),
                    "selection_rationale": rationale,
                }
            )

        # Sort by suitability score descending
        scored_sites.sort(key=lambda s: s["suitability_score"], reverse=True)

        # Assign rank IDs
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
        Computes realistic civil engineering sizing recommendations for the pond structure.
        """
        # Standard farm/village pond design criteria (Central Water Commission / NABARD guidelines):
        # Recommended storage capacity is typically 15% to 30% of total annual runoff,
        # bounded by practical village pond sizes (typically 2,000 m3 to 50,000 m3).
        target_capacity_m3 = min(50000.0, max(2500.0, annual_runoff_m3 * 0.20))
        depth_m = max(1.5, min(5.0, target_pond_depth_m))

        # Effective trapezoidal pond shape (side slopes 1:1.5 to 1:2)
        # Volume V approx = Area_top * depth * 0.75
        required_surface_area_sq_m = target_capacity_m3 / (depth_m * 0.75)
        length_m = np.sqrt(required_surface_area_sq_m * 1.5)  # 1.5:1 aspect ratio
        width_m = required_surface_area_sq_m / length_m

        # Excavation savings due to existing depression
        effective_excavation_depth_m = max(0.5, depth_m - depression_depth_m)
        excavation_vol_m3 = (
            required_surface_area_sq_m * effective_excavation_depth_m * 0.75
        )
        excavation_savings_pct = round(
            ((depth_m - effective_excavation_depth_m) / depth_m) * 100, 1
        )

        # Embankment bund height (pond depth + 0.6m freeboard)
        bund_height_m = round(effective_excavation_depth_m + 0.6, 2)

        # Storage capacity in Liters and Million Liters (ML)
        storage_liters = target_capacity_m3 * 1000.0
        storage_million_liters = storage_liters / 1e6

        # Estimated household / cattle / supplemental irrigation support
        # Assuming 150 liters/day per capita or 1 hectare supplemental irrigation (~5,000 m3/ha)
        household_days = int(storage_liters / (5 * 150))  # 5-member family @ 150L/day
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
