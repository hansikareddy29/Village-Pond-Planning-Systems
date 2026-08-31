"""
Pydantic Models and GeoJSON Schemas for API Requests & Responses
Clearly separates the physical pond storage location from the hydrological pour point.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class Coordinates(BaseModel):
    longitude: float = Field(..., description="WGS84 Longitude in decimal degrees")
    latitude: float = Field(..., description="WGS84 Latitude in decimal degrees")
    elevation_m: float = Field(
        ..., description="Surface elevation in meters above sea level"
    )
    elevation_api_m: Optional[float] = Field(
        None, description="External Elevation API verified elevation in meters"
    )
    elevation_api_diff_m: Optional[float] = Field(
        None, description="Difference between API elevation and TIN elevation in meters"
    )


class UTMCoordinates(BaseModel):
    easting: float = Field(..., description="UTM Easting in meters")
    northing: float = Field(..., description="UTM Northing in meters")
    epsg: int = Field(..., description="Projected coordinate system EPSG code")
    zone: int = Field(..., description="UTM Zone number")


class GridIndex(BaseModel):
    row: int = Field(..., description="DEM grid row index")
    col: int = Field(..., description="DEM grid column index")


class PourPoint(BaseModel):
    coordinates: Coordinates = Field(
        ..., description="Downstream drainage outlet coordinates on the stream channel"
    )
    utm_coordinates: UTMCoordinates
    grid_index: GridIndex
    flow_accumulation_cells: float = Field(
        ...,
        description="Total upstream contributing DEM cells accumulating at this pour point",
    )
    drainage_area_ha: float = Field(
        ..., description="Upstream contributing drainage area in hectares"
    )


class CriteriaBreakdown(BaseModel):
    catchment_score: float = Field(
        ..., description="Contributing upstream area score (0-100)"
    )
    depression_score: float = Field(
        ..., description="Natural topographic depression score (0-100)"
    )
    slope_stability_score: float = Field(
        ..., description="Bed slope stability score (0-100)"
    )
    wetness_index_score: float = Field(
        ..., description="Topographic wetness index score (0-100)"
    )


class LocalTerrain(BaseModel):
    slope_percent: float = Field(
        ..., description="Local slope gradient at the pond location in percent"
    )
    depression_depth_m: float = Field(
        ...,
        description="Depth of natural hollow/depression at the pond location in meters",
    )
    topographic_wetness_index: float = Field(
        ..., description="Topographic Wetness Index (TWI)"
    )
    elevation_m: float = Field(..., description="Elevation at pond bottom in meters")


class CandidateSite(BaseModel):
    site_id: str
    rank: int
    candidate_type: str = Field(
        ...,
        description="Classification of candidate: 'natural_depression', 'stream_confluence_basin', or 'valley_storage'",
    )
    coordinates: Coordinates = Field(
        ..., description="Physical pond storage/construction location center"
    )
    utm_coordinates: UTMCoordinates
    grid_index: GridIndex
    associated_pour_point: PourPoint = Field(
        ...,
        description="Downstream hydrological pour point on the drainage path from which the catchment is delineated",
    )
    suitability_score: float = Field(
        ..., description="Composite suitability score (0-100)"
    )
    criteria_breakdown: CriteriaBreakdown
    local_terrain: LocalTerrain
    catchment_area_ha: float
    catchment_area_sq_m: float
    continuous_basin_footprint_ha: Optional[float] = Field(
        None,
        description="Actual localized continuous deep depression basin area in hectares",
    )
    continuous_basin_geometry: Optional[Dict[str, Any]] = Field(
        None,
        description="GeoJSON geometry of the localized continuous deep depression basin",
    )
    compact_pond_footprint_ha: Optional[float] = Field(
        None,
        description="Compact core village farm pond construction footprint area in hectares",
    )
    compact_pond_geometry: Optional[Dict[str, Any]] = Field(
        None,
        description="GeoJSON geometry of the compact core village farm pond construction footprint",
    )
    estimated_annual_water_yield_m3: Optional[float] = None
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
    elevation_source: Optional[str] = "KML_3D_Contour_TIN_Interpolation"


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
    rainfall_source: Optional[str] = None
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
    rainfall_service: Optional[Dict[str, Any]] = None
    elevation_service: Optional[Dict[str, Any]] = None


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
