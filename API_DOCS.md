# Village Pond Planning & Catchment Analysis — API Documentation

This document provides complete REST API specifications for the Village Pond Planning & Catchment Analysis backend service.

---

## Base URLs
- **Local Development**: `http://localhost:8000`
- **Interactive OpenAPI (Swagger) UI**: `http://localhost:8000/docs`
- **Interactive Redoc UI**: `http://localhost:8000/redoc`
- **Interactive Web Visualizer**: `http://localhost:8000/`

---

## Endpoints Overview

| Method | Path | Summary | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/analyzeContour` | Analyze Contour Map | Uploads KML/KMZ, generates DEM, delineates catchment, and finds optimal pond site. |
| `POST` | `/findCatchment` | Find Catchment (Alias) | Direct alias for `/analyzeContour`. |
| `GET` | `/health` | Health Check | Verifies service status and version. |
| `GET` | `/` | Web Dashboard | Serves the interactive Leaflet map dashboard. |

---

## 1. POST `/analyzeContour` (and `/findCatchment`)

### Request Headers
- `Content-Type: multipart/form-data`

### Request Parameters (Form-Data)

| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `file` | `File` | **Yes** | — | The contour map file (`.kml`, `.kmz`, or `.xml`). |
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
      "longitude": 81.295404,
      "latitude": 21.251178,
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
    "perimeter_meters": 6832.0,
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
        "properties": { "name": "Catchment Boundary", "perimeter_m": 6832.0 },
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
  -F "pond_depth_m=3.0" \
  -F "num_candidate_sites=5"
```

### Python (`requests`)
```python
import requests

url = "http://localhost:8000/analyzeContour"
files = {"file": open("contours_1m.kml", "rb")}
data = {
    "grid_resolution_m": 10.0,
    "rainfall_annual_mm": 1000.0,
    "runoff_coefficient": 0.35,
    "pond_depth_m": 3.0,
    "num_candidate_sites": 5
}

response = requests.post(url, files=files, data=data)
result = response.json()

print(f"Optimal Pond Site: {result['recommended_pond_location']['coordinates']}")
print(f"Catchment Area: {result['catchment_summary']['area_hectares']} ha")
print(f"Annual Runoff Yield: {result['catchment_summary']['estimated_annual_runoff_million_liters']} ML")
```

### JavaScript / Fetch
```javascript
const formData = new FormData();
formData.append('file', fileBlob, 'contours_1m.kml');
formData.append('grid_resolution_m', 10.0);
formData.append('rainfall_annual_mm', 1000.0);
formData.append('runoff_coefficient', 0.35);

const response = await fetch('http://localhost:8000/analyzeContour', {
  method: 'POST',
  body: formData
});
const data = await response.json();
console.log(data);
```

---

## 3. Error Handling

| Status Code | Reason | Example Response |
| :--- | :--- | :--- |
| `400 Bad Request` | Missing file, empty file, or corrupted KML syntax. | `{"detail": "KML/KMZ Parsing Error: No valid contour lines found"}` |
| `422 Unprocessable Entity`| Missing required parameters or invalid parameter types. | `{"detail": [{"loc": ["body", "file"], "msg": "Field required"}]}` |
| `500 Internal Server Error`| Siting failure on flat or degenerate grid. | `{"detail": "No viable pond candidate locations identified."}` |

