"""
FastAPI Backend Application for Village Pond Planning & Catchment Analysis
Provides endpoints:
- POST /analyzeContour
- POST /findCatchment
- POST /analyzeSample
- GET /health
- GET / (Interactive Web Visualizer Dashboard)
"""

import time
import os
import traceback
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, Query, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.kml_parser import KMLParser, KMLParseError
from app.dem_generator import DEMGenerator
from app.hydrology import HydrologyEngine
from app.pond_siting import PondSitingEngine
from app.models import AnalysisResponse


# Initialize FastAPI App
app = FastAPI(
    title="Village Pond Planning & Catchment Analysis API",
    description="Automated terrain modeling, optimal pond location identification, and hydrological catchment delineation from KML/KMZ contour maps.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Enable CORS for cross-origin frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static directory for frontend visualizer
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Shared Engine Instances
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
    num_candidate_sites: int = 5
) -> dict:
    """Core analysis workflow executing DEM generation, hydrological routing, and pond siting."""
    t_start = time.time()

    # 1. Parse KML/KMZ
    try:
        parsed_data = kml_parser.parse(file_bytes, filename=filename)
    except KMLParseError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"KML/KMZ Parsing Error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to read file: {str(e)}"
        )

    # 2. Generate DEM Grid
    try:
        dem = dem_generator.generate_dem(parsed_data, resolution_m=grid_resolution_m)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DEM Surface Generation Error: {str(e)}"
        )

    # 3. Hydrological Analysis
    try:
        hydro_results = hydrology_engine.analyze(dem)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Hydrological Analysis Error: {str(e)}"
        )

    # 4. Pond Candidate Siting & MCDA Ranking
    try:
        candidate_sites = pond_siting_engine.find_optimal_sites(
            dem=dem,
            hydro_results=hydro_results,
            num_candidates=num_candidate_sites
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pond Siting Optimization Error: {str(e)}"
        )

    if not candidate_sites:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No viable pond candidate locations could be identified for this terrain."
        )

    top_site = candidate_sites[0]

    # 5. Delineate Catchment Boundary for the Recommended Pond Site
    top_grid = (top_site['grid_index']['row'], top_site['grid_index']['col'])
    catchment_info = hydrology_engine.delineate_catchment(
        pour_point_grid=top_grid,
        flow_dir=hydro_results['flow_direction'],
        dem=dem
    )

    # 6. Estimate Runoff & Water Yield
    runoff_info = hydrology_engine.estimate_runoff(
        catchment_area_sq_m=catchment_info['area_sq_meters'],
        annual_rainfall_mm=rainfall_annual_mm,
        runoff_coefficient=runoff_coefficient
    )

    # 7. Sizing & Civil Engineering Recommendations
    pond_design = pond_siting_engine.compute_design_recommendations(
        catchment_area_sq_m=catchment_info['area_sq_meters'],
        annual_runoff_m3=runoff_info['estimated_annual_runoff_m3'],
        depression_depth_m=top_site['local_terrain']['depression_depth_m'],
        target_pond_depth_m=pond_depth_m
    )

    # 8. Assemble GeoJSON Feature Collection
    geojson_features = []

    # A. Catchment Boundary Polygon
    geojson_features.append(catchment_info['geojson'])

    # B. Streams / Drainage Network
    geojson_features.append(hydro_results['streams'])

    # C. Recommended Pond Site Point Feature
    geojson_features.append({
        "type": "Feature",
        "properties": {
            "name": f"Recommended Pond Site (Rank 1)",
            "site_id": top_site['site_id'],
            "suitability_score": top_site['suitability_score'],
            "elevation_m": top_site['coordinates']['elevation_m'],
            "catchment_area_ha": catchment_info['area_hectares'],
            "recommended_capacity_m3": pond_design['recommended_storage_capacity_m3'],
            "recommended_depth_m": pond_design['recommended_depth_m'],
            "selection_rationale": top_site['selection_rationale'],
            "marker_color": "#00E676",
            "is_primary": True
        },
        "geometry": {
            "type": "Point",
            "coordinates": [top_site['coordinates']['longitude'], top_site['coordinates']['latitude']]
        }
    })

    # D. Alternative Candidate Sites
    for site in candidate_sites[1:]:
        geojson_features.append({
            "type": "Feature",
            "properties": {
                "name": f"Alternative Pond Site ({site['site_id']})",
                "site_id": site['site_id'],
                "rank": site['rank'],
                "suitability_score": site['suitability_score'],
                "elevation_m": site['coordinates']['elevation_m'],
                "catchment_area_ha": site['catchment_area_ha'],
                "selection_rationale": site['selection_rationale'],
                "marker_color": "#FF9100",
                "is_primary": False
            },
            "geometry": {
                "type": "Point",
                "coordinates": [site['coordinates']['longitude'], site['coordinates']['latitude']]
            }
        })

    # E. Survey Boundary Polygon if present in KML
    if parsed_data.get('boundary_polygon'):
        b_pts = parsed_data['boundary_polygon']
        b_coords = [[pt[0], pt[1]] for pt in b_pts]
        if b_coords and b_coords[0] != b_coords[-1]:
            b_coords.append(b_coords[0])
        geojson_features.append({
            "type": "Feature",
            "properties": {
                "name": "Survey Boundary",
                "style": {"color": "#E91E63", "weight": 2, "dashArray": "5, 5"}
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [b_coords]
            }
        })

    geojson_collection = {
        "type": "FeatureCollection",
        "features": geojson_features
    }

    t_exec = round(time.time() - t_start, 3)

    # 9. Format Complete Response
    response = {
        "success": True,
        "message": "Contour map terrain analysis and catchment delineation completed successfully.",
        "execution_time_seconds": t_exec,
        "metadata": {
            "filename": filename or "uploaded_file.kml",
            "num_contours_extracted": parsed_data['num_contours'],
            "total_points_sampled": len(parsed_data['point_cloud']),
            "contour_interval_m": parsed_data['contour_interval'],
            "utm_zone": dem.utm_zone,
            "utm_epsg": dem.utm_epsg,
            "bounds_wgs84": parsed_data['bounds']
        },
        "terrain_summary": {
            "min_elevation_m": round(dem.stats['min_elevation'], 2),
            "max_elevation_m": round(dem.stats['max_elevation'], 2),
            "mean_elevation_m": round(dem.stats['mean_elevation'], 2),
            "relief_m": round(dem.stats['relief'], 2),
            "mean_slope_percent": round(dem.stats['mean_slope_percent'], 2),
            "mean_slope_degrees": round(dem.stats['mean_slope_degrees'], 2),
            "grid_resolution_m": dem.resolution_m,
            "grid_rows": dem.stats['grid_rows'],
            "grid_cols": dem.stats['grid_cols'],
            "total_grid_cells": dem.stats['total_grid_cells']
        },
        "recommended_pond_location": top_site,
        "catchment_summary": {
            "area_sq_meters": catchment_info['area_sq_meters'],
            "area_hectares": catchment_info['area_hectares'],
            "area_acres": catchment_info['area_acres'],
            "perimeter_meters": catchment_info['perimeter_meters'],
            "min_elevation_m": catchment_info['min_elevation_m'],
            "max_elevation_m": catchment_info['max_elevation_m'],
            "mean_elevation_m": catchment_info['mean_elevation_m'],
            "elevation_range_m": catchment_info['elevation_range_m'],
            "average_slope_percent": catchment_info['average_slope_percent'],
            "average_slope_degrees": catchment_info['average_slope_degrees'],
            "centroid_wgs84": catchment_info['centroid_wgs84'],
            "annual_rainfall_mm": runoff_info['annual_rainfall_mm'],
            "runoff_coefficient": runoff_info['runoff_coefficient'],
            "estimated_annual_runoff_m3": runoff_info['estimated_annual_runoff_m3'],
            "estimated_annual_runoff_liters": runoff_info['estimated_annual_runoff_liters'],
            "estimated_annual_runoff_million_liters": runoff_info['estimated_annual_runoff_million_liters'],
            "estimated_peak_discharge_m3_per_sec": runoff_info['estimated_peak_discharge_m3_per_sec']
        },
        "pond_design_recommendations": pond_design,
        "candidate_pond_sites": candidate_sites,
        "geojson": geojson_collection
    }

    return response


