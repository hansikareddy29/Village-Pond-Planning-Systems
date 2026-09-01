# Village Pond Planning & Catchment Analysis Backend API

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg?logo=python&logoColor=white)](https://python.org)
[![Open-Meteo](https://img.shields.io/badge/Open--Meteo-ERA5%20Reanalysis-orange.svg)](https://open-meteo.com)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)]()

An automated, physics-based backend REST API service for 3D digital terrain modeling, optimal village pond location ranking, and exact hydrological watershed catchment delineation from KML/KMZ contour maps.

**GitHub Repository**: [https://github.com/hansikareddy29/Village-Pond-Planning-Systems.git](https://github.com/hansikareddy29/Village-Pond-Planning-Systems.git)

---

## 🌟 Key Capabilities

- **Continuous DEM Surface**: Reconstructs seamless $10\text{m} \times 10\text{m}$ Digital Elevation Models using Delaunay Triangulated Irregular Network (TIN) linear barycentric interpolation.
- **Priority-Flood Depression Siting**: Detects natural topographic storage sinks and hollows using Barnes' Priority-Flood algorithm, saving over $80\%$ of earthwork excavation costs.
- **Graph-Based Hydrology**: D8 flow direction with Garbrecht-Martz flat routing and Kahn's topological flow accumulation ($O(N)$ linear time).
- **Reverse-BFS Catchment Delineation**: Delineates upstream contributing watershed basins via reverse BFS from optimal pour points.
- **Rational Runoff Yield Modeling**: Computes annual water harvest volume ($V = C \times P \times A$) using live meteorological rainfall data.
- **Dual-Basin Engineering GeoJSON**: Renders both the **Compact Core Farm Pond ($0.6 - 1.4\text{ ha}$)** and the **Full Natural Depression Basin ($1.4 - 6.8\text{ ha}$)** with distinct symbology for all candidate sites.

---

## 🚀 Quick Start

### 1. One-Command Setup & Run
```bash
chmod +x run.sh
./run.sh
```
---

## 📡 API Endpoints

### `POST /analyzeContour`
Accepts a 3D contour map (`.kml` or `.kmz`) via `multipart/form-data`.

#### Query Parameters:
| Parameter | Type | Default | Description |
| :--- | :---: | :---: | :--- |
| `grid_resolution_m` | `float` | `10.0` | Spatial resolution of the DEM grid in meters. |
| `rainfall_annual_mm`| `float` | `null` | Optional rainfall override. If omitted, live Open-Meteo ERA5 rainfall is fetched. |
| `runoff_coefficient`| `float` | `0.35` | Rational runoff factor (0.25–0.45 typical for loamy agricultural soil). |
| `pond_depth_m` | `float` | `3.0` | Target design depth for civil pond excavation in meters. |
| `num_candidate_sites` | `int` | `5` | Number of top candidate pond locations to return. |
| `format` | `string` | `"json"` | Output format: `"json"` (full payload) or `"geojson"` (FeatureCollection). |

#### Example cURL Request:
```bash
curl -X POST "http://localhost:8000/analyzeContour?grid_resolution_m=10.0&num_candidate_sites=5" \
  -F "file=@contours_1m.kml" \
  -o analysis_output.json
```

#### Example Direct GeoJSON Download for `geojson.io`:
```bash
curl -X POST "http://localhost:8000/analyzeContour?format=geojson" \
  -F "file=@contours_1m.kml" \
  -o village_pond_map.geojson
```

---

## 🌊 Hydrological & Catchment Estimation Approach

1. **Projection & DEM Construction (`app/dem_generator.py`)**:
   Projects WGS84 coordinates to UTM Zone 44N (EPSG:32644) and builds a $10\text{m} \times 10\text{m}$ grid using Delaunay Triangulation + TIN barycentric surface interpolation.
2. **Depression Detection (`app/hydrology.py`)**:
   Uses Barnes' Priority-Flood algorithm with a min-heap queue to flood the terrain inward. Subtracting the original DEM from the filled DEM computes the **Depression Depth Grid**:
   $$\text{Depression Depth}(r, c) = \text{DEM}_{\text{filled}}(r, c) - \text{DEM}_{\text{original}}(r, c)$$
3. **D8 Flow Direction & Routing**:
   Determines steepest downhill gravity paths across 8 directions ($2^0 \dots 2^7$) and resolves flat lake beds using Garbrecht-Martz dual-gradient routing.
4. **Kahn's Topological Flow Accumulation**:
   Rapidly accumulates uphill cell drainage counts in $O(N)$ linear time without recursion stack overflows.
5. **Reverse-BFS Catchment Delineation**:
   Traces tributary cells uphill from each pour point to delineate the watershed drainage divide.
6. **Rational Method Water Harvest Yield**:
   $$V_{\text{runoff}} = C \times P \times A$$
   *(where $C = 0.35$, $P = 1,382.6\text{ mm}$ live Open-Meteo ERA5 precipitation, and $A$ is the catchment area).*
7. **Multi-Criteria Decision Analysis (MCDA) Scoring (`app/pond_siting.py`)**:
   $$\text{Score} = 100 \times \Big( 0.35 \cdot S_{\text{dep}} + 0.25 \cdot S_{\text{catch}} + 0.15 \cdot S_{\text{vol}} + 0.10 \cdot S_{\text{slope}} + 0.10 \cdot S_{\text{interior}} + 0.05 \cdot S_{\text{twi}} \Big)$$

---

## 🗺️ Demonstration: Candidate Pond Locations (`contours_1m.kml`)

The system processed the 1-meter contour map of **Sirsa Khurd / Jeora Sirsa village, Durg (Chhattisgarh)** across 519.4 hectares (1,355 contours, 160,468 points, 87,843 grid cells).

### Master Candidate Sites Summary:

| Rank | Site ID | Latitude (°N) | Longitude (°E) | Bed Elev. | Natural Depth | Compact Footprint | Full Basin Footprint | Catchment Area | Annual Runoff Yield | Bed Slope | Score |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | `pond_site_1` | **`21.251809`** | **`81.296659`** | $270.01\text{ m}$ | **$11.98\text{ m}$** | **$1.35\text{ ha}$** | **$5.59\text{ ha}$** | **$173.79\text{ ha}$** | **`840,987 m³`** | $0.62\%$ | **`96.0`** |
| **2** | `pond_site_2` | **`21.248820`** | **`81.300411`** | $278.01\text{ m}$ | **$5.99\text{ m}$** | **$0.57\text{ ha}$** | **$6.75\text{ ha}$** | **$111.46\text{ ha}$** | **`539,366 m³`** | $0.47\%$ | **`81.5`** |
| **3** | `pond_site_3` | **`21.256858`** | **`81.302548`** | $280.00\text{ m}$ | **$8.98\text{ m}$** | **$1.25\text{ ha}$** | **$2.74\text{ ha}$** | **$13.21\text{ ha}$** | **`63,925 m³`** | $0.13\%$ | **`80.7`** |
| **4** | `pond_site_4` | **`21.259406`** | **`81.292529`** | $278.00\text{ m}$ | **$3.38\text{ m}$** | **$0.93\text{ ha}$** | **$1.38\text{ ha}$** | **$96.24\text{ ha}$** | **`465,715 m³`** | $0.10\%$ | **`71.4`** |
| **5** | `pond_site_5` | **`21.243656`** | **`81.308497`** | $283.00\text{ m}$ | **$4.98\text{ m}$** | **$0.79\text{ ha}$** | **$2.27\text{ ha}$** | **$43.49\text{ ha}$** | **`210,452 m³`** | $0.60\%$ | **`71.3`** |

---

## 🎨 Visual Map Symbology on `geojson.io`

When loading the generated GeoJSON into `geojson.io` or GIS software:
* 🟨 **Inner Green Solid Polygon (Gold Border)**: **Compact Core Farm Pond ($0.6 - 1.4\text{ ha}$)** — Immediate construction excavation footprint in the deepest natural depression ($>4.5\text{m}$ depth).
* 🟦 **Outer Cyan Dashed Polygon**: **Full Natural Depression Basin ($1.4 - 6.8\text{ ha}$)** — Maximum natural water retention reservoir bowl.
* 🔵 **Dark Blue Flow Lines**: **Drainage Stream Network** — Natural surface runoff flow veins carrying rainwater downhill into the pond basins.
* 📍 **Center Markers**: Exact pond bed coordinates and construction centers.
* 📍 **Left Spillway Markers**: Natural spillway overflow pour points with crest elevation levels.

---

## 📁 Repository Structure

```
Village-Pond-Planning-Systems/
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI server, REST routes & GeoJSON assembly
│   ├── models.py             # Pydantic schemas & response validation
│   ├── kml_parser.py         # 3D contour XML parser & boundary extractor
│   ├── dem_generator.py      # UTM projection & Delaunay TIN DEM interpolator
│   ├── hydrology.py          # Priority-Flood, D8 flow, topological accumulation & streams
│   ├── pond_siting.py        # MCDA multi-criteria siting & dual-basin BFS extractor
│   └── external_apis.py      # Open-Meteo ERA5 climate archive & Elevation SRTM services
├── requirements.txt          # Production dependencies
└── run.sh                    # Server startup script
```

