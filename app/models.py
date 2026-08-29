"""
Pydantic Models and GeoJSON Schemas for API Requests & Responses
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class Coordinates(BaseModel):
    longitude: float = Field(..., description="WGS84 Longitude in decimal degrees")
    latitude: float = Field(..., description="WGS84 Latitude in decimal degrees")
    elevation_m: float = Field(..., description="Surface elevation in meters above sea level")


class UTMCoordinates(BaseModel):
    easting: float = Field(..., description="UTM Easting in meters")
    northing: float = Field(..., description="UTM Northing in meters")
    epsg: int = Field(..., description="Projected coordinate system EPSG code")
    zone: int = Field(..., description="UTM Zone number")


class CriteriaBreakdown(BaseModel):
    catchment_score: float = Field(..., description="Contributing upstream area score (0-100)")
    depression_score: float = Field(..., description="Natural topographic depression score (0-100)")
    slope_stability_score: float = Field(..., description="Bed slope stability score (0-100)")
    wetness_index_score: float = Field(..., description="Topographic wetness index score (0-100)")


class LocalTerrain(BaseModel):
    slope_percent: float = Field(..., description="Local slope gradient in percent")
    depression_depth_m: float = Field(..., description="Depth of natural hollow/depression in meters")
    topographic_wetness_index: float = Field(..., description="Topographic Wetness Index (TWI)")
    elevation_m: float = Field(..., description="Elevation at pond bottom in meters")


class CandidateSite(BaseModel):
    site_id: str
    rank: int
    coordinates: Coordinates
    utm_coordinates: UTMCoordinates
    suitability_score: float = Field(..., description="Composite suitability score (0-100)")
    criteria_breakdown: CriteriaBreakdown
    local_terrain: LocalTerrain
    catchment_area_ha: float
    catchment_area_sq_m: float
    selection_rationale: str


class TerrainSummary(BaseModel):
    min_elevation_m: float
    max_elevation_m: float
    mean_elevation_m: float
    relief_m: float
    mean_slope_percent: float
    mean_slope_degrees: float
    grid_resolution_m: float
    grid_rows: int
    grid_cols: int
    total_grid_cells: int


class CatchmentSummary(BaseModel):
    area_sq_meters: float
    area_hectares: float
    area_acres: float
    perimeter_meters: float
    min_elevation_m: float
    max_elevation_m: float
    mean_elevation_m: float
    elevation_range_m: float
    average_slope_percent: float
    average_slope_degrees: float
    centroid_wgs84: Dict[str, float]
    annual_rainfall_mm: float
    runoff_coefficient: float
    estimated_annual_runoff_m3: float
    estimated_annual_runoff_liters: float
    estimated_annual_runoff_million_liters: float
    estimated_peak_discharge_m3_per_sec: float


class Dimensions(BaseModel):
    length_m: float
    width_m: float
    side_slope: str


class UtilizationPotential(BaseModel):
    supplemental_irrigation_ha: float
    family_water_supply_days: int
    estimated_annual_refill_cycles: float


class PondDesignRecommendations(BaseModel):
    recommended_depth_m: float
    recommended_surface_area_sq_m: float
    recommended_surface_area_hectares: float
    estimated_dimensions_m: Dimensions
    recommended_storage_capacity_m3: float
    storage_capacity_liters: float
    storage_capacity_million_liters: float
    estimated_excavation_volume_m3: float
    excavation_savings_from_depression_percent: float
    recommended_bund_height_m: float
    recommended_freeboard_m: float
    utilization_potential: UtilizationPotential
    construction_notes: List[str]


class AnalysisMetadata(BaseModel):
    filename: Optional[str]
    num_contours_extracted: int
    total_points_sampled: int
    contour_interval_m: float
    utm_zone: int
    utm_epsg: int
    bounds_wgs84: Dict[str, float]


class AnalysisResponse(BaseModel):
    success: bool
    message: str
    execution_time_seconds: float
    metadata: AnalysisMetadata
    terrain_summary: TerrainSummary
    recommended_pond_location: CandidateSite
    catchment_summary: CatchmentSummary
    pond_design_recommendations: PondDesignRecommendations
    candidate_pond_sites: List[CandidateSite]
    geojson: Dict[str, Any]
