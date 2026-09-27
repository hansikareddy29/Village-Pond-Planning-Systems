/**
 * Village Pond Planning & Catchment Analysis GIS Frontend
 * Handles interactive map, land area polygon/box selection,
 * asynchronous API queries, real-time overlays, and dashboard metrics.
 */

let map;
let baseLayers = {};
let drawnItems;
let activeGeoJsonLayer = null;
let streamsLayer = null;
let surveyBoundaryLayer = null;
let defaultVillageData = null;
let currentSelectedGeometry = null;
let lastAnalysisResult = null;
let activeDrawHandler = null;

// Initialize when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  initMap();
  loadDefaultVillageData();
  setupEventListeners();
});

/**
 * Initializes Leaflet map with Satellite and Street layers
 */
function initMap() {
  // Center on Sirsa Khurd Village (Durg, Chhattisgarh)
  const defaultCenter = [21.2518, 81.2966];
  const defaultZoom = 14;

  map = L.map("map", {
    center: defaultCenter,
    zoom: defaultZoom,
    zoomControl: true,
  });

  // 1. Esri World Imagery (High-Res Satellite)
  const esriSatellite = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    {
      attribution: "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics",
      maxZoom: 19,
    }
  );

  // 2. OpenStreetMap Standard
  const osmStandard = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 19,
  });

  // 3. OpenTopoMap
  const openTopo = L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
    attribution: "Map data: &copy; OpenStreetMap, SRTM | Map style: &copy; OpenTopoMap",
    maxZoom: 17,
  });

  esriSatellite.addTo(map);

  baseLayers = {
    "Satellite Imagery": esriSatellite,
    "OpenStreetMap": osmStandard,
    "Topographic Terrain": openTopo,
  };

  L.control.layers(baseLayers, null, { position: "topright" }).addTo(map);

  // FeatureGroup to hold drawn shapes
  drawnItems = new L.FeatureGroup();
  map.addLayer(drawnItems);
}

/**
 * Loads baseline village terrain data and initializes candidate sites
 */
async function loadDefaultVillageData() {
  showSpinner("Loading village terrain and hydrological baseline...");
  try {
    const res = await fetch("/api/default-data");
    if (!res.ok) throw new Error("Failed to load baseline data");
    defaultVillageData = await res.json();

    // Populate header rainfall badge
    if (defaultVillageData.rainfall_summary) {
      document.getElementById("header-rainfall").innerText =
        `${defaultVillageData.rainfall_summary.annual_rainfall_mm.toFixed(1)} mm`;
    }

    // Render surveyed village boundary (Golden outline)
    if (defaultVillageData.boundary_polygon || defaultVillageData.bounds) {
      let boundaryLatLngs = [];
      if (defaultVillageData.boundary_polygon && defaultVillageData.boundary_polygon.length >= 3) {
        boundaryLatLngs = defaultVillageData.boundary_polygon.map((pt) => [pt[1], pt[0]]);
      } else if (defaultVillageData.bounds) {
        const b = defaultVillageData.bounds;
        boundaryLatLngs = [
          [b.min_lat, b.min_lon],
          [b.max_lat, b.min_lon],
          [b.max_lat, b.max_lon],
          [b.min_lat, b.max_lon],
        ];
      }

      if (boundaryLatLngs.length > 0) {
        if (surveyBoundaryLayer) map.removeLayer(surveyBoundaryLayer);
        surveyBoundaryLayer = L.polygon(boundaryLatLngs, {
          color: "#FFB300",
          weight: 2.5,
          dashArray: "6, 6",
          fillColor: "#FFB300",
          fillOpacity: 0.08,
          interactive: true,
        }).addTo(map);

        surveyBoundaryLayer.bindTooltip(
          "<b>Surveyed Village Boundary (Sirsa Khurd - 519.4 ha)</b><br>Draw your land parcel inside this area for elevation & runoff calculations.",
          { sticky: true, opacity: 0.95 }
        );

        // Auto-fit to the surveyed boundary so the user is directly viewing the valid area
        map.fitBounds(surveyBoundaryLayer.getBounds(), { padding: [35, 35] });
      }
    }

    // Render stream network
    if (defaultVillageData.streams) {
      streamsLayer = L.geoJSON(defaultVillageData.streams, {
        style: {
          color: "#1A237E",
          weight: 2,
          opacity: 0.85,
        },
      }).addTo(map);
    }
  } catch (err) {
    console.error("Error loading village data:", err);
  } finally {
    hideSpinner();
  }
}

