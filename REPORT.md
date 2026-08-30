# Project Submission Report: Village Pond Planning & Catchment Analysis Backend System

---

## 1. Project Overview & Repository

- **GitHub Repository**: [https://github.com/hansikareddy29/Village-Pond-Planning-Systems](https://github.com/hansikareddy29/Village-Pond-Planning-Systems)
- **Primary Working API Endpoint**: `POST http://localhost:8000/analyzeContour`
- **Health Check URL**: `GET http://localhost:8000/health`
- **Interactive OpenAPI Documentation**: `http://localhost:8000/docs`

---

## 2. Executive Summary

This project implements an automated, generalized, production-ready backend REST API for **Village Pond Planning and Hydrological Catchment Analysis** from raw contour maps in KML and KMZ formats.

Given any uploaded contour dataset, the system:
1. Ingests 3D contour lines, elevation tags, and village survey boundaries without hardcoded coordinate assumptions.
2. Projects geographic coordinates into dynamic local metric Universal Transverse Mercator (UTM) space (`EPSG:32600 + Zone`).
3. Interpolates a continuous, high-resolution Digital Elevation Model (DEM) using Delaunay Triangulation + Barycentric TIN surface modeling.
4. Performs advanced digital hydrology: clean Priority-Flood depression filling, deterministic D8 steepest descent flow routing with flat surface Dijkstra resolution, and genuine graph-based topological flow accumulation ($O(N)$ Kahn's in-degree queue algorithm).
5. Detects natural topographic hollows/depressions and calculates natural storage volume.
6. Evaluates candidate pond locations using a multi-criteria decision analysis (MCDA) scoring framework.
7. Delineates the exact upstream contributing watershed catchment boundary polygon via reverse flow-graph Breadth-First Search (BFS) and calculates surface area ($m^2$, ha, acres), perimeter, elevation statistics, and annual runoff volume.
8. Returns structured JSON output and GIS-ready GeoJSON layers.

---

## 3. Mathematical Formulation & Hydrological Methodology

### 3.1. Generalization & Coordinate Projection
- The geographic centroid $(\lambda_c, \phi_c)$ is computed from the parsed contour vertices.
- The UTM Zone is calculated dynamically:
  $$\text{UTM Zone} = \left\lfloor \frac{\lambda_c + 180^\circ}{6^\circ} \right\rfloor + 1$$
- High-precision bidirectional transformers (`pyproj.Transformer`) map between `EPSG:4326` (WGS84) and metric UTM `EPSG:32600 + Zone` (or `32700 + Zone` in the Southern Hemisphere). All spatial distances, cell sizes, slopes, areas ($m^2$), and storage volumes ($m^3$) are computed in true metric units.

### 3.2. Continuous DEM Grid Generation
1. Contour vertices $(X_i, Y_i, Z_i)$ in metric UTM space construct a Delaunay Triangulation.
2. Linear barycentric interpolation (`scipy.interpolate.griddata`) evaluates elevations on a regular 2D grid ($\Delta x = \Delta y = 10.0\text{m}$).
3. Outer margins are filled using nearest-neighbor spatial extrapolation.
4. Slope gradient matrix ($S$) is calculated using central differences:
   $$S = \sqrt{\left(\frac{\partial Z}{\partial x}\right)^2 + \left(\frac{\partial Z}{\partial y}\right)^2} \times 100\%$$

### 3.3. Clean Priority-Flood Depression Filling
To ensure continuous surface drainage without introducing arbitrary epsilon perturbations:
- A min-priority queue initializes with all DEM outer boundary cells.
- The lowest elevation wavefront $(z, r, c)$ propagates inward:
  $$Z_{\text{filled}}(nr, nc) = \max\left(Z_{\text{original}}(nr, nc), z\right)$$
- Topographic depression depth is preserved as:
  $$D_{\text{depression}}(r, c) = \max\left(0, Z_{\text{filled}}(r, c) - Z_{\text{original}}(r, c)\right)$$

### 3.4. D8 Flow Direction & Flat Surface Resolution
- For cells with lower neighbors, flow routes to the neighbor with the steepest downward slope:
  $$S_k = \frac{Z_{\text{filled}}(r, c) - Z_{\text{filled}}(r + \Delta r_k, c + \Delta c_k)}{d_k \cdot \text{resolution}}$$
  where $d_k = 1.0$ for cardinal neighbors and $d_k = \sqrt{2} \approx 1.4142$ for diagonal neighbors.
- For flat regions (equal elevations), Dijkstra distance-wave propagation from resolved downhill outlets routes flat cells deterministically toward the spillway, guaranteeing a Directed Acyclic Graph (DAG) with **zero cycles**.

### 3.5. Graph-Based Topological Flow Accumulation (Kahn's Algorithm)
Rather than relying on elevation sorting (which can fail on flats and filled depressions), the system implements a strict graph-based topological sort:
1. Calculates in-degree $D_{\text{in}}(r, c)$ for every cell (number of upstream cells draining into it).
2. Enqueues all headwater/ridge cells ($D_{\text{in}} == 0$).
3. Iteratively pops cells, pushes their accumulated flow to their downstream neighbor, and decrements the neighbor's in-degree.
4. When a downstream cell's in-degree reaches $0$, it is enqueued.

### 3.6. Reverse Flow-Graph Catchment Delineation
- For the selected optimal pond pour point $(r_0, c_0)$, an inverted Breadth-First Search (BFS) traverses all upstream contributing cells in the directed flow graph.
- Catchment surface area is computed as:
  $$A_{\text{catchment}} = N_{\text{cells}} \times (\text{resolution\_m})^2$$
- Annual water yield is calculated using the **Rational Method**:
  $$V_{\text{annual\_runoff}} = C \cdot P_{\text{annual}} \cdot A_{\text{catchment}}$$
  where $C$ is the runoff coefficient (default $0.35$), $P$ is annual precipitation in meters, and $A$ is the catchment area in $m^2$.

---

## 4. Benchmark Demonstration on Sample Contour Map (`contours_1m.kml`)

### 4.1. Input Map Summary
- **File**: `contours_1m.kml`
- **Total Contours Extracted**: 1,355 contour polylines
- **3D Coordinate Vertices**: 160,468 points
- **Contour Interval**: 1.0 meter
- **Geographic Bounds**: Lon $[81.2814^\circ, 81.3126^\circ\text{ E}]$, Lat $[21.2398^\circ, 21.2636^\circ\text{ N}]$
- **Elevation Range**: 267.0 m to 297.91 m (Total Relief: 30.91 m)
- **Auto-Detected Projection**: UTM Zone 44N (`EPSG:32644`)
- **DEM Grid Size**: 267 rows $\times$ 329 columns (87,843 cells @ 10.0m resolution)

### 4.2. Recommended Optimal Pond Location (Rank 1)
- **Site ID**: `pond_site_1`
- **Latitude / Longitude**: **$21.243691^\circ\text{ N}, 81.288354^\circ\text{ E}$**
- **UTM Coordinates**: Easting $529,919.5\text{ m}$, Northing $2,349,145.3\text{ m}$
- **Base Elevation**: **271.00 m MSL**
- **Composite Suitability Score**: **99.5 / 100**
- **Local Slope**: **$0.38\%$** (very gentle, ideal for embankment stability)
- **Natural Depression Depth**: **$3.00\text{ m}$**
- **Selection Rationale**: *"Substantial upstream drainage (43.9 ha); Located in a natural topographic bowl (3.0m depth) reducing excavation; very gentle bed slope (0.4%) for stable embankment."*

### 4.3. Catchment / Watershed Results
- **Total Catchment Area**: **43.91 hectares** ($439,100\text{ m}^2$ / $108.50\text{ acres}$)
- **Catchment Perimeter**: **4,840.0 meters** ($4.84\text{ km}$)
- **Catchment Elevation Range**: 269.53 m to 290.87 m (Mean: 281.78 m)
- **Catchment Average Slope**: $5.72\%$ ($3.27^\circ$)
- **Estimated Annual Runoff Harvest**: **153.69 Million Liters / year** ($153,685\text{ m}^3$)
- **Peak Design Discharge ($Q_p$)**: $2.13\text{ m}^3/\text{s}$

### 4.4. Pond Engineering Sizing Recommendations
- **Recommended Storage Capacity**: **$30,737\text{ m}^3$** (30.74 Million Liters)
- **Pond Surface Area**: $13,660.9\text{ m}^2$ ($1.37\text{ ha}$)
- **Dimensions ($L \times W$)**: $143.1\text{ m} \times 95.4\text{ m}$ (Side slopes 1.5:1)
- **Pond Depth / Bund Height**: $3.0\text{ m}$ depth with $1.1\text{ m}$ freeboard bund
- **Excavation Savings**: **$83.3\%$** earthwork reduction achieved by utilizing the existing topographic depression
- **Agricultural Support**: Provides supplemental irrigation for **$7.68\text{ hectares}$** of crops

---

## 5. Scientific Limitations & Engineering Disclaimer

This software serves as a **preliminary planning and terrain suitability assessment tool**. Users and civil planners must note the following engineering limitations:
1. **DEM Discretization & Resolution**: Topographic surfaces interpolated from contour polylines are subject to interpolation smoothing. Grid resolution (e.g. 10m) sets the minimum detectable drainage feature size.
2. **D8 Flow Routing Simplification**: Single-flow-direction (D8) routes 100% of flow to a single neighbor, which simplifies multi-directional sheet flow on divergent ridges.
3. **Runoff Approximations**: The Rational Method ($V = C \cdot P \cdot A$) provides lumped seasonal water yield estimates. Local infiltration, soil hydraulic conductivity, and land-use variations require detailed soil-moisture modeling (e.g. SCS-CN).
4. **Field Verification**: Final pond excavation, embankment structural design, spillway sizing, and geomembrane lining require on-site geotechnical boreholes and professional civil engineering evaluation.

---

## 6. How to Run & Verify the Solution

### Prerequisites
- Python 3.10+
- Linux / macOS / Windows WSL

### One-Command Startup
```bash
./run.sh
```

### Run Automated Test Suite
```bash
./venv/bin/python -m pytest tests/ -v
```

### Test API via cURL
```bash
curl -X POST "http://localhost:8000/analyzeContour" \
  -F "file=@contours_1m.kml" \
  -F "grid_resolution_m=10.0" \
  -F "rainfall_annual_mm=1000.0" \
  -F "runoff_coefficient=0.35" \
  -F "pond_depth_m=3.0"
```
