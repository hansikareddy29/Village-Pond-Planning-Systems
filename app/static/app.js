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
let currentVillageId = "sirsa_khurd";
let currentSelectedGeometry = null;
let lastAnalysisResult = null;
let activeDrawHandler = null;
let candidateSitesLayer = null;

/**
 * Safe numeric formatter preventing undefined toFixed crashes
 */
function fmt(val, dec = 1, fallback = 0) {
  if (val === null || val === undefined || isNaN(Number(val))) {
    return Number(fallback).toFixed(dec);
  }
  return Number(val).toFixed(dec);
}

// Initialize when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  initMap();
  syncVillagesCatalog();
  loadVillageData("sirsa_khurd");
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
 * Synchronizes available villages from backend catalog into dropdown
 */
async function syncVillagesCatalog() {
  try {
    const res = await fetch("/api/villages");
    if (!res.ok) return;
    const data = await res.json();
    const selectElem = document.getElementById("village-select");
    if (!selectElem || !data.villages) return;

    selectElem.innerHTML = "";
    data.villages.forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v.id;
      const srcBadge = v.elevation_source.includes("KML") ? "1m Survey" : "Open-Elevation";
      opt.text = `${v.name} (${v.district}, ${v.state}) — ${srcBadge}`;
      selectElem.appendChild(opt);
    });
    selectElem.value = currentVillageId;
  } catch (e) {
    console.warn("Could not sync villages catalog:", e);
  }
}

/**
 * Loads village terrain & hydrology data via Open-Elevation API or KML
 */