/**
 * Sets up button controls and map interaction handlers
 */
function setupEventListeners() {
  document.getElementById("btn-draw-poly").addEventListener("click", () => {
    startCustomPolygonDraw();
  });

  document.getElementById("btn-draw-rect").addEventListener("click", () => {
    startCustomRectangleDraw();
  });

  document.getElementById("btn-focus-boundary")?.addEventListener("click", () => {
    if (surveyBoundaryLayer) {
      map.fitBounds(surveyBoundaryLayer.getBounds(), { padding: [35, 35] });
    } else if (defaultVillageData && defaultVillageData.bounds) {
      const b = defaultVillageData.bounds;
      map.fitBounds(
        [
          [b.min_lat, b.min_lon],
          [b.max_lat, b.max_lon],
        ],
        { padding: [35, 35] }
      );
    }
  });

  document.getElementById("btn-analyze").addEventListener("click", () => {
    if (!currentSelectedGeometry) {
      alert("Please draw a land area on the map first using 'Draw Land Area' or 'Draw Rectangle'!");
      return;
    }
    executeLandAnalysis(currentSelectedGeometry);
  });

  document.getElementById("btn-clear").addEventListener("click", () => {
    clearAllDrawingsAndResults();
  });

  document.getElementById("btn-export-geojson").addEventListener("click", () => {
    exportGeoJSON();
  });

  document.getElementById("btn-export-json").addEventListener("click", () => {
    exportJSON();
  });
}

/**
 * Handles Polygon drawing on map
 */
function startCustomPolygonDraw() {
  resetActiveToolButtons();
  document.getElementById("btn-draw-poly").classList.add("active");

  if (typeof L.Draw !== "undefined" && L.Draw.Polygon) {
    if (activeDrawHandler) activeDrawHandler.disable();
    activeDrawHandler = new L.Draw.Polygon(map, {
      shapeOptions: {
        color: "#D81B60",
        weight: 3,
        dashArray: "6, 4",
        fillColor: "#E91E63",
        fillOpacity: 0.2,
      },
    });
    activeDrawHandler.enable();

    map.once(L.Draw.Event.CREATED, (e) => {
      drawnItems.clearLayers();
      const layer = e.layer;
      drawnItems.addLayer(layer);
      currentSelectedGeometry = layer.toGeoJSON().geometry;
      resetActiveToolButtons();
      executeLandAnalysis(currentSelectedGeometry);
    });
  } else {
    // Fallback interactive click-to-draw polygon
    startManualPolygonDraw();
  }
}

/**
 * Handles Rectangle drawing on map
 */
function startCustomRectangleDraw() {
  resetActiveToolButtons();
  document.getElementById("btn-draw-rect").classList.add("active");

  if (typeof L.Draw !== "undefined" && L.Draw.Rectangle) {
    if (activeDrawHandler) activeDrawHandler.disable();
    activeDrawHandler = new L.Draw.Rectangle(map, {
      shapeOptions: {
        color: "#D81B60",
        weight: 3,
        dashArray: "6, 4",
        fillColor: "#E91E63",
        fillOpacity: 0.2,
      },
    });
    activeDrawHandler.enable();

    map.once(L.Draw.Event.CREATED, (e) => {
      drawnItems.clearLayers();
      const layer = e.layer;
      drawnItems.addLayer(layer);
      currentSelectedGeometry = layer.toGeoJSON().geometry;
      resetActiveToolButtons();
      executeLandAnalysis(currentSelectedGeometry);
    });
  } else {
    alert("Click two points on the map to define the bounding box corners.");
    map.once("click", (e1) => {
      map.once("click", (e2) => {
        const bounds = L.latLngBounds(e1.latlng, e2.latlng);
        const rect = L.rectangle(bounds, {
          color: "#D81B60",
          weight: 3,
          dashArray: "6, 4",
          fillColor: "#E91E63",
          fillOpacity: 0.2,
        });
        drawnItems.clearLayers();
        drawnItems.addLayer(rect);
        currentSelectedGeometry = rect.toGeoJSON().geometry;
        resetActiveToolButtons();
        executeLandAnalysis(currentSelectedGeometry);
      });
    });
  }
}

