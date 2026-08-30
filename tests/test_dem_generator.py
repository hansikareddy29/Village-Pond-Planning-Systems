"""
Unit tests for DEM Generator and UTM Projector
"""

import os
import pytest
import numpy as np
from app.kml_parser import KMLParser
from app.dem_generator import DEMGenerator


@pytest.fixture
def sample_kml_data():
    parser = KMLParser()
    kml_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "contours_1m.kml"
    )
    with open(kml_path, "rb") as f:
        return parser.parse(f.read(), filename="contours_1m.kml")


def test_generate_dem_grid(sample_kml_data):
    gen = DEMGenerator(default_resolution_m=10.0)
    dem = gen.generate_dem(sample_kml_data)

    assert dem.rows > 0
    assert dem.cols > 0
    assert dem.resolution_m == 10.0
    assert dem.utm_zone == 44
    assert dem.utm_epsg == 32644
    assert dem.elevation.shape == (dem.rows, dem.cols)
    assert not np.any(np.isnan(dem.elevation))


def test_dem_georeferencing_roundtrip(sample_kml_data):
    gen = DEMGenerator(default_resolution_m=10.0)
    dem = gen.generate_dem(sample_kml_data)

    r, c = dem.rows // 2, dem.cols // 2
    lon, lat = dem.grid_to_wgs84(r, c)
    r_back, c_back = dem.wgs84_to_grid(lon, lat)

    assert abs(r - r_back) <= 1
    assert abs(c - c_back) <= 1
