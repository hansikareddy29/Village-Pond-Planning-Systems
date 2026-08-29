"""
Unit tests for HydrologyEngine and Watershed Delineation
"""

import os
import pytest
import numpy as np
from app.kml_parser import KMLParser
from app.dem_generator import DEMGenerator
from app.hydrology import HydrologyEngine


@pytest.fixture(scope="module")
def dem_fixture():
    kml_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "contours_1m.kml"
    )
    parser = KMLParser()
    data = parser.parse(kml_path)
    dem_gen = DEMGenerator(default_resolution_m=10.0)
    return dem_gen.generate_dem(data)


def test_hydrology_analysis(dem_fixture):
    hydro = HydrologyEngine()
    results = hydro.analyze(dem_fixture)

    assert "filled_elevation" in results
    assert "flow_direction" in results
    assert "flow_accumulation" in results
    assert "streams" in results
    assert "depressions" in results

    assert results["flow_accumulation"].max() > 100
    assert len(results["depressions"]) > 0
    assert results["streams"]["geometry"]["type"] == "MultiLineString"


def test_catchment_delineation(dem_fixture):
    hydro = HydrologyEngine()
    results = hydro.analyze(dem_fixture)

    # Pick a high accumulation node
    flow_acc = results["flow_accumulation"]
    r_max, c_max = np.unravel_index(np.argmax(flow_acc), flow_acc.shape)

    catchment = hydro.delineate_catchment(
        (r_max, c_max), results["flow_direction"], dem_fixture
    )

    assert catchment["area_sq_meters"] > 0
    assert catchment["area_hectares"] > 0
    assert catchment["perimeter_meters"] > 0
    assert catchment["geojson"]["geometry"]["type"] in ["Polygon", "MultiPolygon"]
    assert catchment["min_elevation_m"] <= catchment["max_elevation_m"]


def test_runoff_estimation():
    hydro = HydrologyEngine()
    runoff = hydro.estimate_runoff(
        catchment_area_sq_m=100000.0,  # 10 ha
        annual_rainfall_mm=1000.0,
        runoff_coefficient=0.35,
    )

    # V = 100,000 * 1.0 * 0.35 = 35,000 m3
    assert runoff["estimated_annual_runoff_m3"] == 35000.0
    assert runoff["estimated_annual_runoff_liters"] == 35000000.0
    assert runoff["estimated_annual_runoff_million_liters"] == 35.0
