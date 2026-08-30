"""
Synthetic & Unit Tests for Hydrology Engine
Tests:
- Test A: Straight downhill terrain
- Test B: Two branches merging at a confluence
- Test C: Exact catchment upstream tracing
- Test D: Depression and flat surface filling and routing
- Test E: Area & runoff metric consistency
"""

import numpy as np
import pytest
from app.hydrology import HydrologyEngine
from app.dem_generator import DEMGrid


@pytest.fixture
def hydrology():
    return HydrologyEngine()


def test_synthetic_straight_downhill(hydrology):
    """
    Test A: Straight downhill terrain (3x3 grid).
    10  9  8
     9  8  7
     8  7  6
    Flow moves towards lower elevations and accumulation increases downstream.
    """
    elev = np.array([
        [10.0, 9.0, 8.0],
        [ 9.0, 8.0, 7.0],
        [ 8.0, 7.0, 6.0]
    ], dtype=np.float64)

    flow_dir = hydrology.compute_flow_direction(elev, resolution_m=10.0)
    flow_acc = hydrology.compute_flow_accumulation(flow_dir)

    # The bottom-right corner (row 2, col 2) receives flow from all 9 cells
    assert flow_acc[2, 2] == 9.0
    # Headwater cell (0, 0) has accumulation 1.0
    assert flow_acc[0, 0] == 1.0
    # Strict monotonicity downstream
    assert flow_acc[0, 0] <= flow_acc[1, 1] <= flow_acc[2, 2]


def test_synthetic_confluence_merge(hydrology):
    """
    Test B: Two branches merging at a confluence (Y-shaped valley).
    10  5 10
     8  4  8
     7  3  7
     6  2  6
    Left and right ridges flow into the central valley stream.
    """
    elev = np.array([
        [10.0, 5.0, 10.0],
        [ 8.0, 4.0,  8.0],
        [ 7.0, 3.0,  7.0],
        [ 6.0, 2.0,  6.0]
    ], dtype=np.float64)

    flow_dir = hydrology.compute_flow_direction(elev, resolution_m=10.0)
    flow_acc = hydrology.compute_flow_accumulation(flow_dir)

    # Confluence cell (3, 1) must accumulate all 12 cells in the grid
    assert flow_acc[3, 1] == 12.0
    # Each row's center cell accumulates its row + upstream rows
    assert flow_acc[0, 1] == 3.0
    assert flow_acc[1, 1] == 6.0
    assert flow_acc[2, 1] == 9.0


def test_synthetic_catchment_delineation(hydrology):
    """
    Test C: Catchment Upstream Tracing.
    Verifies that the reverse flow graph from a pour point correctly delineates
    the exact contributing cells.
    """
    elev = np.array([
        [10.0, 5.0, 10.0],
        [ 8.0, 4.0,  8.0],
        [ 7.0, 3.0,  7.0],
        [ 6.0, 2.0,  6.0]
    ], dtype=np.float64)

    flow_dir = hydrology.compute_flow_direction(elev, resolution_m=10.0)
    flow_acc = hydrology.compute_flow_accumulation(flow_dir)

    # Construct mock DEMGrid
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

    # Delineate catchment for pour point at (2, 1)
    catchment_info = hydrology.delineate_catchment(pour_point_grid=(2, 1), flow_dir=flow_dir, dem=dem)

    # Cell count must match exactly the upstream accumulation at (2, 1) = 9 cells
    assert catchment_info['cell_count'] == 9
    assert catchment_info['cell_count'] == int(flow_acc[2, 1])
    assert catchment_info['area_sq_meters'] == 9 * 100.0  # 9 cells * 100 m^2/cell
    assert catchment_info['area_hectares'] == (9 * 100.0) / 10000.0


def test_synthetic_depression_filling_and_routing(hydrology):
    """
    Test D: Closed Depression / Pit Filling and Flat Routing.
    Center pit at (2, 2) has elevation 2.0 surrounded by 5.0, with perimeter spillway at (4, 2) elevation 7.0.
    10 10 10 10 10
    10  5  5  5 10
    10  5  2  5 10
    10  5  5  5 10
    10 10  7 10 10
    """
    elev = np.array([
        [10.0, 10.0, 10.0, 10.0, 10.0],
        [10.0,  5.0,  5.0,  5.0, 10.0],
        [10.0,  5.0,  2.0,  5.0, 10.0],
        [10.0,  5.0,  5.0,  5.0, 10.0],
        [10.0, 10.0,  7.0, 10.0, 10.0]
    ], dtype=np.float64)

    # Create mock DEMGrid
    x_coords = np.arange(0, 50, 10)
    y_coords = np.arange(0, 50, 10)
    dem = DEMGrid(elev, x_coords, y_coords, resolution_m=10.0, utm_epsg=32644, utm_zone=44, is_northern=True)

    filled, dep_depth = hydrology.fill_depressions(dem)

    # Verify pit was filled to spillway height 7.0 without arbitrary epsilon noise
    assert filled[2, 2] == 7.0
    assert dep_depth[2, 2] == 5.0  # 7.0 - 2.0 = 5.0m
    assert dep_depth[1, 1] == 2.0  # 7.0 - 5.0 = 2.0m
    assert dep_depth[0, 0] == 0.0  # boundary not depressed

    # Verify flow directions route across flat filled basin to the spillway outlet at (4, 2)
    flow_dir = hydrology.compute_flow_direction(filled, resolution_m=10.0)
    flow_acc = hydrology.compute_flow_accumulation(flow_dir)

    # All 25 cells must route out through the spillway (4, 2)
    assert flow_acc[4, 2] == 25.0


def test_area_unit_consistency(hydrology):
    """
    Test E: Unit conversions and Rational runoff calculations.
    """
    area_sq_m = 100000.0  # 10 ha
    runoff = hydrology.estimate_runoff(area_sq_m, annual_rainfall_mm=1000.0, runoff_coefficient=0.35)

    # V = C * P * A = 0.35 * 1.0m * 100,000 m^2 = 35,000 m^3
    assert runoff['estimated_annual_runoff_m3'] == 35000.0
    assert runoff['estimated_annual_runoff_million_liters'] == 35.0