/**
 * Native click-to-draw fallback for polygon if Leaflet.Draw CDN is blocked
 */
function startManualPolygonDraw() {
  const points = [];
  let tempPoly = null;

  const onMapClick = (e) => {
    points.push(e.latlng);
    if (points.length >= 3) {
      if (tempPoly) map.removeLayer(tempPoly);
      tempPoly = L.polygon(points, {
        color: "#D81B60",
        weight: 3,
        dashArray: "6, 4",
        fillColor: "#E91E63",
        fillOpacity: 0.2,
      }).addTo(map);
    }
  };

  const onMapDblClick = () => {
    map.off("click", onMapClick);
    map.off("dblclick", onMapDblClick);
    if (tempPoly) map.removeLayer(tempPoly);
    if (points.length >= 3) {
      const finalPoly = L.polygon(points, {
        color: "#D81B60",
        weight: 3,
        dashArray: "6, 4",
        fillColor: "#E91E63",
        fillOpacity: 0.2,
      });
      drawnItems.clearLayers();
      drawnItems.addLayer(finalPoly);
      currentSelectedGeometry = finalPoly.toGeoJSON().geometry;
      resetActiveToolButtons();
      executeLandAnalysis(currentSelectedGeometry);
    }
  };

  map.on("click", onMapClick);
  map.on("dblclick", onMapDblClick);
}

function resetActiveToolButtons() {
  document.getElementById("btn-draw-poly").classList.remove("active");
  document.getElementById("btn-draw-rect").classList.remove("active");
}

/**
 * Selects a pre-defined village land parcel / agricultural sector
 */
function selectSector(sectorId, shouldAnalyze = true) {
  if (!defaultVillageData) return;

  let coords = null;
  let sectorName = "";

  if (sectorId === "entire_village") {
    // Entire survey perimeter bounding box
    const b = defaultVillageData.bounds;
    coords = [
      [b.min_lon, b.min_lat],
      [b.max_lon, b.min_lat],
      [b.max_lon, b.max_lat],
      [b.min_lon, b.max_lat],
      [b.min_lon, b.min_lat],
    ];
    sectorName = "Entire Village Survey Area (519.4 ha)";
  } else {
    const sec = defaultVillageData.preset_sectors.find((s) => s.id === sectorId);
    if (sec) {
      coords = sec.coordinates;
      sectorName = sec.name;
    }
  }

  if (!coords) return;

  const latLngs = coords.map((pt) => [pt[1], pt[0]]);
  drawnItems.clearLayers();

  const poly = L.polygon(latLngs, {
    color: "#D81B60",
    weight: 3,
    dashArray: "6, 4",
    fillColor: "#E91E63",
    fillOpacity: 0.18,
  });
  drawnItems.addLayer(poly);
  map.fitBounds(poly.getBounds(), { padding: [40, 40] });

  currentSelectedGeometry = {
    type: "Polygon",
    coordinates: [coords],
  };

  if (shouldAnalyze) {
    executeLandAnalysis(currentSelectedGeometry);
  }
}

/**
 * Sends POST /analyzeArea query to backend and updates map overlays & dashboard
 */
async function executeLandAnalysis(geometry) {
  showSpinner("Running priority-flood routing & catchment delineation for land area...");

  try {
    const payload = {
      geometry: geometry,
      rainfall_annual_mm: null,
      runoff_coefficient: 0.35,
      pond_depth_m: 3.0,
      format: "json",
    };

    const response = await fetch("/analyzeArea", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || "Analysis failed");
    }

    const data = await response.json();
    lastAnalysisResult = data;
    renderAnalysisResults(data);
  } catch (error) {
    hideSpinner();
    console.error("Error executing land analysis:", error);
    alert(`${error.message}`);
    if (surveyBoundaryLayer) {
      map.fitBounds(surveyBoundaryLayer.getBounds(), { padding: [35, 35] });
    }
  } finally {
    hideSpinner();
  }
}