@app.post(
    "/analyzeContour",
    response_model=AnalysisResponse,
    summary="Analyze Contour Map & Estimate Catchment",
    description="Upload a KML/KMZ contour map to generate continuous DEM, delineate watershed catchment, identify optimal pond sites, and compute water storage recommendations."
)
async def analyze_contour(
    file: Optional[UploadFile] = File(None, description="KML or KMZ contour map file (optional, defaults to sample contours_1m.kml)"),
    grid_resolution_m: float = Form(10.0, description="Spatial DEM grid cell resolution in meters (e.g. 5.0 to 20.0)"),
    rainfall_annual_mm: float = Form(1000.0, description="Average annual precipitation in mm for water yield calculation"),
    runoff_coefficient: float = Form(0.35, description="Catchment runoff coefficient C (0.1 to 0.8)"),
    pond_depth_m: float = Form(3.0, description="Target pond excavation depth in meters"),
    num_candidate_sites: int = Form(5, description="Number of top candidate pond locations to return")
):
    if file is not None and file.filename:
        contents = await file.read()
        filename = file.filename
    else:
        # Fallback to local contours_1m.kml
        sample_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "contours_1m.kml")
        if not os.path.exists(sample_path):
            raise HTTPException(status_code=400, detail="No file uploaded and sample contours_1m.kml not found.")
        with open(sample_path, "rb") as f:
            contents = f.read()
        filename = "contours_1m.kml"

    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    
    return _process_contour_map(
        file_bytes=contents,
        filename=filename,
        grid_resolution_m=grid_resolution_m,
        rainfall_annual_mm=rainfall_annual_mm,
        runoff_coefficient=runoff_coefficient,
        pond_depth_m=pond_depth_m,
        num_candidate_sites=num_candidate_sites
    )


