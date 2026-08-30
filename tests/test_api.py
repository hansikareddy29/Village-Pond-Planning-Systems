"""
Integration tests for FastAPI REST Endpoints
"""

import os
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

    # Verify Catchment Summary Metrics
    catchment = data["catchment_summary"]
    assert catchment["area_hectares"] > 0
    assert catchment["area_sq_meters"] > 0
    assert catchment["perimeter_meters"] > 0
    assert catchment["estimated_annual_runoff_m3"] > 0

    # Verify Recommended Pond Location
    pond = data["recommended_pond_location"]
    assert "coordinates" in pond
    assert 20.0 <= pond["coordinates"]["latitude"] <= 22.0
    assert 80.0 <= pond["coordinates"]["longitude"] <= 82.0
    assert pond["suitability_score"] > 80.0
    assert len(pond["selection_rationale"]) > 10

    # Verify GeoJSON
    geojson = data["geojson"]
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) >= 3
