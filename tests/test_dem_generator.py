"""
Unit tests for DEM Generator and Metric Coordinate Projections
"""

import os
import pytest
import numpy as np
from app.kml_parser import KMLParser
from app.dem_generator import DEMGenerator, DEMGrid


@pytest.fixture(scope="module")
def sample_kml_data():
    kml_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "contours_1m.kml")
    parser = KMLParser()
    return parser.parse(kml_path)


def test_generate_dem_grid(sample_kml_data):
    dem_gen = DEMGenerator(default_resolution_m=10.0)
    dem = dem_gen.generate_dem(sample_kml_data)

    assert isinstance(dem, DEMGrid)
    assert dem.rows > 100
    assert dem.cols > 100
    assert dem.resolution_m == 10.0
    assert dem.utm_epsg == 32644  # UTM Zone 44N for India ~81E, 21N
    assert dem.utm_zone == 44
    assert dem.is_northern is True


def test_dem_georeferencing_roundtrip(sample_kml_data):
    dem_gen = DEMGenerator(default_resolution_m=10.0)
    dem = dem_gen.generate_dem(sample_kml_data)

    # Pick center grid cell
    r_mid = dem.rows // 2
    c_mid = dem.cols // 2

    lon, lat = dem.grid_to_wgs84(r_mid, c_mid)
    assert 81.0 <= lon <= 82.0
    assert 21.0 <= lat <= 22.0

    r_calc, c_calc = dem.wgs84_to_grid(lon, lat)
    assert abs(r_calc - r_mid) <= 1
    assert abs(c_calc - c_mid) <= 1


def test_dem_terrain_stats(sample_kml_data):
    dem_gen = DEMGenerator(default_resolution_m=10.0)
    dem = dem_gen.generate_dem(sample_kml_data)

    stats = dem.stats
    assert stats['min_elevation'] >= 265.0
    assert stats['max_elevation'] <= 300.0
    assert stats['relief'] > 10.0
    assert stats['mean_slope_percent'] >= 0.0
    assert stats['total_grid_cells'] == dem.rows * dem.cols
