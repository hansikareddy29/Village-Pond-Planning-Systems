# Village Pond Planning & Catchment Analysis Backend API

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg?logo=python&logoColor=white)](https://python.org)
[![Tests](https://img.shields.io/badge/Tests-14%20Passed-brightgreen.svg)]()
[![License](https://img.shields.io/badge/License-MIT-blue.svg)]()

An automated, generalized backend REST API service for terrain modeling, optimal village pond location ranking, and exact hydrological watershed catchment delineation from KML/KMZ contour maps.

---

## 🌟 Key Features

- **Multi-Format Ingestion**: Ingests uncompressed `.kml` and zipped `.kmz` files, dynamically parsing 3D contour lines and elevation tags.
- **Dynamic Metric Projection**: Automatically calculates local UTM Zone (e.g. UTM Zone 44N) and transforms WGS84 coordinates into exact metric space.
- **Continuous DEM Surface**: Reconstructs continuous Digital Elevation Model grids from sparse contours using Delaunay Triangulation + Barycentric TIN surface modeling.
- **Clean Priority-Flood**: Implements Priority-Flood (Barnes et al.) depression filling without arbitrary epsilon perturbations.
- **Graph-Based Flow Routing**: D8 flow direction with Dijkstra-based flat surface resolution, and true topological flow accumulation (Kahn's in-degree queue algorithm).
- **Reverse Flow-Graph Catchment Delineation**: Delineates upstream contributing watershed basins via reverse BFS traversal from optimal pour points.
- **Multi-Criteria Pond Siting (MCDA)**: Evaluates terrain suitability based on upstream catchment yield, natural depression depth, slope stability, and topographic wetness index (TWI).
- **Direct GeoJSON Export**: Exports GIS-ready GeoJSON layers for ponds, streams, and catchment basins.

---

## 🚀 Quick Start

### 1. One-Command Setup & Run
```bash
chmod +x run.sh
./run.sh
```

### 2. Open in Browser
- **Interactive OpenAPI (Swagger) Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Redoc Documentation**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 📡 API Endpoint

### `POST /analyzeContour`
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

#### Example GeoJSON File Download:
```bash
curl -X POST "http://localhost:8000/analyzeContour" \
  -F "file=@contours_1m.kml" \
  -F "format=geojson" \
  -o catchment.geojson
```

---

## 🧪 Running Tests

Execute the automated test suite with pytest:
```bash
./venv/bin/python -m pytest tests/ -v
```

---

## 📁 Repository Structure

```
Village-Pond-Planning-Systems/
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI application & single POST /analyzeContour endpoint
│   ├── models.py             # Pydantic schemas for request/response validation
│   ├── kml_parser.py         # KML & KMZ parser with elevation and coordinate extraction
│   ├── dem_generator.py      # UTM projection & Delaunay TIN DEM surface generator
│   ├── hydrology.py          # Clean Priority-Flood, D8 flow routing, graph accumulation, catchment BFS
│   └── pond_siting.py        # Multi-criteria pond site evaluation & design recommendations
├── tests/                    # Synthetic hydrology & API integration test suite
├── contours_1m.kml           # Sample contour map dataset
├── REPORT.md                 # Full project submission report
├── API_DOCS.md               # Detailed API documentation
├── requirements.txt          # Python dependencies
└── run.sh                    # One-command startup script
```
