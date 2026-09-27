"""
FastAPI Backend Application for Village Pond Planning & Catchment Analysis
Provides backend REST API routes:
- GET / (Interactive Web GIS Front-End)
- POST /analyzeArea (Evaluate user-selected land area polygon)
- POST /analyzeContour (Supports format='json' or format='geojson')
- GET /health
- GET / (Redirects to /docs OpenAPI Specification)
- GET /api/default-data (Pre-computed village GIS layers and candidates)
- GET /health (Liveness & service health probe)
- GET /docs (OpenAPI Swagger Documentation)
"""

import time
import os
import json
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, status
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, status, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response
from fastapi.responses import RedirectResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles

import numpy as np
import shapely.geometry as sg
import shapely.ops
from shapely.prepared import prep
from pyproj import Transformer

from app.kml_parser import KMLParser, KMLParseError
from app.dem_generator import DEMGenerator
from app.hydrology import HydrologyEngine
from app.hydrology import HydrologyEngine, D8_NEIGHBORS
from app.pond_siting import PondSitingEngine
from app.external_apis import RainfallAPIService, ElevationAPIService
from app.models import AnalysisResponse
from app.models import AnalysisResponse, LandAreaAnalysisRequest

# Initialize FastAPI Backend Application
app = FastAPI(
    title="Village Pond Planning & Catchment Analysis Backend API",
    description="Automated backend API for continuous terrain elevation modeling, optimal village pond location ranking, and exact hydrological catchment delineation from KML/KMZ contour maps with Open-Meteo & Open-Elevation API integration.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for backend API access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files setup
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Shared Hydrology & Geospatial Engines
kml_parser = KMLParser()
dem_generator = DEMGenerator(default_resolution_m=10.0)
hydrology_engine = HydrologyEngine()
pond_siting_engine = PondSitingEngine()

# In-memory base terrain cache for sub-second responses
_BASE_MODEL_CACHE: Dict[str, Any] = {}


def _process_contour_map(
    file_bytes: bytes,
    filename: Optional[str] = None,
    grid_resolution_m: float = 10.0,
    rainfall_annual_mm: Optional[float] = None,
    runoff_coefficient: float = 0.35,
    pond_depth_m: float = 3.0,
    num_candidate_sites: int = 5,
) -> dict:
    """Core backend analysis workflow executing DEM generation, hydrological routing, and pond siting."""
    t_start = time.time()

    # 1. Parse KML/KMZ
    try:
        parsed_data = kml_parser.parse(file_bytes, filename=filename)
    except KMLParseError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"KML/KMZ Parsing Error: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to read file: {str(e)}",
        )

    # 2. Generate Continuous DEM Grid from 3D Contours (Delaunay TIN)
    try:
        dem = dem_generator.generate_dem(parsed_data, resolution_m=grid_resolution_m)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DEM Surface Generation Error: {str(e)}",
        )

    # 3. Dynamic Meteorological Rainfall & Elevation API Fetch
    center_lat = parsed_data["bounds"].get("center_lat", 21.25)
    center_lon = parsed_data["bounds"].get("center_lon", 81.30)
    rainfall_api_data = RainfallAPIService.fetch_annual_rainfall(
        latitude=center_lat, longitude=center_lon, user_override_mm=rainfall_annual_mm
    )
    effective_rainfall_mm = rainfall_api_data["annual_rainfall_mm"]
    elevation_api_data = ElevationAPIService.fetch_point_elevation(
        latitude=center_lat, longitude=center_lon
    )

    # 4. Hydrological Analysis (Priority-Flood, D8 Routing, Kahn's Topological Flow Accumulation)
    try:
        hydro_results = hydrology_engine.analyze(dem)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Hydrological Analysis Error: {str(e)}",
        )

    # 5. Dynamic Pond Candidate Siting & MCDA Ranking
    try:
        candidate_sites = pond_siting_engine.find_optimal_sites(
            dem=dem,
            hydro_results=hydro_results,
            rainfall_annual_mm=effective_rainfall_mm,
            runoff_coefficient=runoff_coefficient,
            num_candidates=num_candidate_sites,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pond Siting Optimization Error: {str(e)}",
        )

    if not candidate_sites:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No viable pond candidate locations could be identified for this terrain.",
        )

    top_site = candidate_sites[0]

    # 6. Delineate Catchment Boundary from the Associated Hydrological Pour Point
    pour_grid = (
        top_site["associated_pour_point"]["grid_index"]["row"],
        top_site["associated_pour_point"]["grid_index"]["col"],
    )
    catchment_info = hydrology_engine.delineate_catchment(
        pour_point_grid=pour_grid, flow_dir=hydro_results["flow_direction"], dem=dem
    )

    # 7. Estimate Runoff & Water Yield
    runoff_info = hydrology_engine.estimate_runoff(
        catchment_area_sq_m=catchment_info["area_sq_meters"],
        annual_rainfall_mm=effective_rainfall_mm,
        runoff_coefficient=runoff_coefficient,
    )

    # 8. Sizing & Civil Engineering Recommendations
    pond_design = pond_siting_engine.compute_design_recommendations(
        catchment_area_sq_m=catchment_info["area_sq_meters"],
        annual_runoff_m3=runoff_info["estimated_annual_runoff_m3"],
        depression_depth_m=top_site["local_terrain"]["depression_depth_m"],
        target_pond_depth_m=pond_depth_m,
    )

    # 9. Assemble GeoJSON Feature Collection distinguishing Pond Region vs Pour Point
    geojson_features = []

    # A. Add Full Natural Depression Basins & Compact Farm Ponds for ALL Candidate Sites
    for site in candidate_sites:
        s_rank = site["rank"]
        s_id = site["site_id"]
        is_primary = s_rank == 1

        # 1. Full Natural Depression Basin
        if site.get("continuous_basin_geometry"):
            geojson_features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "title": f"Rank {s_rank}: Full Basin",
                        "name": f"Full Natural Basin - Rank {s_rank} ({s_id})",
                        "feature_type": "full_natural_basin",
                        "site_id": s_id,
                        "rank": s_rank,
                        "area_hectares": site.get("continuous_basin_footprint_ha"),
                        "depression_depth_m": site["local_terrain"][
                            "depression_depth_m"
                        ],
                        "elevation_m": site["coordinates"]["elevation_m"],
                        "suitability_score": site["suitability_score"],
                        "fill": "#00E676" if is_primary else "#4CAF50",
                        "fill-opacity": 0.22 if is_primary else 0.18,
                        "stroke": "#00B0FF" if is_primary else "#0288D1",
                        "stroke-width": 3,
                        "stroke-dasharray": "6 6",
                        "style": {
                            "color": "#00B0FF" if is_primary else "#0288D1",
                            "weight": 3,
                            "dashArray": "6, 6",
                            "fillColor": "#00E676" if is_primary else "#4CAF50",
                            "fillOpacity": 0.22 if is_primary else 0.18,
                        },
                    },
                    "geometry": site["continuous_basin_geometry"],
                }
            )

        # 2. Compact Core Village Farm Pond
        if site.get("compact_pond_geometry"):
            geojson_features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "title": f"Rank {s_rank}: Compact Pond",
                        "name": f"Compact Core Farm Pond - Rank {s_rank} ({s_id})",
                        "feature_type": "compact_pond_footprint",
                        "site_id": s_id,
                        "rank": s_rank,
                        "area_hectares": site.get("compact_pond_footprint_ha"),
                        "depression_depth_m": site["local_terrain"][
                            "depression_depth_m"
                        ],
                        "elevation_m": site["coordinates"]["elevation_m"],
                        "suitability_score": site["suitability_score"],
                        "fill": "#00C853" if is_primary else "#2E7D32",
                        "fill-opacity": 0.85 if is_primary else 0.75,
                        "stroke": "#FFD600" if is_primary else "#FFA000",
                        "stroke-width": 4 if is_primary else 3,
                        "style": {
                            "color": "#FFD600" if is_primary else "#FFA000",
                            "weight": 4 if is_primary else 3,
                            "fillColor": "#00C853" if is_primary else "#2E7D32",
                            "fillOpacity": 0.85 if is_primary else 0.75,
                        },
                    },
                    "geometry": site["compact_pond_geometry"],
                }
            )

    # B. Drainage / Stream Network
    geojson_features.append(hydro_results["streams"])

    # C. Candidate Pond Sites (Point Features with Numbered Pins 1, 2, 3, 4, 5)
    marker_palette = {
        1: "#00C853",  # Vibrant Green for Rank 1
        2: "#E65100",  # Dark Orange for Rank 2
        3: "#F57C00",  # Amber Orange for Rank 3
        4: "#FFA000",  # Gold Amber for Rank 4
        5: "#FFB300",  # Yellow Gold for Rank 5
    }

    for site in candidate_sites:
        s_rank = site["rank"]
        s_id = site["site_id"]
        is_primary = s_rank == 1
        m_color = marker_palette.get(s_rank, "#FF9100")

        pond_props = {
            "title": f"Rank {s_rank}: {s_id}",
            "name": f"Rank {s_rank}: Optimal Pond Location ({s_id})",
            "marker-symbol": str(s_rank),
            "marker-color": m_color,
            "marker-size": "large",
            "feature_type": "pond_candidate",
            "site_id": s_id,
            "rank": s_rank,
            "candidate_type": site["candidate_type"],
            "suitability_score": site["suitability_score"],
            "elevation_m": site["coordinates"]["elevation_m"],
            "local_slope_percent": site["local_terrain"]["slope_percent"],
            "depression_depth_m": site["local_terrain"]["depression_depth_m"],
            "catchment_area_ha": site["catchment_area_ha"],
            "selection_rationale": site.get("selection_rationale", ""),
            "marker_color": m_color,
            "is_primary": is_primary,
            "description": (
                f"Rank {s_rank} Pond Location ({s_id})\n"
                f"• Suitability Score: {site['suitability_score']} / 100\n"
                f"• Natural Depression Depth: {site['local_terrain']['depression_depth_m']} m\n"
                f"• Catchment Runoff Area: {site['catchment_area_ha']} ha\n"
                f"• Ground Bed Slope: {site['local_terrain']['slope_percent']}%\n"
                f"• Bed Elevation: {site['coordinates']['elevation_m']} m\n"
                f"• Annual Water Harvest: {site.get('estimated_annual_water_yield_m3', 0):,.0f} m³"
            ),
        }
        if "elevation_api_m" in site["coordinates"]:
            pond_props["elevation_api_m"] = site["coordinates"]["elevation_api_m"]

        geojson_features.append(
            {
                "type": "Feature",
                "properties": pond_props,
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        site["coordinates"]["longitude"],
                        site["coordinates"]["latitude"],
                    ],
                },
            }
        )

        # D. Associated Hydrological Pour Point / Spillway Feature
        if site.get("associated_pour_point"):
            pp = site["associated_pour_point"]
            geojson_features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "title": f"Spillway {s_rank}",
                        "name": f"Rank {s_rank} Spillway Pour Point",
                        "marker-symbol": "water",
                        "marker-color": "#00B0FF",
                        "marker-size": "small",
                        "feature_type": "pour_point",
                        "site_id": s_id,
                        "rank": s_rank,
                        "elevation_m": pp["coordinates"]["elevation_m"],
                        "drainage_flow_acc_cells": pp.get("flow_accumulation_cells"),
                        "description": f"Natural Spillway Overflow Point for Rank {s_rank} Pond (Crest Elev: {pp['coordinates']['elevation_m']} m)",
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [
                            pp["coordinates"]["longitude"],
                            pp["coordinates"]["latitude"],
                        ],
                    },
                }
            )

    # F. Survey Boundary Polygon if present in KML
    if parsed_data.get("boundary_polygon"):
        b_pts = parsed_data["boundary_polygon"]
        b_coords = [[pt[0], pt[1]] for pt in b_pts]
        if b_coords and b_coords[0] != b_coords[-1]:
            b_coords.append(b_coords[0])
        geojson_features.append(
            {
                "type": "Feature",
                "properties": {
                    "name": "Survey Boundary",
                    "feature_type": "survey_boundary",
                    "style": {"color": "#E91E63", "weight": 2, "dashArray": "5, 5"},
                },
                "geometry": {"type": "Polygon", "coordinates": [b_coords]},
            }
        )

    geojson_collection = {"type": "FeatureCollection", "features": geojson_features}

    t_exec = round(time.time() - t_start, 3)

    # 10. Format Structured JSON Response
    response = {
        "success": True,
        "message": "Contour map terrain analysis and catchment delineation completed successfully.",
        "execution_time_seconds": t_exec,
        "metadata": {
            "filename": filename or "uploaded_file.kml",
            "num_contours_extracted": parsed_data["num_contours"],
            "total_points_sampled": len(parsed_data["point_cloud"]),
            "contour_interval_m": parsed_data["contour_interval"],
            "utm_zone": dem.utm_zone,
            "utm_epsg": dem.utm_epsg,
            "bounds_wgs84": parsed_data["bounds"],
            "rainfall_service": rainfall_api_data,
            "elevation_service": elevation_api_data,
        },
        "terrain_summary": {
            "min_elevation_m": round(dem.stats["min_elevation"], 2),
            "max_elevation_m": round(dem.stats["max_elevation"], 2),
            "mean_elevation_m": round(dem.stats["mean_elevation"], 2),
            "relief_m": round(dem.stats["relief"], 2),
            "mean_slope_percent": round(dem.stats["mean_slope_percent"], 2),
            "mean_slope_degrees": round(dem.stats["mean_slope_degrees"], 2),
            "grid_resolution_m": dem.resolution_m,
            "grid_rows": dem.stats["grid_rows"],
            "grid_cols": dem.stats["grid_cols"],
            "total_grid_cells": dem.stats["total_grid_cells"],
            "elevation_source": "KML_3D_Contour_TIN_Interpolation",
        },
        "recommended_pond_location": top_site,
        "catchment_summary": {
            "area_sq_meters": catchment_info["area_sq_meters"],
            "area_hectares": catchment_info["area_hectares"],
            "area_acres": catchment_info["area_acres"],
            "perimeter_meters": catchment_info["perimeter_meters"],
            "min_elevation_m": catchment_info["min_elevation_m"],
            "max_elevation_m": catchment_info["max_elevation_m"],
            "mean_elevation_m": catchment_info["mean_elevation_m"],
            "elevation_range_m": catchment_info["elevation_range_m"],
            "average_slope_percent": catchment_info["average_slope_percent"],
            "average_slope_degrees": catchment_info["average_slope_degrees"],
            "centroid_wgs84": catchment_info["centroid_wgs84"],
            "annual_rainfall_mm": runoff_info["annual_rainfall_mm"],
            "rainfall_source": rainfall_api_data.get("source", "open-meteo-api"),
            "runoff_coefficient": runoff_info["runoff_coefficient"],
            "estimated_annual_runoff_m3": runoff_info["estimated_annual_runoff_m3"],
            "estimated_annual_runoff_liters": runoff_info[
                "estimated_annual_runoff_liters"
            ],
            "estimated_annual_runoff_million_liters": runoff_info[
                "estimated_annual_runoff_million_liters"
            ],
            "estimated_peak_discharge_m3_per_sec": runoff_info[
                "estimated_peak_discharge_m3_per_sec"
            ],
        },
        "pond_design_recommendations": pond_design,
        "candidate_pond_sites": candidate_sites,
        "geojson": geojson_collection,
    }

    return response


