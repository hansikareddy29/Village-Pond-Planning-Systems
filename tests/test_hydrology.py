"""
Synthetic & Unit Tests for Hydrology Engine
"""

import numpy as np
import pytest
from app.hydrology import HydrologyEngine
from app.dem_generator import DEMGrid


@pytest.fixture
def hydrology():
    return HydrologyEngine()


def test_synthetic_straight_downhill(hydrology):
    elev = np.array([
        [10.0, 9.0, 8.0],
        [ 9.0, 8.0, 7.0],
        [ 8.0, 7.0, 6.0]
    ], dtype=np.float64)

    flow_dir = hydrology.compute_flow_direction(elev, resolution_m=10.0)
    flow_acc = hydrology.compute_flow_accumulation(flow_dir)

    assert flow_acc[2, 2] == 9.0
    assert flow_acc[0, 0] == 1.0
    assert flow_acc[0, 0] <= flow_acc[1, 1] <= flow_acc[2, 2]


def test_synthetic_confluence_merge(hydrology):
    elev = np.array([
        [10.0, 5.0, 10.0],
        [ 8.0, 4.0,  8.0],
        [ 7.0, 3.0,  7.0],
        [ 6.0, 2.0,  6.0]
    ], dtype=np.float64)

    flow_dir = hydrology.compute_flow_direction(elev, resolution_m=10.0)
    flow_acc = hydrology.compute_flow_accumulation(flow_dir)

    assert flow_acc[3, 1] == 12.0
    assert flow_acc[0, 1] == 3.0
    assert flow_acc[1, 1] == 6.0
    assert flow_acc[2, 1] == 9.0


def test_synthetic_catchment_delineation(hydrology):
    elev = np.array([
        [10.0, 5.0, 10.0],
        [ 8.0, 4.0,  8.0],
        [ 7.0, 3.0,  7.0],
        [ 6.0, 2.0,  6.0]
    ], dtype=np.float64)

    flow_dir = hydrology.compute_flow_direction(elev, resolution_m=10.0)
    flow_acc = hydrology.compute_flow_accumulation(flow_dir)

    x_coords = np.array([0.0, 10.0, 20.0])
    y_coords = np.array([0.0, 10.0, 20.0, 30.0])
    dem = DEMGrid(
        elevation=elev,
        x_coords=x_coords,
        y_coords=y_coords,
        resolution_m=10.0,
        utm_epsg=32644,
        utm_zone=44,
        is_northern=True
    )

    catchment_info = hydrology.delineate_catchment(pour_point_grid=(2, 1), flow_dir=flow_dir, dem=dem)

    assert catchment_info['cell_count'] == 9
    assert catchment_info['cell_count'] == int(flow_acc[2, 1])
    assert catchment_info['area_sq_meters'] == 9 * 100.0
    assert catchment_info['area_hectares'] == (9 * 100.0) / 10000.0


def test_synthetic_depression_filling_and_routing(hydrology):
    elev = np.array([
        [10.0, 10.0, 10.0, 10.0, 10.0],
        [10.0,  5.0,  5.0,  5.0, 10.0],
        [10.0,  5.0,  2.0,  5.0, 10.0],
        [10.0,  5.0,  5.0,  5.0, 10.0],
        [10.0, 10.0,  7.0, 10.0, 10.0]
    ], dtype=np.float64)

    x_coords = np.arange(0, 50, 10)
    y_coords = np.arange(0, 50, 10)
    dem = DEMGrid(elev, x_coords, y_coords, resolution_m=10.0, utm_epsg=32644, utm_zone=44, is_northern=True)

    filled, dep_depth = hydrology.fill_depressions(dem)

    assert filled[2, 2] == 7.0
    assert dep_depth[2, 2] == 5.0
    assert dep_depth[1, 1] == 2.0
    assert dep_depth[0, 0] == 0.0

    flow_dir = hydrology.compute_flow_direction(filled, resolution_m=10.0)
    flow_acc = hydrology.compute_flow_accumulation(flow_dir)

    assert flow_acc[4, 2] == 25.0


def test_area_unit_consistency(hydrology):
    area_sq_m = 100000.0
    runoff = hydrology.estimate_runoff(area_sq_m, annual_rainfall_mm=1000.0, runoff_coefficient=0.35)

    assert runoff['estimated_annual_runoff_m3'] == 35000.0
    assert runoff['estimated_annual_runoff_million_liters'] == 35.0