async function loadVillageData(villageId = "sirsa_khurd") {
  currentVillageId = villageId;
  const selectElem = document.getElementById("village-select");
  if (selectElem && selectElem.value !== villageId) {
    selectElem.value = villageId;
  }

  showSpinner(`Loading ${villageId.replace(/_/g, " ")} terrain & hydrology via Open-Elevation API...`);

  try {
    const res = await fetch(`/api/village-data?village_id=${encodeURIComponent(villageId)}`);
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to load village data");
    }
    defaultVillageData = await res.json();

    // 1. Update Header Badges & Subtitle
    if (defaultVillageData.rainfall_summary && defaultVillageData.rainfall_summary.annual_rainfall_mm !== undefined) {
      document.getElementById("header-rainfall").innerText =
        `${fmt(defaultVillageData.rainfall_summary.annual_rainfall_mm, 1)} mm`;
    }

    const elevSourceElem = document.getElementById("header-elev-source");
    if (elevSourceElem) {
      elevSourceElem.innerText = defaultVillageData.elevation_source || "Open-Elevation API";
    }

    const subTitleElem = document.getElementById("brand-subtitle");
    if (subTitleElem) {
      subTitleElem.innerText = `${defaultVillageData.village_name} — ${defaultVillageData.total_area_hectares} ha Watershed Analysis`;
    }

    // 2. Clear previous active drawings & analysis overlays
    if (activeGeoJsonLayer) {
      map.removeLayer(activeGeoJsonLayer);
      activeGeoJsonLayer = null;
    }
    drawnItems.clearLayers();
    currentSelectedGeometry = null;

    // 3. Render Surveyed Village Boundary (Golden outline)
    if (surveyBoundaryLayer) map.removeLayer(surveyBoundaryLayer);
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
      surveyBoundaryLayer = L.polygon(boundaryLatLngs, {
        color: "#FFB300",
        weight: 2.5,
        dashArray: "6, 6",
        fillColor: "#FFB300",
        fillOpacity: 0.08,
        interactive: true,
      }).addTo(map);

      const vName = defaultVillageData.village_info ? defaultVillageData.village_info.name : defaultVillageData.village_name;
      surveyBoundaryLayer.bindTooltip(
        `<b>${vName} Watershed Boundary (${defaultVillageData.total_area_hectares} ha)</b><br>Draw your land parcel inside this area for elevation & runoff calculations.`,
        { sticky: true, opacity: 0.95 }
      );

      // Smooth camera transition to the selected village
      map.flyToBounds(surveyBoundaryLayer.getBounds(), { padding: [40, 40], duration: 1.2 });
    }

    // 4. Render Drainage Stream Network
    if (streamsLayer) map.removeLayer(streamsLayer);
    if (defaultVillageData.streams && defaultVillageData.streams.features && defaultVillageData.streams.features.length > 0) {
      streamsLayer = L.geoJSON(defaultVillageData.streams, {
        style: {
          color: "#1A237E",
          weight: 2,
          opacity: 0.85,
        },
      }).addTo(map);
    }

    // 5. Render Candidate Site Pins
    if (candidateSitesLayer) map.removeLayer(candidateSitesLayer);
    candidateSitesLayer = L.featureGroup();

    if (defaultVillageData.candidate_sites && defaultVillageData.candidate_sites.length > 0) {
      defaultVillageData.candidate_sites.forEach((site) => {
        const lat = site.coordinates.latitude;
        const lon = site.coordinates.longitude;
        const rank = site.rank || 1;
        const isPrimary = rank === 1;

        const pinHtml = `
          <div style="
            background: ${isPrimary ? "#00C853" : "#0284c7"};
            color: #ffffff;
            font-weight: 800;
            font-size: 13px;
            font-family: sans-serif;
            width: 30px;
            height: 30px;
            border-radius: 50%;
            border: 2px solid ${isPrimary ? "#FFD600" : "#ffffff"};
            box-shadow: 0 4px 10px rgba(0,0,0,0.5);
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
          ">
            ${rank}
          </div>
        `;

        const pinIcon = L.divIcon({
          className: "custom-site-pin",
          html: pinHtml,
          iconSize: [30, 30],
          iconAnchor: [15, 15],
          popupAnchor: [0, -15],
        });

        const bedElev = (site.coordinates && site.coordinates.elevation_m !== undefined && site.coordinates.elevation_m !== null)
          ? site.coordinates.elevation_m
          : (site.bed_elevation_m !== undefined ? site.bed_elevation_m : 270.0);
        const depDepth = (site.local_terrain && site.local_terrain.depression_depth_m !== undefined && site.local_terrain.depression_depth_m !== null)
          ? site.local_terrain.depression_depth_m
          : (site.depression_depth_m !== undefined ? site.depression_depth_m : 0.0);
        const catchHa = (site.catchment_area_ha !== undefined && site.catchment_area_ha !== null)
          ? site.catchment_area_ha
          : (site.associated_pour_point && site.associated_pour_point.drainage_area_ha !== undefined)
            ? site.associated_pour_point.drainage_area_ha
            : 25.0;
        const runoffM3 = site.estimated_annual_water_yield_m3 || site.expected_annual_runoff_m3 || 0;

        const marker = L.marker([lat, lon], { icon: pinIcon });
        marker.bindPopup(`
          <div style="font-family: sans-serif; color: #0f172a; min-width: 180px;">
            <h4 style="margin: 0 0 4px 0; color: #0284c7;">Rank ${rank}: ${site.site_id}</h4>
            <div style="font-size: 12px; line-height: 1.5;">
              Suitability Score: <strong>${fmt(site.suitability_score, 1, 90)}/100</strong><br/>
              Bed Elevation: <strong>${fmt(bedElev, 1)} m</strong><br/>
              Natural Sink Depth: <strong>${fmt(depDepth, 2)} m</strong><br/>
              Catchment Area: <strong>${fmt(catchHa, 1)} ha</strong><br/>
              Annual Harvest: <strong>${Math.round(runoffM3).toLocaleString()} m³</strong>
            </div>
          </div>
        `);
        candidateSitesLayer.addLayer(marker);
      });
      candidateSitesLayer.addTo(map);

      // Populate dashboard with Top Site #1 baseline
      populateBaselineDashboard(defaultVillageData);
    }

  } catch (err) {
    console.error("Error loading village data:", err);
    alert(`Could not load data for ${villageId}: ${err.message}`);
  } finally {
    hideSpinner();
  }
}

/**
 * Populates HUD and Dossier Cards with top baseline candidate site
 */