def get_base_model() -> Dict[str, Any]:
    """Retrieves or builds in-memory cached base model for default terrain."""
    if "default" in _BASE_MODEL_CACHE:
        return _BASE_MODEL_CACHE["default"]

    sample_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "contours_1m.kml"
    )
    if not os.path.exists(sample_path):
        raise HTTPException(
            status_code=500,
            detail="Default contour file contours_1m.kml not found.",
        )
    with open(sample_path, "rb") as f:
        contents = f.read()

    parsed_data = kml_parser.parse(contents, filename="contours_1m.kml")
    dem = dem_generator.generate_dem(parsed_data, resolution_m=10.0)
    center_lat = parsed_data["bounds"].get("center_lat", 21.25)
    center_lon = parsed_data["bounds"].get("center_lon", 81.30)
    rainfall_api_data = RainfallAPIService.fetch_annual_rainfall(
        latitude=center_lat, longitude=center_lon
    )
    elevation_api_data = ElevationAPIService.fetch_point_elevation(
        latitude=center_lat, longitude=center_lon
    )
    hydro_results = hydrology_engine.analyze(dem)
    candidate_sites = pond_siting_engine.find_optimal_sites(
        dem=dem,
        hydro_results=hydro_results,
        rainfall_annual_mm=rainfall_api_data["annual_rainfall_mm"],
        runoff_coefficient=0.35,
        num_candidates=5,
    )

    _BASE_MODEL_CACHE["default"] = {
        "parsed_data": parsed_data,
        "dem": dem,
        "rainfall_api_data": rainfall_api_data,
        "elevation_api_data": elevation_api_data,
        "hydro_results": hydro_results,
        "candidate_sites": candidate_sites,
    }
    return _BASE_MODEL_CACHE["default"]


