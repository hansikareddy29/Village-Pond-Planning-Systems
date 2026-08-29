# Village Pond Planning & Catchment Analysis Backend System

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg?logo=python&logoColor=white)](https://python.org)
[![Tests](https://img.shields.io/badge/Tests-14%20Passed-brightgreen.svg)]()
[![License](https://img.shields.io/badge/License-MIT-blue.svg)]()

An automated, generalized backend API and geospatial hydrology engine for terrain analysis, optimal pond location siting, and watershed catchment delineation from KML/KMZ contour maps.

---

## 🌟 Key Features

- **Multi-Format Ingestion**: Ingests uncompressed `.kml` and zipped `.kmz` files, parsing 3D contour lines and elevation tags.
- **Dynamic Metric Projection**: Automatically detects the appropriate UTM coordinate system (e.g. UTM Zone 44N) and transforms WGS84 coordinates into exact metric space.
- **DEM Surface Generation**: Reconstructs continuous Digital Elevation Model grids from sparse contours using Delaunay Triangulation and Barycentric TIN surface modeling.
- **D8 Hydrological Routing**: Implements Priority-Flood depression filling, D8 steepest descent flow directions, and vectorized flow accumulation in $O(N)$ topological order.
- **Topographic Depression Analysis**: Identifies natural sinks, computes spillover elevations, and integrates natural storage capacity.
- **Multi-Criteria Pond Siting (MCDA)**: Evaluates terrain suitability based on upstream catchment yield, natural depression depth, slope stability, and topographic wetness index (TWI).
- **Watershed Delineation & GeoJSON Export**: Delineates upstream catchment boundary polygons and exports GeoJSON layers for ponds, streams, and catchment basins.
- **Interactive Web Visualizer**: Built-in Leaflet.js dashboard with dark/satellite basemaps, custom markers, and real-time metric cards.

---

## 🚀 Quick Start

### 1. Clone the Repository
```bash
git clone https://github.com/hansikareddy29/Village-Pond-Planning-Systems.git
cd Village-Pond-Planning-Systems
```

### 2. One-Command Setup & Run
```bash
chmod +x run.sh
./run.sh
```

### 3. Open in Browser
- **Interactive Web Visualizer**: [http://localhost:8000/](http://localhost:8000/)
- **Interactive OpenAPI (Swagger) Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Redoc Documentation**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 📡 API Endpoints

### `POST /analyzeContour` (and alias `POST /findCatchment`)
Accepts an uploaded contour map (`.kml` or `.kmz`) as `multipart/form-data`.

#### Example cURL Request:
```bash
curl -X POST "http://localhost:8000/analyzeContour" \
  -F "file=@contours_1m.kml" \
  -F "grid_resolution_m=10.0" \
  -F "rainfall_annual_mm=1000.0" \
  -F "runoff_coefficient=0.35" \
  -F "pond_depth_m=3.0"
```

#### Example Output Response:
```json
{
  "success": true,
  "execution_time_seconds": 1.39,
  "recommended_pond_location": {
    "site_id": "pond_site_1",
    "coordinates": {
      "latitude": 21.251178,
      "longitude": 81.295404,
      "elevation_m": 278.0
    },
    "suitability_score": 99.5,
    "selection_rationale": "Substantial upstream drainage (161.2 ha); Located in a natural topographic bowl (4.0m depth)..."
  },
  "catchment_summary": {
    "area_hectares": 161.18,
    "area_sq_meters": 1611800.0,
    "perimeter_meters": 6832.0,
    "estimated_annual_runoff_million_liters": 564.13
  },
  "pond_design_recommendations": {
    "recommended_storage_capacity_m3": 50000.0,
    "recommended_depth_m": 3.0,
    "recommended_surface_area_sq_m": 22222.2,
    "excavation_savings_from_depression_percent": 83.3
  }
}
```

---

## 🧪 Running Tests

Execute the automated test suite with pytest:
```bash
./venv/bin/python -m pytest tests/ -v
```

Execute the standalone demonstration script:
```bash
./venv/bin/python demo.py
```

---

## 📁 Repository Structure

```
Village-Pond-Planning-Systems/
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI application & REST route definitions
│   ├── models.py             # Pydantic schemas for request/response validation
│   ├── kml_parser.py         # KML & KMZ parser with elevation and coordinate extraction
│   ├── dem_generator.py      # UTM projection & Delaunay TIN DEM surface generator
│   ├── hydrology.py          # Priority-Flood, D8 flow routing, watershed delineation
│   └── pond_siting.py        # Multi-criteria pond site evaluation & design recommendations
├── static/
│   └── index.html            # Interactive Leaflet web dashboard
├── tests/
│   ├── test_kml_parser.py    # Unit tests for KML/KMZ parser
│   ├── test_dem_generator.py # Unit tests for DEM generation & projections
│   ├── test_hydrology.py     # Unit tests for hydrology & catchment delineation
│   └── test_api.py           # Integration tests for FastAPI endpoints
├── assets/                   # High-resolution map plots and figures
├── contours_1m.kml           # Sample contour map dataset
├── demo.py                   # Standalone command-line demonstration script
├── generate_visualizations.py# Script to generate terrain and hydrology figures
├── REPORT.md                 # Full project submission report
├── API_DOCS.md               # Detailed API documentation
├── requirements.txt          # Python dependencies
└── run.sh                    # One-command startup script
```

---

## 📜 Documentation Links
- [Submission Report (REPORT.md)](REPORT.md)
- [API Documentation (API_DOCS.md)](API_DOCS.md)