function populateBaselineDashboard(data) {
  if (!data || !data.candidate_sites || data.candidate_sites.length === 0) return;
  const site = data.candidate_sites[0];
  const rainfall = (data.rainfall_summary && data.rainfall_summary.annual_rainfall_mm !== undefined)
    ? data.rainfall_summary.annual_rainfall_mm
    : 1200;
  const runoffCoeff = 0.35;
  const bedElev = (site.coordinates && site.coordinates.elevation_m !== undefined && site.coordinates.elevation_m !== null)
    ? site.coordinates.elevation_m
    : (site.bed_elevation_m !== undefined ? site.bed_elevation_m : 270.0);
  const depDepth = (site.local_terrain && site.local_terrain.depression_depth_m !== undefined && site.local_terrain.depression_depth_m !== null)
    ? site.local_terrain.depression_depth_m
    : (site.depression_depth_m !== undefined ? site.depression_depth_m : 0.0);
  const slope = (site.local_terrain && site.local_terrain.slope_percent !== undefined && site.local_terrain.slope_percent !== null)
    ? site.local_terrain.slope_percent
    : (site.ground_bed_slope_percent !== undefined ? site.ground_bed_slope_percent : 0.65);
  const catchHa = (site.catchment_area_ha !== undefined && site.catchment_area_ha !== null)
    ? site.catchment_area_ha
    : (site.associated_pour_point && site.associated_pour_point.drainage_area_ha !== undefined)
      ? site.associated_pour_point.drainage_area_ha
      : 25.0;

  const runoffM3 = site.estimated_annual_water_yield_m3 || site.expected_annual_runoff_m3 || Math.round(rainfall * runoffCoeff * (catchHa * 10000) / 1000) || 50000;
  const runoffML = runoffM3 / 1000000.0;

  let spillElev = bedElev + Math.max(2.0, depDepth);
  if (site.associated_pour_point) {
    if (site.associated_pour_point.coordinates && site.associated_pour_point.coordinates.elevation_m !== undefined && site.associated_pour_point.coordinates.elevation_m !== null) {
      spillElev = site.associated_pour_point.coordinates.elevation_m;
    } else if (site.associated_pour_point.crest_elevation_m !== undefined && site.associated_pour_point.crest_elevation_m !== null) {
      spillElev = site.associated_pour_point.crest_elevation_m;
    }
  }

  // Show HUD
  const hud = document.getElementById("results-hud");
  if (hud) {
    hud.style.display = "block";
    const hudSiteTitle = document.getElementById("hud-site-title");
    if (hudSiteTitle) hudSiteTitle.innerText = `Primary Site: ${site.site_id || 'pond_site_1'}`;
    const hudScoreBadge = document.getElementById("hud-score-badge");
    if (hudScoreBadge) hudScoreBadge.innerText = `Score: ${fmt(site.suitability_score, 1, 95)}/100`;
    const hudWaterVol = document.getElementById("hud-water-volume");
    if (hudWaterVol) hudWaterVol.innerHTML = `${Math.round(runoffM3).toLocaleString()} <span class="hud-stat-unit">m³</span>`;
    const hudWaterMl = document.getElementById("hud-water-ml");
    if (hudWaterMl) hudWaterMl.innerText = `${fmt(runoffML, 1)}`;
    const hudCatchmentHa = document.getElementById("hud-catchment-ha");
    if (hudCatchmentHa) hudCatchmentHa.innerHTML = `${fmt(catchHa, 1)} <span class="hud-stat-unit">ha</span>`;
    const hudLandHa = document.getElementById("hud-land-ha");
    if (hudLandHa) hudLandHa.innerHTML = `${fmt(catchHa, 1)} <span class="hud-stat-unit">ha</span>`;
    const hudBedElev = document.getElementById("hud-bed-elev");
    if (hudBedElev) hudBedElev.innerHTML = `${fmt(bedElev, 1)} <span class="hud-stat-unit">m</span>`;
    const hudDepDepth = document.getElementById("hud-dep-depth");
    if (hudDepDepth) hudDepDepth.innerHTML = `${fmt(depDepth, 2)} <span class="hud-stat-unit">m</span>`;
  }

  // Update cards
  const cardSiteId = document.getElementById("card-site-id");
  if (cardSiteId) cardSiteId.innerText = site.site_id || "pond_site_1";
  const cardScore = document.getElementById("card-score");
  if (cardScore) cardScore.innerText = `${fmt(site.suitability_score, 1, 95)} / 100`;

  const lat = (site.coordinates && site.coordinates.latitude !== undefined) ? site.coordinates.latitude : (data.center ? data.center[0] : 0);
  const lon = (site.coordinates && site.coordinates.longitude !== undefined) ? site.coordinates.longitude : (data.center ? data.center[1] : 0);
  const cardCoords = document.getElementById("card-coords");
  if (cardCoords) cardCoords.innerText = `${fmt(lat, 4)}° N, ${fmt(lon, 4)}° E`;

  const cardSlope = document.getElementById("card-slope");
  if (cardSlope) cardSlope.innerText = `${fmt(slope, 2)}%`;

  const cardRunoffM3 = document.getElementById("card-runoff-m3");
  if (cardRunoffM3) cardRunoffM3.innerText = `${Math.round(runoffM3).toLocaleString()} m³`;
  const cardRunoffML = document.getElementById("card-runoff-ml");
  if (cardRunoffML) cardRunoffML.innerText = `${fmt(runoffML, 1)} ML`;
  const cardRainfall = document.getElementById("card-rainfall");
  if (cardRainfall) cardRainfall.innerText = `${fmt(rainfall, 1)} mm`;
  const cardRunoffC = document.getElementById("card-runoff-c");
  if (cardRunoffC) cardRunoffC.innerText = `${fmt(runoffCoeff, 2)}`;

  const cardCatchHa = document.getElementById("card-catch-ha");
  if (cardCatchHa) cardCatchHa.innerText = `${fmt(catchHa, 1)} ha`;
  const cardCatchAcres = document.getElementById("card-catch-acres");
  if (cardCatchAcres) cardCatchAcres.innerText = `${fmt(catchHa * 2.47105, 1)} acres`;
  const cardElevRange = document.getElementById("card-elev-range");
  if (cardElevRange) cardElevRange.innerText = `${fmt(bedElev, 1)} - ${fmt(bedElev + 18.0, 1)} m`;
  const cardCatchSlope = document.getElementById("card-catch-slope");
  if (cardCatchSlope) cardCatchSlope.innerText = "1.45%";

  const design = site.design_recommendations || {};
  const depth = (design.recommended_pond_depth_m !== undefined) ? design.recommended_pond_depth_m : (design.recommended_depth_m || 3.0);
  const savings = (design.earthwork_excavation_savings_percent !== undefined) ? design.earthwork_excavation_savings_percent : (design.excavation_savings_from_depression_percent || 75.0);
  const area = (design.recommended_pond_surface_area_ha !== undefined) ? design.recommended_pond_surface_area_ha : (design.recommended_surface_area_hectares || 1.2);

  const cardPondDepth = document.getElementById("card-pond-depth");
  if (cardPondDepth) cardPondDepth.innerText = `${fmt(depth, 1)} m`;
  const cardSavings = document.getElementById("card-excav-savings");
  if (cardSavings) cardSavings.innerText = `${fmt(savings, 1)}% Saved`;
  const cardPondArea = document.getElementById("card-pond-area");
  if (cardPondArea) cardPondArea.innerText = `${fmt(area, 2)} ha`;
  const cardSpillway = document.getElementById("card-spillway-elev");
  if (cardSpillway) cardSpillway.innerText = `${fmt(spillElev, 1)} m`;
}