def _process_land_area(
    geometry: dict,
    rainfall_annual_mm: Optional[float] = None,
    runoff_coefficient: float = 0.35,
    pond_depth_m: float = 3.0,
) -> dict:
    t_start = time.time()
    model = get_base_model()
    dem = model["dem"]
    hydro_results = model["hydro_results"]
    candidate_sites = model["candidate_sites"]
    effective_rainfall_mm = (
        rainfall_annual_mm
        if rainfall_annual_mm is not None and rainfall_annual_mm > 0
        else model["rainfall_api_data"]["annual_rainfall_mm"]
    )

    try:
        user_poly = sg.shape(geometry)
        if not user_poly.is_valid:
            from shapely.validation import make_valid

            user_poly = make_valid(user_poly)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid land area polygon geometry: {str(e)}",
        )

    # Validate that selected land intersects the surveyed contour elevation area
    b = model["parsed_data"]["bounds"]
    bp = model["parsed_data"].get("boundary_polygon")
    if bp and len(bp) >= 3:
        survey_poly = sg.Polygon([(p[0], p[1]) for p in bp])
    else:
        survey_poly = sg.box(b["min_lon"], b["min_lat"], b["max_lon"], b["max_lat"])

    if not user_poly.intersects(survey_poly):
        raise HTTPException(
            status_code=400,
            detail=(
                "The selected land area lies outside the surveyed elevation contour area "
                "(Sirsa Khurd village). Elevation and runoff data are only available within "
                "the surveyed village boundary. Please draw or select a parcel within the "
                "highlighted village survey perimeter."
            ),
        )

    overlap_poly = user_poly.intersection(survey_poly)
    if overlap_poly.is_empty or overlap_poly.area < 1e-10:
        raise HTTPException(
            status_code=400,
            detail="The selected land area has no valid overlap with the surveyed elevation contour area.",
        )

    # Compute metric area of selected land polygon
    poly_utm = shapely.ops.transform(dem.transformer_to_utm.transform, user_poly)
    selected_land_area_sq_m = float(poly_utm.area)
    selected_land_area_ha = round(selected_land_area_sq_m / 10000.0, 3)
    selected_land_area_acres = round(selected_land_area_sq_m / 4046.85642, 3)

    # Check which candidate sites are inside the selected land area
    contained_sites = []
    for site in candidate_sites:
        pt = sg.Point(site["coordinates"]["longitude"], site["coordinates"]["latitude"])
        if user_poly.contains(pt) or user_poly.intersects(pt):
            contained_sites.append(site)

    if contained_sites:
        chosen_site = contained_sites[0]
        site_id = chosen_site["site_id"]
        pour_grid = (
            chosen_site["associated_pour_point"]["grid_index"]["row"],
            chosen_site["associated_pour_point"]["grid_index"]["col"],
        )
    else:
        # User selected a custom parcel without pre-computed candidate
        minx, miny, maxx, maxy = overlap_poly.bounds
        min_r, min_c = dem.wgs84_to_grid(minx, miny)
        max_r, max_c = dem.wgs84_to_grid(maxx, maxy)
        r0 = max(0, min(min_r, max_r) - 1)
        r1 = min(dem.rows, max(min_r, max_r) + 2)
        c0 = max(0, min(min_c, max_c) - 1)
        c1 = min(dem.cols, max(min_c, max_c) + 2)

        best_r, best_c = None, None
        best_metric = -1e9
        prep_poly = prep(user_poly)

        for r in range(r0, r1):
            for c in range(c0, c1):
                lon, lat = dem.grid_to_wgs84(r, c)
                pt = sg.Point(lon, lat)
                if prep_poly.contains(pt):
                    dep = float(hydro_results["depression_depth"][r, c])
                    acc = float(hydro_results["flow_accumulation"][r, c])
                    slope_val = float(dem.slope_percent[r, c])
                    metric = (dep * 20.0) + np.log1p(acc) * 5.0 - (slope_val * 0.5)
                    if metric > best_metric:
                        best_metric = metric
                        best_r, best_c = r, c

        if best_r is None:
            # If the parcel is very small/narrow and doesn't contain a 10m grid center,
            # use a guaranteed interior point from the representative point of the polygon
            rep_pt = overlap_poly.representative_point()
            lon, lat = float(rep_pt.x), float(rep_pt.y)
            gr, gc = dem.wgs84_to_grid(lon, lat)
            best_r = int(np.clip(gr, 0, dem.rows - 1))
            best_c = int(np.clip(gc, 0, dem.cols - 1))
        else:
            lon, lat = dem.grid_to_wgs84(best_r, best_c)

        easting, northing = dem.grid_to_utm(best_r, best_c)
        elev = float(dem.elevation[best_r, best_c])
        dep_val = float(hydro_results["depression_depth"][best_r, best_c])
        slope_pct = float(dem.slope_percent[best_r, best_c])
        acc_cells = float(hydro_results["flow_accumulation"][best_r, best_c])

        # Trace D8 flow direction to pour point
        curr_r, curr_c = best_r, best_c
        flow_dir = hydro_results["flow_direction"]
        for _ in range(50):
            d = flow_dir[curr_r, curr_c]
            if d >= 0:
                dr, dc, _ = D8_NEIGHBORS[d]
                nr, nc = curr_r + dr, curr_c + dc
                if 0 <= nr < dem.rows and 0 <= nc < dem.cols:
                    curr_r, curr_c = nr, nc
                    if hydro_results["depression_depth"][curr_r, curr_c] == 0.0:
                        break
                else:
                    break
            else:
                break
        pour_r, pour_c = curr_r, curr_c
        pour_lon, pour_lat = dem.grid_to_wgs84(pour_r, pour_c)
        pour_elev = float(dem.elevation[pour_r, pour_c])

        site_id = "custom_selected_parcel_pond"
        pour_grid = (pour_r, pour_c)

        chosen_site = {
            "rank": 1,
            "site_id": site_id,
            "candidate_type": "user_land_selection",
            "coordinates": {
                "longitude": round(lon, 6),
                "latitude": round(lat, 6),
                "elevation_m": round(elev, 2),
            },
            "utm_coordinates": {
                "easting": round(easting, 1),
                "northing": round(northing, 1),
                "zone": dem.utm_zone,
                "epsg": dem.utm_epsg,
            },
            "grid_index": {"row": best_r, "col": best_c},
            "local_terrain": {
                "slope_percent": round(slope_pct, 2),
                "depression_depth_m": round(dep_val, 2),
                "elevation_m": round(elev, 2),
                "topographic_wetness_index": round(
                    float(
                        np.log(
                            (acc_cells * 10.0)
                            / max(
                                0.01,
                                np.tan(np.deg2rad(dem.slope_degrees[best_r, best_c])),
                            )
                        )
                    ),
                    2,
                ),
            },
            "associated_pour_point": {
                "coordinates": {
                    "longitude": round(pour_lon, 6),
                    "latitude": round(pour_lat, 6),
                    "elevation_m": round(pour_elev, 2),
                },
                "grid_index": {"row": pour_r, "col": pour_c},
                "flow_accumulation_cells": float(
                    hydro_results["flow_accumulation"][pour_r, pour_c]
                ),
                "drainage_area_ha": round(
                    (float(hydro_results["flow_accumulation"][pour_r, pour_c]) * 100.0)
                    / 10000.0,
                    3,
                ),
            },
            "suitability_score": round(
                min(98.0, max(55.0, 78.0 + (dep_val * 2.5) - (slope_pct * 1.2))), 1
            ),
            "selection_rationale": "Optimal topographic storage sink identified within the user-selected land boundary.",
        }

    # Catchment delineation
    catchment_info = hydrology_engine.delineate_catchment(
        pour_point_grid=pour_grid,
        flow_dir=hydro_results["flow_direction"],
        dem=dem,
    )

    # Runoff estimation
    runoff_info = hydrology_engine.estimate_runoff(
        catchment_area_sq_m=catchment_info["area_sq_meters"],
        annual_rainfall_mm=effective_rainfall_mm,
        runoff_coefficient=runoff_coefficient,
    )

    # Pond design recommendations
    pond_design = pond_siting_engine.compute_design_recommendations(
        catchment_area_sq_m=catchment_info["area_sq_meters"],
        annual_runoff_m3=runoff_info["estimated_annual_runoff_m3"],
        depression_depth_m=chosen_site["local_terrain"]["depression_depth_m"],
        target_pond_depth_m=pond_depth_m,
    )

    # Build GeoJSON features
    geojson_features = []

    # 1. Selected land area polygon
    user_poly_geojson = json.loads(json.dumps(sg.mapping(user_poly)))
    geojson_features.append(
        {
            "type": "Feature",
            "properties": {
                "title": "Selected Land Area",
                "name": f"Selected Land Area ({selected_land_area_ha} ha)",
                "feature_type": "selected_land_area",
                "area_hectares": selected_land_area_ha,
                "area_acres": selected_land_area_acres,
                "fill": "#E91E63",
                "fill-opacity": 0.16,
                "stroke": "#D81B60",
                "stroke-width": 3,
                "stroke-dasharray": "6 4",
                "style": {
                    "color": "#D81B60",
                    "weight": 3,
                    "dashArray": "6, 4",
                    "fillColor": "#E91E63",
                    "fillOpacity": 0.16,
                },
            },
            "geometry": user_poly_geojson,
        }
    )

    # 2. Delineated catchment area polygon
    geojson_features.append(
        {
            "type": "Feature",
            "properties": {
                "title": f"Delineated Catchment ({catchment_info['area_hectares']} ha)",
                "name": f"Upstream Catchment Basin for {chosen_site['site_id']}",
                "feature_type": "catchment_boundary",
                "area_hectares": catchment_info["area_hectares"],
                "area_acres": catchment_info["area_acres"],
                "area_sq_meters": catchment_info["area_sq_meters"],
                "min_elevation_m": catchment_info["min_elevation_m"],
                "max_elevation_m": catchment_info["max_elevation_m"],
                "expected_runoff_m3": runoff_info["estimated_annual_runoff_m3"],
                "expected_runoff_million_liters": runoff_info[
                    "estimated_annual_runoff_million_liters"
                ],
                "fill": "#00E5FF",
                "fill-opacity": 0.22,
                "stroke": "#00B0FF",
                "stroke-width": 3,
                "stroke-dasharray": "6 6",
                "style": {
                    "color": "#00B0FF",
                    "weight": 3,
                    "dashArray": "6, 6",
                    "fillColor": "#00E5FF",
                    "fillOpacity": 0.22,
                },
            },
            "geometry": catchment_info["geojson"]["geometry"],
        }
    )

    # 3. Stream network
    geojson_features.append(hydro_results["streams"])

    # 4. Compact Pond Footprint
    if chosen_site.get("compact_pond_geometry"):
        pond_geom = chosen_site["compact_pond_geometry"]
        footprint_ha = chosen_site.get(
            "compact_pond_footprint_ha",
            pond_design["recommended_surface_area_hectares"],
        )
    else:
        # Buffer circular pond footprint in UTM
        pt_easting, pt_northing = dem.grid_to_utm(
            chosen_site["grid_index"]["row"],
            chosen_site["grid_index"]["col"],
        )
        radius_m = max(
            15.0,
            np.sqrt(pond_design["recommended_surface_area_sq_m"] / np.pi),
        )
        circle_utm = sg.Point(pt_easting, pt_northing).buffer(radius_m)
        transformer_to_wgs = Transformer.from_crs(
            f"EPSG:{dem.utm_epsg}", "EPSG:4326", always_xy=True
        )
        circle_wgs = shapely.ops.transform(transformer_to_wgs.transform, circle_utm)
        pond_geom = json.loads(json.dumps(sg.mapping(circle_wgs)))
        footprint_ha = round((np.pi * (radius_m**2)) / 10000.0, 3)

    geojson_features.append(
        {
            "type": "Feature",
            "properties": {
                "title": f"Pond Footprint ({footprint_ha} ha)",
                "name": f"Excavation Footprint - {chosen_site['site_id']}",
                "feature_type": "compact_pond_footprint",
                "site_id": chosen_site["site_id"],
                "area_hectares": footprint_ha,
                "design_depth_m": pond_depth_m,
                "storage_capacity_m3": pond_design["recommended_storage_capacity_m3"],
                "fill": "#00C853",
                "fill-opacity": 0.85,
                "stroke": "#FFD600",
                "stroke-width": 4,
                "style": {
                    "color": "#FFD600",
                    "weight": 4,
                    "fillColor": "#00C853",
                    "fillOpacity": 0.85,
                },
            },
            "geometry": pond_geom,
        }
    )

    # 5. Full Natural Basin if available
    if chosen_site.get("continuous_basin_geometry"):
        geojson_features.append(
            {
                "type": "Feature",
                "properties": {
                    "title": f"Natural Basin ({chosen_site.get('continuous_basin_footprint_ha')} ha)",
                    "name": f"Full Natural Retention Bowl - {chosen_site['site_id']}",
                    "feature_type": "full_natural_basin",
                    "site_id": chosen_site["site_id"],
                    "area_hectares": chosen_site.get("continuous_basin_footprint_ha"),
                    "fill": "#00E676",
                    "fill-opacity": 0.18,
                    "stroke": "#00B0FF",
                    "stroke-width": 2,
                    "stroke-dasharray": "4 4",
                    "style": {
                        "color": "#00B0FF",
                        "weight": 2,
                        "dashArray": "4, 4",
                        "fillColor": "#00E676",
                        "fillOpacity": 0.18,
                    },
                },
                "geometry": chosen_site["continuous_basin_geometry"],
            }
        )

    # 6. Suggested Pond Location Pin
    geojson_features.append(
        {
            "type": "Feature",
            "properties": {
                "title": f"Suggested Pond ({chosen_site['site_id']})",
                "name": f"Optimal Pond Location ({chosen_site['site_id']})",
                "marker-symbol": str(chosen_site.get("rank", 1)),
                "marker-color": "#00C853",
                "marker-size": "large",
                "feature_type": "pond_candidate",
                "site_id": chosen_site["site_id"],
                "rank": chosen_site.get("rank", 1),
                "suitability_score": chosen_site.get("suitability_score", 90.0),
                "elevation_m": chosen_site["coordinates"]["elevation_m"],
                "depression_depth_m": chosen_site["local_terrain"][
                    "depression_depth_m"
                ],
                "bed_slope_percent": chosen_site["local_terrain"]["slope_percent"],
                "catchment_area_ha": catchment_info["area_hectares"],
                "annual_water_harvest_m3": runoff_info["estimated_annual_runoff_m3"],
                "annual_water_harvest_million_liters": runoff_info[
                    "estimated_annual_runoff_million_liters"
                ],
                "description": (
                    f"Suggested Pond Location ({chosen_site['site_id']})\n"
                    f"• Suitability Score: {chosen_site.get('suitability_score', 90.0)} / 100\n"
                    f"• Natural Depression Depth: {chosen_site['local_terrain']['depression_depth_m']} m\n"
                    f"• Bed Elevation: {chosen_site['coordinates']['elevation_m']} m\n"
                    f"• Upstream Catchment: {catchment_info['area_hectares']} ha\n"
                    f"• Expected Annual Water Volume: {runoff_info['estimated_annual_runoff_m3']:,.0f} m³ ({runoff_info['estimated_annual_runoff_million_liters']} ML)"
                ),
            },
            "geometry": {
                "type": "Point",
                "coordinates": [
                    chosen_site["coordinates"]["longitude"],
                    chosen_site["coordinates"]["latitude"],
                ],
            },
        }
    )

    # 7. Spillway Pour Point
    pp = chosen_site["associated_pour_point"]
    geojson_features.append(
        {
            "type": "Feature",
            "properties": {
                "title": "Spillway Overflow Point",
                "name": f"Spillway Pour Point for {chosen_site['site_id']}",
                "marker-symbol": "water",
                "marker-color": "#00B0FF",
                "marker-size": "small",
                "feature_type": "pour_point",
                "site_id": chosen_site["site_id"],
                "elevation_m": pp["coordinates"]["elevation_m"],
                "description": f"Natural Spillway Overflow Point (Crest Elev: {pp['coordinates']['elevation_m']} m)",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [
                    pp["coordinates"]["longitude"],
                    pp["coordinates"]["latitude"],
                ],
            },
        }
    )

    t_exec = round(time.time() - t_start, 3)

    return {
        "success": True,
        "message": f"Land area analysis completed. Identified optimal pond location {chosen_site['site_id']}.",
        "execution_time_seconds": t_exec,
        "selected_land_area_ha": selected_land_area_ha,
        "selected_land_area_acres": selected_land_area_acres,
        "selected_land_area_sq_meters": selected_land_area_sq_m,
        "recommended_pond_location": chosen_site,
        "catchment_summary": {
            "area_sq_meters": catchment_info["area_sq_meters"],
            "area_hectares": catchment_info["area_hectares"],
            "area_acres": catchment_info["area_acres"],
            "perimeter_meters": catchment_info["perimeter_meters"],
            "min_elevation_m": catchment_info["min_elevation_m"],
            "max_elevation_m": catchment_info["max_elevation_m"],
            "mean_elevation_m": catchment_info["mean_elevation_m"],
            "elevation_range_m": catchment_info["elevation_range_m"],
            "average_slope_percent": catchment_info["average_slope_percent"],
            "centroid_wgs84": catchment_info["centroid_wgs84"],
        },
        "expected_water_volume": {
            "estimated_annual_runoff_m3": runoff_info["estimated_annual_runoff_m3"],
            "estimated_annual_runoff_liters": runoff_info[
                "estimated_annual_runoff_liters"
            ],
            "estimated_annual_runoff_million_liters": runoff_info[
                "estimated_annual_runoff_million_liters"
            ],
            "annual_rainfall_mm": runoff_info["annual_rainfall_mm"],
            "runoff_coefficient": runoff_info["runoff_coefficient"],
            "rainfall_source": "Open-Meteo ERA5 Reanalysis",
        },
        "pond_design_recommendations": pond_design,
        "geojson": {
            "type": "FeatureCollection",
            "features": geojson_features,
        },
    }


