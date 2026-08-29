"""
Unit tests for KML & KMZ parser
"""

import os
import io
import zipfile
import pytest
from app.kml_parser import KMLParser, KMLParseError


def test_parse_sample_kml():
    kml_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "contours_1m.kml")
    assert os.path.exists(kml_path), "Sample KML file contours_1m.kml must exist"

    parser = KMLParser()
    result = parser.parse(kml_path)

    assert result['num_contours'] > 0
    assert len(result['point_cloud']) > 1000
    assert result['bounds']['min_elevation'] >= 200.0
    assert result['bounds']['max_elevation'] <= 350.0
    assert result['contour_interval'] == 1.0
    assert result['boundary_polygon'] is not None


def test_parse_in_memory_bytes():
    sample_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
      <Document>
        <Placemark>
          <name>250.0</name>
          <LineString>
            <coordinates>81.28,21.24,250.0 81.29,21.25,250.0</coordinates>
          </LineString>
        </Placemark>
        <Placemark>
          <name>255.0</name>
          <LineString>
            <coordinates>81.28,21.26,255.0 81.29,21.27,255.0</coordinates>
          </LineString>
        </Placemark>
      </Document>
    </kml>"""

    parser = KMLParser()
    result = parser.parse(sample_xml)

    assert result['num_contours'] == 2
    assert result['bounds']['min_elevation'] == 250.0
    assert result['bounds']['max_elevation'] == 255.0


def test_parse_kmz_archive():
    sample_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
      <Document>
        <Placemark>
          <name>300.0</name>
          <LineString>
            <coordinates>80.0,20.0,300.0 80.1,20.1,300.0</coordinates>
          </LineString>
        </Placemark>
      </Document>
    </kml>"""

    kmz_buf = io.BytesIO()
    with zipfile.ZipFile(kmz_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('doc.kml', sample_xml)

    parser = KMLParser()
    result = parser.parse(kmz_buf.getvalue(), filename="test.kmz")

    assert result['num_contours'] == 1
    assert result['bounds']['min_elevation'] == 300.0


def test_invalid_kml_raises_error():
    parser = KMLParser()
    with pytest.raises(KMLParseError):
        parser.parse(b"<invalid>not a kml</invalid>")