/**
 * Renders GeoJSON layers, markers, popups, and updates dashboard metrics
 */
function renderAnalysisResults(result) {
  // Clear previous active GeoJSON overlay
  if (activeGeoJsonLayer) {
    map.removeLayer(activeGeoJsonLayer);
  }

  // Render complete GeoJSON collection
  activeGeoJsonLayer = L.geoJSON(result.geojson, {
    style: (feature) => {
      const props = feature.properties || {};
      if (props.feature_type === "selected_land_area") {
        return {
          color: "#D81B60",
          weight: 3,
          dashArray: "6, 4",
          fillColor: "#E91E63",
          fillOpacity: 0.16,
        };
      } else if (props.feature_type === "catchment_boundary") {
        return {
          color: "#00B0FF",
          weight: 3,
          dashArray: "6, 6",
          fillColor: "#00E5FF",
          fillOpacity: 0.22,
        };
      } else if (props.feature_type === "compact_pond_footprint") {
        return {
          color: "#FFD600",
          weight: 4,
          fillColor: "#00C853",
          fillOpacity: 0.85,
        };
      } else if (props.feature_type === "full_natural_basin") {
        return {
          color: "#00B0FF",
          weight: 2,
          dashArray: "4, 4",
          fillColor: "#00E676",
          fillOpacity: 0.18,
        };
      } else if (props.feature_type === "drainage") {
        return {
          color: "#1A237E",
          weight: 2,
          opacity: 0.9,
        };
      }
      return {};
    },
    pointToLayer: (feature, latlng) => {
      const props = feature.properties || {};
      if (props.feature_type === "pond_candidate") {
        // High visibility custom pin marker for recommended pond location
        const markerHtml = `
          <div style="
            background: linear-gradient(135deg, #00C853, #2E7D32);
            color: #ffffff;
            width: 38px;
            height: 38px;
            border-radius: 50% 50% 50% 0;
            transform: rotate(-45deg);
            display: flex;
            align-items: center;
            justify-content: center;
            border: 3px solid #ffffff;
            box-shadow: 0 4px 12px rgba(0,0,0,0.6);
            font-weight: 800;
            font-size: 14px;
          ">
            <span style="transform: rotate(45deg);">P</span>
          </div>
        `;
        const customIcon = L.divIcon({
          className: "pond-marker-pin",
          html: markerHtml,
          iconSize: [38, 38],
          iconAnchor: [19, 38],
          popupAnchor: [0, -38],
        });
        return L.marker(latlng, { icon: customIcon });
      } else if (props.feature_type === "pour_point") {
        const spillwayHtml = `
          <div style="
            background: #00B0FF;
            color: #ffffff;
            width: 26px;
            height: 26px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            border: 2px solid #ffffff;
            box-shadow: 0 2px 8px rgba(0,0,0,0.5);
            font-size: 11px;
            font-weight: 700;
          ">S</div>
        `;
        const spillIcon = L.divIcon({
          className: "spillway-pin",
          html: spillwayHtml,
          iconSize: [26, 26],
          iconAnchor: [13, 13],
          popupAnchor: [0, -13],
        });
        return L.marker(latlng, { icon: spillIcon });
      }
      return L.circleMarker(latlng);
    },
    onEachFeature: (feature, layer) => {
      const p = feature.properties || {};
      let popupContent = "";
      if (p.feature_type === "pond_candidate") {
        popupContent = `
          <div style="min-width: 220px; font-family: sans-serif; color: #0f172a;">
            <h4 style="margin: 0 0 6px 0; color: #0284c7; font-size: 15px;">
              Suggested Pond Location (${p.site_id})
            </h4>
            <div style="font-size: 12px; line-height: 1.6;">
              <strong>Suitability Score:</strong> <span style="color: #10b981; font-weight: 700;">${p.suitability_score} / 100</span><br/>
              <strong>Bed Elevation:</strong> ${p.elevation_m} m<br/>
              <strong>Natural Depression Depth:</strong> ${p.depression_depth_m} m<br/>
              <strong>Catchment Runoff Area:</strong> ${p.catchment_area_ha} ha<br/>
              <strong>Expected Annual Water Harvest:</strong> <strong style="color: #0284c7;">${p.annual_water_harvest_m3.toLocaleString()} m³</strong> (${p.annual_water_harvest_million_liters} ML)<br/>
            </div>
          </div>
        `;
      } else if (p.feature_type === "catchment_boundary") {
        popupContent = `
          <div style="min-width: 200px; font-family: sans-serif; color: #0f172a;">
            <h4 style="margin: 0 0 4px 0; color: #00B0FF; font-size: 14px;">Delineated Catchment Basin</h4>
            <div style="font-size: 12px; line-height: 1.5;">
              <strong>Drainage Area:</strong> ${p.area_hectares} ha (${p.area_acres} acres)<br/>
              <strong>Annual Water Yield:</strong> ${p.expected_runoff_m3 ? p.expected_runoff_m3.toLocaleString() : ""} m³<br/>
            </div>
          </div>
        `;
      } else if (p.feature_type === "selected_land_area") {
        popupContent = `
          <div style="font-family: sans-serif; color: #0f172a;">
            <h4 style="margin: 0 0 4px 0; color: #D81B60; font-size: 14px;">Selected Land Area</h4>
            <div style="font-size: 12px;">Area: <strong>${p.area_hectares} ha</strong> (${p.area_acres} acres)</div>
          </div>
        `;
      } else if (p.feature_type === "pour_point") {
        popupContent = `
          <div style="font-family: sans-serif; color: #0f172a;">
            <h4 style="margin: 0 0 4px 0; color: #00B0FF; font-size: 14px;">Natural Spillway Overflow Weir</h4>
            <div style="font-size: 12px;">Crest Elevation: <strong>${p.elevation_m} m</strong></div>
          </div>
        `;
      }

      if (popupContent) {
        layer.bindPopup(popupContent);
      }
    },
  }).addTo(map);

  // Zoom map to show both the selected land area and the delineated catchment
  const bounds = activeGeoJsonLayer.getBounds();
  if (bounds.isValid()) {
    map.fitBounds(bounds, { padding: [50, 50] });
  }

  // Update Floating Results HUD
  updateResultsHUD(result);

  // Update Right Analytics Dashboard
  updateDashboard(result);
}