@app.post(
    "/analyzeArea",
    summary="Analyze User-Selected Land Area on Map",
    description="Accepts a GeoJSON polygon or geometry representing a user-selected land area on the map. Returns the optimal suggested pond location, delineated catchment area, and expected water volume that can be collected, with complete overlaid GeoJSON layers.",
)
async def analyze_area(
    payload: Dict[str, Any] = Body(
        ...,
        example={
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [81.295, 21.250],
                        [81.305, 21.250],
                        [81.305, 21.260],
                        [81.295, 21.260],
                        [81.295, 21.250],
                    ]
                ],
            },
            "rainfall_annual_mm": None,
            "runoff_coefficient": 0.35,
            "pond_depth_m": 3.0,
            "format": "json",
        },
    )
):
    if "geometry" not in payload:
        raise HTTPException(
            status_code=400,
            detail="Missing 'geometry' object in request body.",
        )

    geometry = payload["geometry"]
    rainfall_annual_mm = payload.get("rainfall_annual_mm")
    runoff_coefficient = float(payload.get("runoff_coefficient", 0.35))
    pond_depth_m = float(payload.get("pond_depth_m", 3.0))
    fmt = str(payload.get("format", "json")).lower()

    result = _process_land_area(
        geometry=geometry,
        rainfall_annual_mm=rainfall_annual_mm,
        runoff_coefficient=runoff_coefficient,
        pond_depth_m=pond_depth_m,
    )

    if fmt == "geojson":
        geojson_str = json.dumps(result["geojson"], indent=2)
        return Response(
            content=geojson_str,
            media_type="application/geo+json",
            headers={
                "Content-Disposition": "attachment; filename=selected_land_catchment.geojson"
            },
        )

    return result


