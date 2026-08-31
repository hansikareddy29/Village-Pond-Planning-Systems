"""
FastAPI Backend Application for Village Pond Planning & Catchment Analysis
Provides backend REST API routes:
- POST /analyzeContour (Supports format='json' or format='geojson')
- GET /health
- GET / (Redirects to /docs OpenAPI Specification)
"""

import time
import os
import json
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response

from app.kml_parser import KMLParser, KMLParseError
from app.dem_generator import DEMGenerator
from app.hydrology import HydrologyEngine
from app.pond_siting import PondSitingEngine
from app.external_apis import RainfallAPIService, ElevationAPIService
from app.models import AnalysisResponse

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

# Shared Hydrology & Geospatial Engines
kml_parser = KMLParser()
dem_generator = DEMGenerator(default_resolution_m=10.0)
hydrology_engine = HydrologyEngine()
pond_siting_engine = PondSitingEngine()


def _process_contour_map(
    file_bytes: bytes,
    filename: Optional[str] = None,
    grid_resolution_m: float = 10.0,
    rainfall_annual_mm: float = 1000.0,
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

    # A. Full Natural Depression Basin (5.59 ha - Full Reservoir Zone)
    if top_site.get("continuous_basin_geometry"):
        geojson_features.append(
            {
                "type": "Feature",
                "properties": {
                    "name": "Full Natural Depression Basin (5.59 ha - Max Reservoir Zone)",
                    "feature_type": "full_natural_basin",
                    "site_id": top_site["site_id"],
                    "area_hectares": top_site.get("continuous_basin_footprint_ha"),
                    "depression_depth_m": top_site["local_terrain"][
                        "depression_depth_m"
                    ],
                    "elevation_m": top_site["coordinates"]["elevation_m"],
                    "fill": "#00E676",
                    "fill-opacity": 0.22,
                    "stroke": "#00B0FF",
                    "stroke-width": 3,
                    "stroke-dasharray": "6 6",
                    "style": {
                        "color": "#00B0FF",
                        "weight": 3,
                        "dashArray": "6, 6",
                        "fillColor": "#00E676",
                        "fillOpacity": 0.22,
                    },
                },
                "geometry": top_site["continuous_basin_geometry"],
            }
        )

    # B. Compact Core Village Farm Pond (1.35 ha - Deep Core Construction Area)
    if top_site.get("compact_pond_geometry"):
        geojson_features.append(
            {
                "type": "Feature",
                "properties": {
                    "name": "Compact Core Village Farm Pond (1.35 ha - Core Excavation Footprint)",
                    "feature_type": "compact_pond_footprint",
                    "site_id": top_site["site_id"],
                    "area_hectares": top_site.get("compact_pond_footprint_ha"),
                    "depression_depth_m": top_site["local_terrain"][
                        "depression_depth_m"
                    ],
                    "elevation_m": top_site["coordinates"]["elevation_m"],
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
                "geometry": top_site["compact_pond_geometry"],
            }
        )

    # B. Drainage / Stream Network
    geojson_features.append(hydro_results["streams"])

    # C. Recommended Pond Storage Location Feature
    pond_feat_props = {
        "name": "Recommended Pond Storage Location (Rank 1)",
        "feature_type": "pond_candidate",
        "site_id": top_site["site_id"],
        "candidate_type": top_site["candidate_type"],
        "suitability_score": top_site["suitability_score"],
        "elevation_m": top_site["coordinates"]["elevation_m"],
        "local_slope_percent": top_site["local_terrain"]["slope_percent"],
        "depression_depth_m": top_site["local_terrain"]["depression_depth_m"],
        "recommended_capacity_m3": pond_design["recommended_storage_capacity_m3"],
        "selection_rationale": top_site["selection_rationale"],
        "marker_color": "#00E676",
        "is_primary": True,
    }
    if "elevation_api_m" in top_site["coordinates"]:
        pond_feat_props["elevation_api_m"] = top_site["coordinates"]["elevation_api_m"]

    geojson_features.append(
        {
            "type": "Feature",
            "properties": pond_feat_props,
            "geometry": {
                "type": "Point",
                "coordinates": [
                    top_site["coordinates"]["longitude"],
                    top_site["coordinates"]["latitude"],
                ],
            },
        }
    )

    # D. Associated Hydrological Pour Point Feature (on the drainage stream)
    geojson_features.append(
        {
            "type": "Feature",
            "properties": {
                "name": "Associated Hydrological Pour Point (Rank 1)",
                "feature_type": "pour_point",
                "site_id": top_site["site_id"],
                "elevation_m": top_site["associated_pour_point"]["coordinates"][
                    "elevation_m"
                ],
                "catchment_area_ha": catchment_info["area_hectares"],
                "drainage_flow_acc_cells": top_site["associated_pour_point"][
                    "flow_accumulation_cells"
                ],
                "marker_color": "#2979FF",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [
                    top_site["associated_pour_point"]["coordinates"]["longitude"],
                    top_site["associated_pour_point"]["coordinates"]["latitude"],
                ],
            },
        }
    )

    # E. Alternative Candidate Sites
    for site in candidate_sites[1:]:
        alt_props = {
            "name": f"Alternative Pond Site ({site['site_id']})",
            "feature_type": "alternative_candidate",
            "site_id": site["site_id"],
            "rank": site["rank"],
            "candidate_type": site["candidate_type"],
            "suitability_score": site["suitability_score"],
            "elevation_m": site["coordinates"]["elevation_m"],
            "catchment_area_ha": site["catchment_area_ha"],
            "marker_color": "#FF9100",
            "is_primary": False,
        }
        if "elevation_api_m" in site["coordinates"]:
            alt_props["elevation_api_m"] = site["coordinates"]["elevation_api_m"]

        geojson_features.append(
            {
                "type": "Feature",
                "properties": alt_props,
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        site["coordinates"]["longitude"],
                        site["coordinates"]["latitude"],
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


@app.post(
    "/analyzeContour",
    summary="Analyze Contour Map & Delineate Catchment",
    description="Accepts a KML/KMZ contour map upload. Dynamically queries Open-Meteo Rainfall API for the coordinates and returns structured JSON analysis or direct GeoJSON.",
)
async def analyze_contour(
    file: Optional[UploadFile] = File(
        None,
        description="KML or KMZ contour map file (optional, defaults to sample contours_1m.kml)",
    ),
    format: str = Form(
        "json",
        description="Output format: 'json' (complete analysis report) or 'geojson' (pure GeoJSON FeatureCollection file)",
    ),
    grid_resolution_m: float = Form(
        10.0,
        description="Spatial DEM grid cell resolution in meters (e.g. 5.0 to 25.0)",
    ),
    rainfall_annual_mm: float = Form(
        1000.0,
        description="Annual precipitation in mm (auto-fetched from Open-Meteo API for file coordinates if left default)",
    ),
    runoff_coefficient: float = Form(
        0.35, description="Catchment runoff coefficient C (0.0 to 1.0]"
    ),
    pond_depth_m: float = Form(
        3.0, description="Target pond excavation depth in meters"
    ),
    num_candidate_sites: int = Form(
        5, description="Number of top candidate pond locations to return"
    ),
):
    # Parameter Validations
    if grid_resolution_m <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="grid_resolution_m must be strictly greater than 0.",
        )
    if not (0 < runoff_coefficient <= 1.0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="runoff_coefficient must be between 0.0 (exclusive) and 1.0 (inclusive).",
        )
    if rainfall_annual_mm < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="rainfall_annual_mm cannot be negative.",
        )
    if pond_depth_m <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="pond_depth_m must be strictly greater than 0.",
        )
    if num_candidate_sites < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="num_candidate_sites must be at least 1.",
        )

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
                "Content-Disposition": f"attachment; filename=catchment_pond_output.geojson"
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
        "timestamp": time.time(),
    }


@app.get("/", summary="Root Endpoint (OpenAPI Redirect)")
async def root():
    """Redirects to interactive OpenAPI specification docs."""
    return RedirectResponse(url="/docs")
