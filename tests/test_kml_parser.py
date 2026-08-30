"""
Unit tests for KML/KMZ Parser
"""

import os
import pytest
from app.kml_parser import KMLParser, KMLParseError


@pytest.fixture
def parser():
    return KMLParser()


def test_parse_sample_kml(parser):
    kml_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "contours_1m.kml")
    assert os.path.exists(kml_path)

    with open(kml_path, "rb") as f:
        data = parser.parse(f.read(), filename="contours_1m.kml")

    assert data["num_contours"] > 0
    assert len(data["point_cloud"]) > 1000
    assert data["contour_interval"] == 1.0
    assert data["bounds"]["min_elevation"] < data["bounds"]["max_elevation"]


def test_invalid_kml_raises_error(parser):
    with pytest.raises(KMLParseError):
        parser.parse(b"<invalid>xml</invalid>", filename="test.kml")