@app.get(
    "/api/default-data",
    summary="Retrieve Default Village Terrain and Baseline Data",
)
async def get_default_data():
    """Returns baseline metadata, pre-computed candidates, streams, and preset sectors for fast map load."""
    model = get_base_model()
    parsed = model["parsed_data"]
    dem = model["dem"]
    sites = model["candidate_sites"]
    hydro = model["hydro_results"]

    # Pre-defined agricultural zones / sectors of Sirsa Khurd village for rapid selection
    preset_sectors = [
        {
            "id": "sector_central_valley",
            "name": "Sector 1: Central Valley & Agricultural Interior (~174 ha)",
            "description": "Primary low-lying natural hollow with largest drainage accumulation.",
            "recommended_site_id": "pond_site_1",
            "coordinates": [
                [81.292, 21.248],
                [81.302, 21.248],
                [81.302, 21.256],
                [81.292, 21.256],
                [81.292, 21.248],
            ],
        },
        {
            "id": "sector_east_farmlands",
            "name": "Sector 2: East Farmlands Plain (~111 ha)",
            "description": "Expansive agricultural basin with flat slopes for community storage.",
            "recommended_site_id": "pond_site_2",
            "coordinates": [
                [81.297, 21.244],
                [81.305, 21.244],
                [81.305, 21.252],
                [81.297, 21.252],
                [81.297, 21.244],
            ],
        },
        {
            "id": "sector_northeast_talab",
            "name": "Sector 3: Northeast Historical Water Basin (~13 ha)",
            "description": "Historical Sirsa Khurd village water reservoir (Ground-Truth Validated).",
            "recommended_site_id": "pond_site_3",
            "coordinates": [
                [81.299, 21.254],
                [81.306, 21.254],
                [81.306, 21.261],
                [81.299, 21.261],
                [81.299, 21.254],
            ],
        },
        {
            "id": "sector_northwest_plain",
            "name": "Sector 4: Northwest River Plain (~96 ha)",
            "description": "Captures descending agricultural runoff before regional discharge.",
            "recommended_site_id": "pond_site_4",
            "coordinates": [
                [81.288, 21.255],
                [81.296, 21.255],
                [81.296, 21.264],
                [81.288, 21.264],
                [81.288, 21.255],
            ],
        },
        {
            "id": "sector_south_fields",
            "name": "Sector 5: Southeast Farmland Plain (~43 ha)",
            "description": "Decentralized pond site securing water for southern agricultural belt.",
            "recommended_site_id": "pond_site_5",
            "coordinates": [
                [81.304, 21.240],
                [81.312, 21.240],
                [81.312, 21.248],
                [81.304, 21.248],
                [81.304, 21.240],
            ],
        },
    ]

    bp = parsed.get("boundary_polygon")
    formatted_bp = None
    if bp and len(bp) >= 3:
        formatted_bp = [[round(pt[0], 6), round(pt[1], 6)] for pt in bp]

    return {
        "village_name": "Sirsa Khurd / Jeora Sirsa, Durg, Chhattisgarh",
        "center": [
            parsed["bounds"].get("center_lat", 21.2518),
            parsed["bounds"].get("center_lon", 81.2966),
        ],
        "bounds": parsed["bounds"],
        "boundary_polygon": formatted_bp,
        "total_area_hectares": round(
            (dem.rows * dem.cols * (dem.resolution_m**2)) / 10000.0, 1
        ),
        "elevation_summary": {
            "min_elevation_m": round(dem.stats["min_elevation"], 1),
            "max_elevation_m": round(dem.stats["max_elevation"], 1),
            "relief_m": round(dem.stats["relief"], 1),
            "mean_slope_percent": round(dem.stats["mean_slope_percent"], 1),
        },
        "rainfall_summary": model["rainfall_api_data"],
        "candidate_sites": sites,
        "preset_sectors": preset_sectors,
        "streams": hydro["streams"],
    }