/**
 * Updates Floating Results HUD overlaid on map
 */
function updateResultsHUD(res) {
  const hud = document.getElementById("results-hud");
  hud.style.display = "block";

  const site = res.recommended_pond_location;
  const catchm = res.catchment_summary;
  const water = res.expected_water_volume;

  document.getElementById("hud-site-title").innerText = `Optimal Site: ${site.site_id}`;
  document.getElementById("hud-score-badge").innerText = `Score: ${site.suitability_score}/100`;

  document.getElementById("hud-water-volume").innerHTML =
    `${water.estimated_annual_runoff_m3.toLocaleString()} <span class="hud-stat-unit">m³</span>`;
  document.getElementById("hud-water-ml").innerText =
    `${water.estimated_annual_runoff_million_liters.toFixed(1)}`;

  document.getElementById("hud-catchment-ha").innerHTML =
    `${catchm.area_hectares.toFixed(1)} <span class="hud-stat-unit">ha</span>`;
  document.getElementById("hud-land-ha").innerHTML =
    `${res.selected_land_area_ha.toFixed(1)} <span class="hud-stat-unit">ha</span>`;

  document.getElementById("hud-bed-elev").innerHTML =
    `${site.coordinates.elevation_m.toFixed(1)} <span class="hud-stat-unit">m</span>`;
  document.getElementById("hud-dep-depth").innerHTML =
    `${site.local_terrain.depression_depth_m.toFixed(2)} <span class="hud-stat-unit">m</span>`;
}

