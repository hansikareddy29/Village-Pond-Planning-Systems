# Village Pond Planning & Catchment Analysis — API Documentation

This document provides the complete REST API specification for the Village Pond Planning & Catchment Analysis backend service.

---

## Base URLs
- **API Base URL**: `http://localhost:8000`
- **Interactive OpenAPI (Swagger) UI**: `http://localhost:8000/docs`
- **Interactive Redoc UI**: `http://localhost:8000/redoc`
- **Health Check Endpoint**: `http://localhost:8000/health`

---

## Endpoints Overview

| Method | Path | Summary | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/analyzeContour` | Analyze Contour Map & Delineate Catchment | Uploads KML/KMZ, generates DEM, performs graph-based hydrological analysis, identifies optimal pond site, and returns structured JSON or direct GeoJSON. |
| `GET` | `/health` | Health Check | Verifies service status and version. |
| `GET` | `/` | Root Redirect | Redirects to interactive OpenAPI specification docs (`/docs`). |

---

## 1. POST `/analyzeContour`

### Request Headers
- `Content-Type: multipart/form-data`

### Request Parameters (Form-Data)

| Parameter | Type | Required | Default | Validation Rules | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `file` | `File` | No | `contours_1m.kml` | Valid KML or KMZ archive | The contour map file. Defaults to sample if omitted. |
| `format` | `string` | No | `json` | `'json'` or `'geojson'` | Output format: complete JSON analysis or direct GeoJSON file download. |
| `grid_resolution_m` | `float` | No | `10.0` | `> 0.0` | Digital Elevation Model grid resolution in meters. |
| `rainfall_annual_mm` | `float` | No | `1000.0` | `>= 0.0` | Average annual precipitation in mm for water yield calculation. |
| `runoff_coefficient` | `float` | No | `0.35` | `0.0 < C <= 1.0` | Rational runoff coefficient $C$ for rural/agricultural soil. |
| `pond_depth_m` | `float` | No | `3.0` | `> 0.0` | Target pond depth in meters for sizing and excavation estimations. |
| `num_candidate_sites`| `int` | No | `5` | `>= 1` | Number of top candidate pond locations to evaluate and return. |

---

### Response Format (`application/json`)

#### Status `200 OK`
```json
{
  "success": true,
  "message": "Contour map terrain analysis and catchment delineation completed successfully.",
  "execution_time_seconds": 1.45,
  "metadata": {
    "filename": "contours_1m.kml",
    "num_contours_extracted": 1355,
    "total_points_sampled": 160468,
    "contour_interval_m": 1.0,
    "utm_zone": 44,
    "utm_epsg": 32644,
    "bounds_wgs84": {
      "min_lon": 81.281404,
      "max_lon": 81.312647,
      "min_lat": 21.239822,
      "max_lat": 21.263581,
      "min_elevation": 267.0,
      "max_elevation": 298.0
    }
  },
  "terrain_summary": {
    "min_elevation_m": 267.0,
    "max_elevation_m": 297.91,
    "mean_elevation_m": 283.83,
    "relief_m": 30.91,
    "mean_slope_percent": 5.56,
    "mean_slope_degrees": 3.18,
    "grid_resolution_m": 10.0,
    "grid_rows": 267,
    "grid_cols": 329,
    "total_grid_cells": 87843
  },
  "recommended_pond_location": {
    "site_id": "pond_site_1",
    "rank": 1,
    "coordinates": {
      "latitude": 21.243691,
      "longitude": 81.288354,
      "elevation_m": 271.0
    },
    "utm_coordinates": {
      "easting": 529919.5,
      "northing": 2349145.3,
      "epsg": 32644,
      "zone": 44
    },
    "suitability_score": 99.5,
    "criteria_breakdown": {
      "catchment_score": 100.0,
      "depression_score": 100.0,
      "slope_stability_score": 97.5,
      "wetness_index_score": 99.2
    },
    "local_terrain": {
      "slope_percent": 0.38,
      "depression_depth_m": 3.0,
      "topographic_wetness_index": 12.8,
      "elevation_m": 271.0
    },
    "catchment_area_ha": 43.91,
    "catchment_area_sq_m": 439100.0,
    "selection_rationale": "Substantial upstream drainage (43.9 ha); Located in a natural topographic bowl (3.0m depth) reducing excavation; very gentle bed slope (0.4%) for stable embankment."
  },
  "catchment_summary": {
    "area_sq_meters": 439100.0,
    "area_hectares": 43.91,
    "area_acres": 108.5,
    "perimeter_meters": 4840.0,
    "min_elevation_m": 269.53,
    "max_elevation_m": 290.87,
    "mean_elevation_m": 281.78,
    "elevation_range_m": 21.34,
    "average_slope_percent": 5.72,
    "average_slope_degrees": 3.27,
    "centroid_wgs84": {
      "longitude": 81.2915,
      "latitude": 21.2462
    },
    "annual_rainfall_mm": 1000.0,
    "runoff_coefficient": 0.35,
    "estimated_annual_runoff_m3": 153685.0,
    "estimated_annual_runoff_liters": 153685000.0,
    "estimated_annual_runoff_million_liters": 153.69,
    "estimated_peak_discharge_m3_per_sec": 2.13
  },
  "pond_design_recommendations": {
    "recommended_depth_m": 3.0,
    "recommended_surface_area_sq_m": 13660.9,
    "recommended_surface_area_hectares": 1.366,
    "estimated_dimensions_m": {
      "length_m": 143.1,
      "width_m": 95.4,
      "side_slope": "1.5:1 (Horizontal:Vertical)"
    },
    "recommended_storage_capacity_m3": 30737.0,
    "storage_capacity_liters": 30737000.0,
    "storage_capacity_million_liters": 30.74,
    "estimated_excavation_volume_m3": 5122.8,
    "excavation_savings_from_depression_percent": 83.3,
    "recommended_bund_height_m": 1.1,
    "recommended_freeboard_m": 0.6,
    "utilization_potential": {
      "supplemental_irrigation_ha": 7.68,
      "family_water_supply_days": 40982,
      "estimated_annual_refill_cycles": 5.0
    }
  },
  "candidate_pond_sites": [
    {
      "site_id": "pond_site_1",
      "rank": 1,
      "coordinates": { "longitude": 81.288354, "latitude": 21.243691, "elevation_m": 271.0 },
      "suitability_score": 99.5,
      "catchment_area_ha": 43.91
    }
  ],
  "geojson": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "properties": { "name": "Catchment Boundary", "perimeter_m": 4840.0 },
        "geometry": { "type": "MultiPolygon", "coordinates": [...] }
      },
      {
        "type": "Feature",
        "properties": { "name": "Drainage / Stream Network" },
        "geometry": { "type": "MultiLineString", "coordinates": [...] }
      },
      {
        "type": "Feature",
        "properties": { "name": "Recommended Pond Site (Rank 1)" },
        "geometry": { "type": "Point", "coordinates": [81.288354, 21.243691] }
      }
    ]
  }
}
```

---

## 2. Invocation Examples

### cURL (JSON Response)
```bash
curl -X POST "http://localhost:8000/analyzeContour" \
  -F "file=@contours_1m.kml" \
  -F "grid_resolution_m=10.0" \
  -F "rainfall_annual_mm=1000.0" \
  -F "runoff_coefficient=0.35" \
  -F "pond_depth_m=3.0"
```

### cURL (Direct GeoJSON File Download)
```bash
curl -X POST "http://localhost:8000/analyzeContour" \
  -F "file=@contours_1m.kml" \
  -F "format=geojson" \
  -o catchment.geojson
```

### Python (`requests`)
```python
import requests

url = "http://localhost:8000/analyzeContour"
with open("contours_1m.kml", "rb") as f:
    response = requests.post(url, files={"file": f})

result = response.json()
print("Optimal Pond Location:", result["recommended_pond_location"]["coordinates"])
print("Catchment Area (ha):", result["catchment_summary"]["area_hectares"])
print("Annual Runoff (ML):", result["catchment_summary"]["estimated_annual_runoff_million_liters"])
```