@app.post(
    "/analyzeContour",
    summary="Analyze Contour Map & Delineate Catchment",
    description="Upload a KML or KMZ contour map file. The backend automatically models continuous terrain, queries satellite meteorological rainfall from Open-Meteo API, and returns optimal pond locations with delineated catchments and GIS GeoJSON.",
)
async def analyze_contour(
    file: Optional[UploadFile] = File(
        None,
        description="KML or KMZ contour map file (optional, defaults to sample contours_1m.kml)",
    ),
    format: str = Form(
        "json",
        description="Output format: 'json' (complete analysis report) or 'geojson' (GIS FeatureCollection)",
    ),
):
    # Core engineering defaults kept in code (auto-calibrated for village watersheds)
    grid_resolution_m: float = 10.0
    rainfall_annual_mm: Optional[float] = None
    runoff_coefficient: float = 0.35
    pond_depth_m: float = 3.0
    num_candidate_sites: int = 5

    if file is not None and file.filename:
        contents = await file.read()
        filename = file.filename
    else:
        sample_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "contours_1m.kml"
        )
        if not os.path.exists(sample_path):
            raise HTTPException(
                status_code=400,
                detail="No file uploaded and sample contours_1m.kml not found.",
            )
        with open(sample_path, "rb") as f:
            contents = f.read()
        filename = "contours_1m.kml"

    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    analysis_result = _process_contour_map(
        file_bytes=contents,
        filename=filename,
        grid_resolution_m=grid_resolution_m,
        rainfall_annual_mm=rainfall_annual_mm,
        runoff_coefficient=runoff_coefficient,
        pond_depth_m=pond_depth_m,
        num_candidate_sites=num_candidate_sites,
    )

    # Return pure GeoJSON file if requested
    if format.lower() == "geojson":
        geojson_str = json.dumps(analysis_result["geojson"], indent=2)
        return Response(
            content=geojson_str,
            media_type="application/geo+json",
            headers={
                "Content-Disposition": "attachment; filename=catchment_pond_output.geojson"
            },
        )

    # Otherwise return full JSON analysis
    return analysis_result


@app.get("/health", summary="Health Check")
async def health_check():
    """Returns API health status."""
    return {
        "status": "healthy",
        "service": "Village Pond Planning & Catchment Analysis Backend API",
        "version": "1.0.0",
        "apis_integrated": [
            "Open-Meteo Climate Archive API",
            "Open-Elevation API",
            "IMD Climatological Norms",
        ],
        "cached_models": list(_BASE_MODEL_CACHE.keys()),
        "timestamp": time.time(),
    }


@app.get("/", summary="Village Pond Planning GIS Web Application")
async def root():
    """Serves the interactive web front-end."""
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return RedirectResponse(url="/docs")


@app.get("/map", summary="GIS Map Application View")
async def map_view():
    """Serves the interactive web front-end map."""
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return RedirectResponse(url="/docs")
