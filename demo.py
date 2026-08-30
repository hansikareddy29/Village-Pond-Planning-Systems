"""
Demonstration Script for Village Pond Planning & Catchment Analysis
Runs the entire pipeline on contours_1m.kml and saves output JSON, GeoJSON, and summary.
"""

import json
import os
import time
from app.main import _process_contour_map


def run_demo():
    kml_path = os.path.join(os.path.dirname(__file__), "contours_1m.kml")
    if not os.path.exists(kml_path):
        print(f"Error: {kml_path} not found.")
        return

    print("=" * 70)
    print(" VILLAGE POND PLANNING & CATCHMENT ANALYSIS SYSTEM - DEMONSTRATION")
    print("=" * 70)
    print(f"Input Contour Map: {kml_path}")
    print("Reading and analyzing terrain...")

    with open(kml_path, "rb") as f:
        file_bytes = f.read()

    t0 = time.time()
    result = _process_contour_map(
        file_bytes=file_bytes,
        filename="contours_1m.kml",
        grid_resolution_m=10.0,
        rainfall_annual_mm=1000.0,
        runoff_coefficient=0.35,
        pond_depth_m=3.0,
        num_candidate_sites=5
    )
    t_total = time.time() - t0

    # Print Formatted Results
    meta = result["metadata"]
    terrain = result["terrain_summary"]
    site = result["recommended_pond_location"]
    catchment = result["catchment_summary"]
    design = result["pond_design_recommendations"]

    print("\n--- 1. METADATA & TERRAIN SUMMARY ---")
    print(f"• Contours Extracted:    {meta['num_contours_extracted']} contour lines")
    print(f"• Total Vertices:        {meta['total_points_sampled']:,} 3D coordinate points")
    print(f"• Contour Interval:      {meta['contour_interval_m']} m")
    print(f"• UTM Zone / EPSG:       UTM Zone {meta['utm_zone']}N (EPSG:{meta['utm_epsg']})")
    print(f"• Elevation Bounds:      {terrain['min_elevation_m']} m to {terrain['max_elevation_m']} m (Relief: {terrain['relief_m']} m)")
    print(f"• Mean Terrain Slope:    {terrain['mean_slope_percent']}% ({terrain['mean_slope_degrees']}°)")
    print(f"• DEM Grid Dimensions:   {terrain['grid_rows']} rows × {terrain['grid_cols']} cols ({terrain['total_grid_cells']:,} cells at {terrain['grid_resolution_m']}m resolution)")

    print("\n--- 2. RECOMMENDED OPTIMAL POND SITE (RANK 1) ---")
    print(f"• Site ID:               {site['site_id']}")
    print(f"• Coordinates (WGS84):   Latitude {site['coordinates']['latitude']:.6f}° N, Longitude {site['coordinates']['longitude']:.6f}° E")
    print(f"• Metric UTM:            Easting {site['utm_coordinates']['easting']:.1f} m, Northing {site['utm_coordinates']['northing']:.1f} m")
    print(f"• Elevation:             {site['coordinates']['elevation_m']} m MSL")
    print(f"• Suitability Score:     {site['suitability_score']} / 100")
    print(f"• Criteria Breakdown:    Catchment: {site['criteria_breakdown']['catchment_score']}/100 | Depression: {site['criteria_breakdown']['depression_score']}/100 | Slope: {site['criteria_breakdown']['slope_stability_score']}/100")
    print(f"• Selection Rationale:   {site['selection_rationale']}")

    print("\n--- 3. DELINEATED CATCHMENT / WATERSHED SUMMARY ---")
    print(f"• Catchment Area:        {catchment['area_hectares']} ha ({catchment['area_sq_meters']:,} m² / {catchment['area_acres']} acres)")
    print(f"• Catchment Perimeter:   {catchment['perimeter_meters']:,} m ({catchment['perimeter_meters']/1000:.2f} km)")
    print(f"• Elevation Range:       {catchment['min_elevation_m']} m to {catchment['max_elevation_m']} m (Mean: {catchment['mean_elevation_m']} m)")
    print(f"• Average Catchment Slp: {catchment['average_slope_percent']}% ({catchment['average_slope_degrees']}°)")
    print(f"• Estimated Runoff:      {catchment['estimated_annual_runoff_million_liters']} Million Liters / year ({catchment['estimated_annual_runoff_m3']:,} m³)")
    print(f"• Peak Design Discharge: {catchment['estimated_peak_discharge_m3_per_sec']} m³/s")

    print("\n--- 4. POND DESIGN & SIZING RECOMMENDATIONS ---")
    print(f"• Recommended Capacity:  {design['recommended_storage_capacity_m3']:,} m³ ({design['storage_capacity_million_liters']} ML)")
    print(f"• Recommended Depth:     {design['recommended_depth_m']} m (Bund Height: {design['recommended_bund_height_m']} m)")
    print(f"• Surface Area:          {design['recommended_surface_area_sq_m']:,} m² ({design['recommended_surface_area_hectares']} ha)")
    print(f"• Dimensions (L × W):    {design['estimated_dimensions_m']['length_m']} m × {design['estimated_dimensions_m']['width_m']} m")
    print(f"• Excavation Savings:    {design['excavation_savings_from_depression_percent']}% reduction from natural hollow utilization")
    print(f"• Command Area Support:  {design['utilization_potential']['supplemental_irrigation_ha']} ha supplemental irrigation")

    print("\n--- 5. TOP ALTERNATIVE CANDIDATE SITES ---")
    for cand in result["candidate_pond_sites"]:
        print(f"  [{cand['rank']}] {cand['site_id']} | Score: {cand['suitability_score']}/100 | Coords: ({cand['coordinates']['latitude']:.5f}, {cand['coordinates']['longitude']:.5f}) | Elev: {cand['coordinates']['elevation_m']}m | Catchment: {cand['catchment_area_ha']} ha")

    # 1. Save Full JSON Response
    out_json = os.path.join(os.path.dirname(__file__), "sample_analysis_output.json")
    with open(out_json, "w") as f:
        json.dump(result, f, indent=2)

    # 2. Save Direct GeoJSON Files
    out_geojson = os.path.join(os.path.dirname(__file__), "catchment_pond_output.geojson")
    with open(out_geojson, "w") as f:
        json.dump(result["geojson"], f, indent=2)

    out_geojson_short = os.path.join(os.path.dirname(__file__), "geo.json")
    with open(out_geojson_short, "w") as f:
        json.dump(result["geojson"], f, indent=2)

    print(f"\n✓ Full JSON analysis response saved to:   {out_json}")
    print(f"✓ Standalone GeoJSON output saved to:     {out_geojson}")
    print(f"✓ Standalone GeoJSON (geo.json) saved to: {out_geojson_short}")
    print(f"✓ Execution time: {t_total:.2f} seconds")
    print("=" * 70)


if __name__ == "__main__":
    run_demo()
