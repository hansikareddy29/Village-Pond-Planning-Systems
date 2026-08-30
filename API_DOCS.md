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
| `POST` | `/analyzeContour` | Analyze Contour Map & Delineate Catchment | Uploads KML/KMZ, generates DEM, delineates catchment, identifies optimal pond site, and returns structured JSON & GeoJSON. |
| `GET` | `/health` | Health Check | Verifies service status and version. |
| `GET` | `/` | Root Redirect | Redirects to interactive OpenAPI specification docs (`/docs`). |

---

## 1. POST `/analyzeContour`

### Request Headers
- `Content-Type: multipart/form-data`

### Request Parameters (Form-Data)

| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `file` | `File` | No | `contours_1m.kml` | The contour map file (`.kml`, `.kmz`, or `.xml`). Defaults to sample if omitted. |
| `grid_resolution_m` | `float` | No | `10.0` | Digital Elevation Model grid resolution in meters (e.g. `5.0` to `25.0`). |
| `rainfall_annual_mm` | `float` | No | `1000.0` | Average annual precipitation in mm for water yield calculation. |
| `runoff_coefficient` | `float` | No | `0.35` | Rational runoff coefficient $C$ (typically `0.2` to `0.5` for rural/agricultural soil). |
| `pond_depth_m` | `float` | No | `3.0` | Target pond depth in meters (used for sizing and excavation estimations). |
| `num_candidate_sites`| `int` | No | `5` | Number of top candidate pond locations to evaluate and return. |

---

### Response Format (`application/json`)

#### Status `200 OK`
```json
{
  "success": true,
  "message": "Contour map terrain analysis and catchment delineation completed successfully.",
  "execution_time_seconds": 1.39,
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
      "max_elevation": 298.0,
      "elevation_range": 31.0,
      "center_lon": 81.297026,
      "center_lat": 21.251702
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
      "latitude": 21.251178,
      "longitude": 81.295404,
      "elevation_m": 278.0
    },
    "utm_coordinates": {
      "easting": 530649.5,
      "northing": 2349975.3,
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
      "depression_depth_m": 4.02,
      "topographic_wetness_index": 13.92,
      "elevation_m": 278.0
    },
    "catchment_area_ha": 161.18,
    "catchment_area_sq_m": 1611800.0,
    "selection_rationale": "Substantial upstream drainage (161.2 ha); Located in a natural topographic bowl (4.0m depth) reducing excavation; very gentle bed slope (0.4%) for stable embankment."
  },
  "catchment_summary": {
    "area_sq_meters": 1611800.0,
    "area_hectares": 161.18,
    "area_acres": 398.284,
    "perimeter_meters": 8360.0,
    "min_elevation_m": 276.0,
    "max_elevation_m": 297.82,
    "mean_elevation_m": 286.76,
    "elevation_range_m": 21.82,
    "average_slope_percent": 5.26,
    "average_slope_degrees": 3.0,
    "centroid_wgs84": {
      "longitude": 81.300582,
      "latitude": 21.252514
    },
    "annual_rainfall_mm": 1000.0,
    "runoff_coefficient": 0.35,
    "estimated_annual_runoff_m3": 564130.0,
    "estimated_annual_runoff_liters": 564130000.0,
    "estimated_annual_runoff_million_liters": 564.13,
    "estimated_peak_discharge_m3_per_sec": 7.84
  },
  "pond_design_recommendations": {
    "recommended_depth_m": 3.0,
    "recommended_surface_area_sq_m": 22222.2,
    "recommended_surface_area_hectares": 2.222,
    "estimated_dimensions_m": {
      "length_m": 182.6,
      "width_m": 121.7,
      "side_slope": "1.5:1 (Horizontal:Vertical)"
    },
    "recommended_storage_capacity_m3": 50000.0,
    "storage_capacity_liters": 50000000.0,
    "storage_capacity_million_liters": 50.0,
    "estimated_excavation_volume_m3": 8333.3,
    "excavation_savings_from_depression_percent": 83.3,
    "recommended_bund_height_m": 1.1,
    "recommended_freeboard_m": 0.6,
    "utilization_potential": {
      "supplemental_irrigation_ha": 12.5,
      "family_water_supply_days": 66666,
      "estimated_annual_refill_cycles": 5.0
    },
    "construction_notes": [
      "Clay puddle lining or 300-500 micron LDPE geomembrane recommended if soil permeability > 10^-5 cm/s.",
      "Inlet silt trap / sediment basin recommended to capture runoff sediment before entering main storage.",
      "Earthen surplus weir / emergency spillway required with 0.6m freeboard above maximum water level."
    ]
  },
  "candidate_pond_sites": [
    {
      "site_id": "pond_site_1",
      "rank": 1,
      "coordinates": { "longitude": 81.295404, "latitude": 21.251178, "elevation_m": 278.0 },
      "utm_coordinates": { "easting": 530649.5, "northing": 2349975.3, "epsg": 32644, "zone": 44 },
      "suitability_score": 99.5,
      "criteria_breakdown": { "catchment_score": 100.0, "depression_score": 100.0, "slope_stability_score": 97.5, "wetness_index_score": 99.2 },
      "local_terrain": { "slope_percent": 0.38, "depression_depth_m": 4.02, "topographic_wetness_index": 13.92, "elevation_m": 278.0 },
      "catchment_area_ha": 161.18,
      "catchment_area_sq_m": 1611800.0,
      "selection_rationale": "Substantial upstream drainage (161.2 ha); Located in a natural topographic bowl (4.0m depth) reducing excavation; very gentle bed slope (0.4%) for stable embankment."
    }
  ],
  "geojson": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "properties": { "name": "Catchment Boundary", "perimeter_m": 8360.0 },
        "geometry": { "type": "Polygon", "coordinates": [...] }
      },
      {
        "type": "Feature",
        "properties": { "name": "Drainage / Stream Network", "threshold_cells": 100.0 },
        "geometry": { "type": "MultiLineString", "coordinates": [...] }
      },
      {
        "type": "Feature",
        "properties": {
          "name": "Recommended Pond Site (Rank 1)",
          "site_id": "pond_site_1",
          "suitability_score": 99.5,
          "elevation_m": 278.0,
          "catchment_area_ha": 161.18,
          "is_primary": true
        },
        "geometry": { "type": "Point", "coordinates": [81.295404, 21.251178] }
      }
    ]
  }
}
```

---

## 2. Invocation Examples

### cURL
```bash
curl -X POST "http://localhost:8000/analyzeContour" \
  -F "file=@contours_1m.kml" \
  -F "grid_resolution_m=10.0" \
  -F "rainfall_annual_mm=1000.0" \
  -F "runoff_coefficient=0.35" \
  -F "pond_depth_m=3.0"
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