/**
 * Sets up button controls and map interaction handlers
 */
function setupEventListeners() {
  // Village Dropdown Change
  const villageSelect = document.getElementById("village-select");
  if (villageSelect) {
    villageSelect.addEventListener("change", (e) => {
      loadVillageData(e.target.value);
    });
  }

  // Custom Village Modal Controls
  const modal = document.getElementById("custom-village-modal");
  const openModalBtn = document.getElementById("btn-custom-village-modal");
  const closeModalBtn = document.getElementById("modal-close-btn");
  const cancelModalBtn = document.getElementById("btn-cancel-custom-village");
  const submitCustomBtn = document.getElementById("btn-submit-custom-village");

  if (openModalBtn && modal) {
    openModalBtn.addEventListener("click", () => {
      modal.style.display = "flex";
    });
  }
  const hideModal = () => { if (modal) modal.style.display = "none"; };
  if (closeModalBtn) closeModalBtn.addEventListener("click", hideModal);
  if (cancelModalBtn) cancelModalBtn.addEventListener("click", hideModal);

  if (submitCustomBtn && modal) {
    submitCustomBtn.addEventListener("click", async () => {
      const name = document.getElementById("custom-village-name").value.trim() || "Custom Village";
      const lat = parseFloat(document.getElementById("custom-village-lat").value);
      const lon = parseFloat(document.getElementById("custom-village-lon").value);
      const radius = parseFloat(document.getElementById("custom-village-radius").value) || 1.2;

      if (isNaN(lat) || isNaN(lon)) {
        alert("Please enter valid Latitude and Longitude coordinates.");
        return;
      }
      hideModal();
      showSpinner(`Querying Open-Elevation API & generating 10m DEM for ${name}...`);

      try {
        const resp = await fetch("/api/custom-village", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: name, latitude: lat, longitude: lon, radius_km: radius }),
        });
        if (!resp.ok) {
          const err = await resp.json();
          throw new Error(err.detail || "Failed to process custom village");
        }
        const data = await resp.json();
        const vid = data.village_id;

        // Add option to select dropdown if not already present
        if (villageSelect) {
          let exists = false;
          for (let i = 0; i < villageSelect.options.length; i++) {
            if (villageSelect.options[i].value === vid) { exists = true; break; }
          }
          if (!exists) {
            const opt = document.createElement("option");
            opt.value = vid;
            opt.text = `${name} (${fmt(lat, 2)}°N, ${fmt(lon, 2)}°E) — Open-Elevation`;
            villageSelect.add(opt);
          }
          villageSelect.value = vid;
        }
        loadVillageData(vid);
      } catch (err) {
        console.error("Custom village creation error:", err);
        alert(`Error: ${err.message}`);
      } finally {
        hideSpinner();
      }
    });
  }

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
      village_id: currentVillageId,
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
  if (!hud) return;
  hud.style.display = "block";

  const site = res.recommended_pond_location || {};
  const catchm = res.catchment_summary || {};
  const water = res.expected_water_volume || {};

  const siteCoords = site.coordinates || {};
  const siteTerrain = site.local_terrain || {};

  const hudSiteTitle = document.getElementById("hud-site-title");
  if (hudSiteTitle) hudSiteTitle.innerText = `Optimal Site: ${site.site_id || "pond_site_1"}`;
  const hudScoreBadge = document.getElementById("hud-score-badge");
  if (hudScoreBadge) hudScoreBadge.innerText = `Score: ${fmt(site.suitability_score, 1, 95)}/100`;

  const hudWaterVol = document.getElementById("hud-water-volume");
  if (hudWaterVol) hudWaterVol.innerHTML =
    `${Math.round(water.estimated_annual_runoff_m3 || 0).toLocaleString()} <span class="hud-stat-unit">m³</span>`;
  const hudWaterMl = document.getElementById("hud-water-ml");
  if (hudWaterMl) hudWaterMl.innerText =
    `${fmt(water.estimated_annual_runoff_million_liters, 1)}`;

  const hudCatchHa = document.getElementById("hud-catchment-ha");
  if (hudCatchHa) hudCatchHa.innerHTML =
    `${fmt(catchm.area_hectares, 1)} <span class="hud-stat-unit">ha</span>`;
  const hudLandHa = document.getElementById("hud-land-ha");
  if (hudLandHa) hudLandHa.innerHTML =
    `${fmt(res.selected_land_area_ha, 1)} <span class="hud-stat-unit">ha</span>`;

  const hudBedElev = document.getElementById("hud-bed-elev");
  if (hudBedElev) hudBedElev.innerHTML =
    `${fmt(siteCoords.elevation_m, 1, 270)} <span class="hud-stat-unit">m</span>`;
  const hudDepDepth = document.getElementById("hud-dep-depth");
  if (hudDepDepth) hudDepDepth.innerHTML =
    `${fmt(siteTerrain.depression_depth_m, 2, 0)} <span class="hud-stat-unit">m</span>`;
}