@app.post(
    "/findCatchment",
    response_model=AnalysisResponse,
    summary="Find Catchment and Pond Location (Alias)",
    description="Alias endpoint for POST /analyzeContour."
)
async def find_catchment(
    file: Optional[UploadFile] = File(None, description="KML or KMZ contour map file"),
    grid_resolution_m: float = Form(10.0, description="Spatial DEM grid cell resolution in meters"),
    rainfall_annual_mm: float = Form(1000.0, description="Average annual precipitation in mm"),
    runoff_coefficient: float = Form(0.35, description="Catchment runoff coefficient C"),
    pond_depth_m: float = Form(3.0, description="Target pond excavation depth in meters"),
    num_candidate_sites: int = Form(5, description="Number of top candidate pond locations to return")
):
    return await analyze_contour(
        file=file,
        grid_resolution_m=grid_resolution_m,
        rainfall_annual_mm=rainfall_annual_mm,
        runoff_coefficient=runoff_coefficient,
        pond_depth_m=pond_depth_m,
        num_candidate_sites=num_candidate_sites
    )


@app.post(
    "/analyzeSample",
    response_model=AnalysisResponse,
    summary="Analyze Provided Sample Map (1-Click Demo)",
    description="Analyzes the provided contours_1m.kml sample contour map."
)
async def analyze_sample(
    grid_resolution_m: float = Form(10.0),
    rainfall_annual_mm: float = Form(1000.0),
    runoff_coefficient: float = Form(0.35),
    pond_depth_m: float = Form(3.0),
    num_candidate_sites: int = Form(5)
):
    return await analyze_contour(
        file=None,
        grid_resolution_m=grid_resolution_m,
        rainfall_annual_mm=rainfall_annual_mm,
        runoff_coefficient=runoff_coefficient,
        pond_depth_m=pond_depth_m,
        num_candidate_sites=num_candidate_sites
    )


@app.get("/health", summary="Health Check")
async def health_check():
    """Returns API health status."""
    return {
        "status": "healthy",
        "service": "Village Pond Planning & Catchment Analysis API",
        "version": "1.0.0",
        "timestamp": time.time()
    }


@app.get("/", response_class=HTMLResponse, summary="Web Dashboard Visualizer")
async def serve_dashboard():
    """Serves the interactive Leaflet map dashboard."""
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return HTMLResponse("<h1>Village Pond Planning API</h1><p>Visit <a href='/docs'>/docs</a> for OpenAPI specification.</p>")