/**
 * Updates Right Analytics Sidebar cards
 */
function updateDashboard(res) {
  const site = res.recommended_pond_location;
  const catchm = res.catchment_summary;
  const water = res.expected_water_volume;
  const design = res.pond_design_recommendations;

  // Card 1
  document.getElementById("card-site-id").innerText = site.site_id;
  document.getElementById("card-score").innerText = `${site.suitability_score} / 100`;
  document.getElementById("card-coords").innerText =
    `${site.coordinates.latitude.toFixed(4)}° N, ${site.coordinates.longitude.toFixed(4)}° E`;
  document.getElementById("card-slope").innerText = `${site.local_terrain.slope_percent.toFixed(2)}%`;

  // Card 2
  document.getElementById("card-runoff-m3").innerText =
    `${water.estimated_annual_runoff_m3.toLocaleString()} m³`;
  document.getElementById("card-runoff-ml").innerText =
    `${water.estimated_annual_runoff_million_liters.toFixed(1)} ML`;
  document.getElementById("card-rainfall").innerText = `${water.annual_rainfall_mm.toFixed(1)} mm`;
  document.getElementById("card-runoff-c").innerText = `${water.runoff_coefficient.toFixed(2)}`;

  // Card 3
  document.getElementById("card-catch-ha").innerText = `${catchm.area_hectares.toFixed(1)} ha`;
  document.getElementById("card-catch-acres").innerText = `${catchm.area_acres.toFixed(1)} acres`;
  document.getElementById("card-elev-range").innerText =
    `${catchm.min_elevation_m.toFixed(1)} - ${catchm.max_elevation_m.toFixed(1)} m`;
  document.getElementById("card-catch-slope").innerText = `${catchm.average_slope_percent.toFixed(2)}%`;

  // Card 4
  document.getElementById("card-pond-depth").innerText = `${design.recommended_depth_m.toFixed(1)} m`;
  document.getElementById("card-excav-savings").innerText =
    `${design.excavation_savings_from_depression_percent.toFixed(1)}% Saved`;
  document.getElementById("card-pond-area").innerText =
    `${design.recommended_surface_area_hectares.toFixed(2)} ha`;
  document.getElementById("card-spillway-elev").innerText =
    `${site.associated_pour_point.coordinates.elevation_m.toFixed(1)} m`;
}

/**
 * Clears drawn items and resets to base view
 */
function clearAllDrawingsAndResults() {
  drawnItems.clearLayers();
  if (activeGeoJsonLayer) {
    map.removeLayer(activeGeoJsonLayer);
    activeGeoJsonLayer = null;
  }
  document.getElementById("results-hud").style.display = "none";
  currentSelectedGeometry = null;
  lastAnalysisResult = null;
  resetActiveToolButtons();

  if (surveyBoundaryLayer) {
    map.fitBounds(surveyBoundaryLayer.getBounds(), { padding: [35, 35] });
  } else if (defaultVillageData) {
    map.setView(defaultVillageData.center, 14);
  }
}

/**
 * Exports currently visualized GeoJSON
 */
function exportGeoJSON() {
  if (!lastAnalysisResult || !lastAnalysisResult.geojson) {
    alert("No active analysis result to export!");
    return;
  }
  const str = JSON.stringify(lastAnalysisResult.geojson, null, 2);
  downloadBlob(str, "village_catchment_pond_plan.geojson", "application/geo+json");
}

/**
 * Exports complete JSON analysis report
 */
function exportJSON() {
  if (!lastAnalysisResult) {
    alert("No active analysis result to export!");
    return;
  }
  const str = JSON.stringify(lastAnalysisResult, null, 2);
  downloadBlob(str, "village_pond_analysis_report.json", "application/json");
}

function downloadBlob(content, filename, contentType) {
  const blob = new Blob([content], { type: contentType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function showSpinner(msg = "Processing...") {
  const spin = document.getElementById("loading-spinner");
  const txt = document.getElementById("spinner-status-text");
  txt.innerText = msg;
  spin.style.display = "flex";
}

function hideSpinner() {
  document.getElementById("loading-spinner").style.display = "none";
}