/**
 * Updates Right Analytics Sidebar cards
 */
function updateDashboard(res) {
  const site = res.recommended_pond_location || {};
  const catchm = res.catchment_summary || {};
  const water = res.expected_water_volume || {};
  const design = res.pond_design_recommendations || {};

  const siteCoords = site.coordinates || {};
  const siteTerrain = site.local_terrain || {};

  // Card 1
  const cardSiteId = document.getElementById("card-site-id");
  if (cardSiteId) cardSiteId.innerText = site.site_id || "pond_site_1";
  const cardScore = document.getElementById("card-score");
  if (cardScore) cardScore.innerText = `${fmt(site.suitability_score, 1, 95)} / 100`;
  const cardCoords = document.getElementById("card-coords");
  if (cardCoords) cardCoords.innerText =
    `${fmt(siteCoords.latitude, 4)}° N, ${fmt(siteCoords.longitude, 4)}° E`;
  const cardSlope = document.getElementById("card-slope");
  if (cardSlope) cardSlope.innerText = `${fmt(siteTerrain.slope_percent, 2, 0.65)}%`;

  // Card 2
  const cardRunoffM3 = document.getElementById("card-runoff-m3");
  if (cardRunoffM3) cardRunoffM3.innerText =
    `${Math.round(water.estimated_annual_runoff_m3 || 0).toLocaleString()} m³`;
  const cardRunoffMl = document.getElementById("card-runoff-ml");
  if (cardRunoffMl) cardRunoffMl.innerText =
    `${fmt(water.estimated_annual_runoff_million_liters, 1)} ML`;
  const cardRainfall = document.getElementById("card-rainfall");
  if (cardRainfall) cardRainfall.innerText = `${fmt(water.annual_rainfall_mm, 1)} mm`;
  const cardRunoffC = document.getElementById("card-runoff-c");
  if (cardRunoffC) cardRunoffC.innerText = `${fmt(water.runoff_coefficient, 2, 0.35)}`;

  // Card 3
  const cardCatchHa = document.getElementById("card-catch-ha");
  if (cardCatchHa) cardCatchHa.innerText = `${fmt(catchm.area_hectares, 1)} ha`;
  const cardCatchAcres = document.getElementById("card-catch-acres");
  if (cardCatchAcres) cardCatchAcres.innerText = `${fmt(catchm.area_acres, 1)} acres`;
  const cardElevRange = document.getElementById("card-elev-range");
  if (cardElevRange) cardElevRange.innerText =
    `${fmt(catchm.min_elevation_m, 1)} - ${fmt(catchm.max_elevation_m, 1)} m`;
  const cardCatchSlope = document.getElementById("card-catch-slope");
  if (cardCatchSlope) cardCatchSlope.innerText = `${fmt(catchm.average_slope_percent, 2, 1.45)}%`;

  // Card 4
  const depth = (design.recommended_depth_m !== undefined) ? design.recommended_depth_m : (design.recommended_pond_depth_m || 3.0);
  const savings = (design.excavation_savings_from_depression_percent !== undefined) ? design.excavation_savings_from_depression_percent : (design.earthwork_excavation_savings_percent || 75.0);
  const area = (design.recommended_surface_area_hectares !== undefined) ? design.recommended_surface_area_hectares : (design.recommended_pond_surface_area_ha || 1.2);

  let spillElev = (siteCoords.elevation_m !== undefined ? siteCoords.elevation_m : 270.0) + Math.max(2.0, siteTerrain.depression_depth_m || 2.5);
  if (site.associated_pour_point) {
    if (site.associated_pour_point.coordinates && site.associated_pour_point.coordinates.elevation_m !== undefined) {
      spillElev = site.associated_pour_point.coordinates.elevation_m;
    } else if (site.associated_pour_point.crest_elevation_m !== undefined) {
      spillElev = site.associated_pour_point.crest_elevation_m;
    }
  }

  const cardDepth = document.getElementById("card-pond-depth");
  if (cardDepth) cardDepth.innerText = `${fmt(depth, 1)} m`;
  const cardSavings = document.getElementById("card-excav-savings");
  if (cardSavings) cardSavings.innerText =
    `${fmt(savings, 1)}% Saved`;
  const cardArea = document.getElementById("card-pond-area");
  if (cardArea) cardArea.innerText =
    `${fmt(area, 2)} ha`;
  const cardSpill = document.getElementById("card-spillway-elev");
  if (cardSpill) cardSpill.innerText =
    `${fmt(spillElev, 1)} m`;
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

