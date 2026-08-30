"""
Integration tests for FastAPI REST Endpoints
Tests:
- Health check
- OpenAPI Swagger redirect
- POST /analyzeContour with sample KML
- Separate pond_location and associated_pour_point verification
- GeoJSON feature types (catchment, drainage, pond_candidate, pour_point)
- Input parameter validations
- Direct GeoJSON format download
"""

import os
import json
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


def test_root_redirect_to_docs():
    response = client.get("/", follow_redirects=False)
    assert response.status_code in [302, 307]
    assert response.headers["location"] == "/docs"


def test_analyze_contour_endpoint():
    kml_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "contours_1m.kml")
    assert os.path.exists(kml_path), "contours_1m.kml must exist"

    with open(kml_path, "rb") as f:
        response = client.post(
            "/analyzeContour",
            files={"file": ("contours_1m.kml", f, "application/vnd.google-earth.kml+xml")},
            data={
                "grid_resolution_m": "10.0",
                "rainfall_annual_mm": "1000.0",
                "runoff_coefficient": "0.35",
                "pond_depth_m": "3.0",
                "num_candidate_sites": "5"
            }
        )

    assert response.status_code == 200, f"Error: {response.text}"
    data = response.json()

    assert data["success"] is True
    assert "execution_time_seconds" in data
    assert "metadata" in data
    assert "terrain_summary" in data
    assert "recommended_pond_location" in data
    assert "catchment_summary" in data
    assert "pond_design_recommendations" in data
    assert "geojson" in data

    # Verify Recommended Pond Location and Associated Pour Point separation
    pond = data["recommended_pond_location"]
    assert "coordinates" in pond
    assert "associated_pour_point" in pond
    assert "candidate_type" in pond
    assert 20.0 <= pond["coordinates"]["latitude"] <= 22.0
    assert 80.0 <= pond["coordinates"]["longitude"] <= 82.0
    assert pond["suitability_score"] > 80.0
    assert len(pond["selection_rationale"]) > 10

    pour = pond["associated_pour_point"]
    assert "coordinates" in pour
    assert "flow_accumulation_cells" in pour
    assert pour["flow_accumulation_cells"] > 0

    # Verify GeoJSON Features
    geojson = data["geojson"]
    assert geojson["type"] == "FeatureCollection"
    feature_types = [f["properties"].get("feature_type") for f in geojson["features"]]
    assert "catchment" in feature_types or "Catchment Boundary" in [f["properties"].get("name") for f in geojson["features"]]
    assert "drainage" in feature_types or "Drainage / Stream Network" in [f["properties"].get("name") for f in geojson["features"]]
    assert "pond_candidate" in feature_types
    assert "pour_point" in feature_types


def test_analyze_contour_geojson_format():
    kml_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "contours_1m.kml")
    with open(kml_path, "rb") as f:
        response = client.post(
            "/analyzeContour",
            files={"file": ("contours_1m.kml", f, "application/vnd.google-earth.kml+xml")},
            data={"format": "geojson"}
        )

    assert response.status_code == 200
    assert "application/geo+json" in response.headers["content-type"]
    geojson_data = json.loads(response.text)
    assert geojson_data["type"] == "FeatureCollection"
    assert len(geojson_data["features"]) >= 4


def test_parameter_validations():
    # Test invalid grid_resolution <= 0
    resp1 = client.post("/analyzeContour", data={"grid_resolution_m": "0.0"})
    assert resp1.status_code == 400
    assert "grid_resolution_m" in resp1.json()["detail"]

    # Test invalid runoff_coefficient > 1.0 or <= 0
    resp2 = client.post("/analyzeContour", data={"runoff_coefficient": "1.5"})
    assert resp2.status_code == 400
    assert "runoff_coefficient" in resp2.json()["detail"]

    # Test negative rainfall
    resp3 = client.post("/analyzeContour", data={"rainfall_annual_mm": "-100.0"})
    assert resp3.status_code == 400
    assert "rainfall_annual_mm" in resp3.json()["detail"]
