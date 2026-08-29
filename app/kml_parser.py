"""
KML and KMZ Parser Module
Extracts 3D contour lines, elevation values, coordinates, and survey boundaries
from standard KML and KMZ files.
"""

import os
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import List, Dict, Tuple, Optional, Any
import numpy as np


class KMLParseError(Exception):
    """Exception raised when KML parsing fails."""

    pass


class ContourFeature:
    """Represents a single contour line with its elevation and coordinates."""

    def __init__(
        self,
        elevation: float,
        coordinates: List[Tuple[float, float, Optional[float]]],
        feature_id: Optional[str] = None,
    ):
        self.elevation = float(elevation)
        self.coordinates = coordinates  # list of (lon, lat) or (lon, lat, alt)
        self.feature_id = feature_id

    @property
    def lons(self) -> List[float]:
        return [pt[0] for pt in self.coordinates]

    @property
    def lats(self) -> List[float]:
        return [pt[1] for pt in self.coordinates]


class KMLParser:
    """
    Generalized parser for KML and KMZ files containing contour maps.
    Handles various naming conventions, ExtendedData schemas, and 3D coordinate tuples.
    """

    def __init__(self):
        self.namespaces = {
            "kml": "http://www.opengis.net/kml/2.2",
            "atom": "http://www.w3.org/2005/Atom",
            "gx": "http://www.google.com/kml/ext/2.2",
        }

    def parse(
        self, file_path_or_bytes: Any, filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Parse KML or KMZ file from path or bytes.
        Returns a dictionary with extracted contours, boundary, metadata, and 3D point cloud.
        """
        xml_content = self._extract_xml(file_path_or_bytes, filename)
        return self._parse_xml_content(xml_content)

    def _extract_xml(self, file_source: Any, filename: Optional[str] = None) -> bytes:
        """Extract XML bytes from a filepath, KMZ zip archive, or bytes object."""
        if isinstance(file_source, str):
            if not os.path.exists(file_source):
                raise KMLParseError(f"File not found: {file_source}")

            # Check if KMZ (zip archive)
            if zipfile.is_zipfile(file_source) or file_source.lower().endswith(".kmz"):
                return self._extract_kml_from_kmz(file_source)
            with open(file_source, "rb") as f:
                return f.read()

        elif isinstance(file_source, bytes):
            # Check if bytes are a ZIP archive (KMZ)
            import io

            if zipfile.is_zipfile(io.BytesIO(file_source)) or (
                filename and filename.lower().endswith(".kmz")
            ):
                return self._extract_kml_from_kmz_bytes(file_source)
            return file_source
        else:
            raise KMLParseError(
                "Unsupported file input type. Expected file path or bytes."
            )

    def _extract_kml_from_kmz(self, kmz_path: str) -> bytes:
        """Extract the primary .kml file from a .kmz archive."""
        with zipfile.ZipFile(kmz_path, "r") as zf:
            kml_files = [f for f in zf.namelist() if f.lower().endswith(".kml")]
            if not kml_files:
                raise KMLParseError("No .kml file found inside KMZ archive.")
            # Prefer doc.kml if present, else first kml
            target_kml = "doc.kml" if "doc.kml" in kml_files else kml_files[0]
            return zf.read(target_kml)

    def _extract_kml_from_kmz_bytes(self, kmz_bytes: bytes) -> bytes:
        """Extract primary .kml from KMZ bytes in-memory."""
        import io

        with zipfile.ZipFile(io.BytesIO(kmz_bytes), "r") as zf:
            kml_files = [f for f in zf.namelist() if f.lower().endswith(".kml")]
            if not kml_files:
                raise KMLParseError("No .kml file found inside KMZ archive.")
            target_kml = "doc.kml" if "doc.kml" in kml_files else kml_files[0]
            return zf.read(target_kml)

    def _parse_xml_content(self, xml_bytes: bytes) -> Dict[str, Any]:
        """Parse XML element tree and extract all contours and features."""
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as e:
            raise KMLParseError(f"Malformed XML in KML file: {str(e)}")

        contours: List[ContourFeature] = []
        boundary_polygon: Optional[List[Tuple[float, float]]] = None
        point_cloud_pts: List[Tuple[float, float, float]] = []  # (lon, lat, elev)
        all_lons: List[float] = []
        all_lats: List[float] = []
        all_elevs: List[float] = []

        # Iterate through all Placemarks
        for elem in root.iter():
            if elem.tag.endswith("Placemark"):
                self._process_placemark(
                    elem, contours, point_cloud_pts, all_lons, all_lats, all_elevs
                )

        # Check for boundary polygon (e.g. named 'land' or outer boundary)
        for elem in root.iter():
            if elem.tag.endswith("Placemark"):
                name_elem = elem.find(".//{*}name")
                if (
                    name_elem is not None
                    and name_elem.text
                    and name_elem.text.strip().lower()
                    in ["land", "boundary", "area", "village_boundary"]
                ):
                    poly_coords = elem.find(
                        ".//{*}Polygon//{*}outerBoundaryIs//{*}coordinates"
                    )
                    if poly_coords is not None and poly_coords.text:
                        boundary_polygon = self._parse_coordinate_string(
                            poly_coords.text
                        )

        if not contours and not point_cloud_pts:
            raise KMLParseError(
                "No valid contour lines or elevation data found in the KML file."
            )

        min_lon = min(all_lons) if all_lons else 0.0
        max_lon = max(all_lons) if all_lons else 0.0
        min_lat = min(all_lats) if all_lats else 0.0
        max_lat = max(all_lats) if all_lats else 0.0
        min_elev = min(all_elevs) if all_elevs else 0.0
        max_elev = max(all_elevs) if all_elevs else 0.0

        unique_elevations = sorted(list(set(all_elevs)))
        contour_interval = self._estimate_contour_interval(unique_elevations)

        return {
            "contours": contours,
            "num_contours": len(contours),
            "boundary_polygon": boundary_polygon,
            "point_cloud": (
                np.array(point_cloud_pts) if point_cloud_pts else np.empty((0, 3))
            ),
            "bounds": {
                "min_lon": min_lon,
                "max_lon": max_lon,
                "min_lat": min_lat,
                "max_lat": max_lat,
                "min_elevation": min_elev,
                "max_elevation": max_elev,
                "elevation_range": max_elev - min_elev,
                "center_lon": (min_lon + max_lon) / 2.0,
                "center_lat": (min_lat + max_lat) / 2.0,
            },
            "unique_elevations": unique_elevations,
            "contour_interval": contour_interval,
        }

    def _process_placemark(
        self,
        placemark: ET.Element,
        contours: List[ContourFeature],
        point_cloud: List[Tuple[float, float, float]],
        all_lons: List[float],
        all_lats: List[float],
        all_elevs: List[float],
    ):
        """Extract contour geometries and elevation from a Placemark element."""
        # 1. Determine elevation from Placemark attributes
        elevation = self._extract_elevation(placemark)

        # 2. Extract line coordinates (LineString or MultiGeometry)
        line_elements = placemark.findall(".//{*}LineString")
        poly_elements = placemark.findall(".//{*}Polygon")
        point_elements = placemark.findall(".//{*}Point")

        name_elem = placemark.find(".//{*}name")
        name_text = (
            name_elem.text.strip() if name_elem is not None and name_elem.text else None
        )

        # Ignore special non-contour boundary placemarks unless they carry elevation
        if name_text and name_text.lower() in [
            "land",
            "boundary",
            "sources",
            "disclaimer",
            "legend",
        ]:
            return

        for line in line_elements:
            coord_elem = line.find(".//{*}coordinates")
            if coord_elem is not None and coord_elem.text:
                coords = self._parse_coordinate_string(coord_elem.text)
                if not coords:
                    continue

                # If elevation wasn't found in name/attributes, check 3D coordinate Z
                eff_elev = elevation
                if eff_elev is None:
                    z_vals = [c[2] for c in coords if len(c) > 2 and c[2] is not None]
                    if z_vals and any(z != 0.0 for z in z_vals):
                        eff_elev = float(np.mean(z_vals))

                if eff_elev is not None and eff_elev > 0:
                    feature = ContourFeature(eff_elev, coords, feature_id=name_text)
                    contours.append(feature)
                    all_elevs.append(eff_elev)
                    for pt in coords:
                        point_cloud.append((pt[0], pt[1], eff_elev))
                        all_lons.append(pt[0])
                        all_lats.append(pt[1])

        # If it's a 3D Point feature with elevation
        for pt_elem in point_elements:
            coord_elem = pt_elem.find(".//{*}coordinates")
            if coord_elem is not None and coord_elem.text:
                pts = self._parse_coordinate_string(coord_elem.text)
                for pt in pts:
                    eff_elev = (
                        elevation
                        if elevation is not None
                        else (pt[2] if len(pt) > 2 else None)
                    )
                    if eff_elev is not None and eff_elev > 0:
                        point_cloud.append((pt[0], pt[1], eff_elev))
                        all_lons.append(pt[0])
                        all_lats.append(pt[1])
                        all_elevs.append(eff_elev)

    def _extract_elevation(self, placemark: ET.Element) -> Optional[float]:
        """
        Dynamically extracts elevation from placemark name, ExtendedData, or description.
        Matches common patterns like '277.0', 'Elevation: 277m', 'Contour 277', etc.
        """
        # A. Check <name>
        name_elem = placemark.find(".//{*}name")
        if name_elem is not None and name_elem.text:
            text = name_elem.text.strip()
            elev = self._parse_numeric_elevation(text)
            if elev is not None:
                return elev

        # B. Check <ExtendedData> (<SimpleData> or <Data>)
        for simple_data in placemark.findall(".//{*}SimpleData"):
            attr_name = simple_data.attrib.get("name", "").lower()
            if attr_name in [
                "elevation",
                "elev",
                "contour",
                "height",
                "z",
                "val",
                "contour_m",
                "alt",
                "level",
            ]:
                val = self._parse_numeric_elevation(simple_data.text)
                if val is not None:
                    return val

        for data in placemark.findall(".//{*}Data"):
            attr_name = data.attrib.get("name", "").lower()
            if attr_name in [
                "elevation",
                "elev",
                "contour",
                "height",
                "z",
                "val",
                "contour_m",
                "alt",
                "level",
            ]:
                val_elem = data.find(".//{*}value")
                if val_elem is not None and val_elem.text:
                    val = self._parse_numeric_elevation(val_elem.text)
                    if val is not None:
                        return val

        # C. Check <description>
        desc_elem = placemark.find(".//{*}description")
        if desc_elem is not None and desc_elem.text:
            desc_text = desc_elem.text
            match = re.search(
                r"(?:elevation|elev|height|contour|z)[\s:=]+([+-]?\d+(?:\.\d+)?)",
                desc_text,
                re.IGNORECASE,
            )
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    pass

        return None

    def _parse_numeric_elevation(self, text: Optional[str]) -> Optional[float]:
        """Extract a float elevation from a string."""
        if not text:
            return None
        text = text.strip()
        # Direct float match
        try:
            return float(text)
        except ValueError:
            pass

        # Regex search for numeric pattern
        match = re.search(r"([+-]?\d+(?:\.\d+)?)", text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        return None

    def _parse_coordinate_string(
        self, coord_str: str
    ) -> List[Tuple[float, float, Optional[float]]]:
        """
        Parse KML coordinates format: 'lon,lat,alt lon,lat,alt ...'
        """
        result = []
        tokens = coord_str.strip().split()
        for token in tokens:
            parts = token.strip().split(",")
            if len(parts) >= 2:
                try:
                    lon = float(parts[0])
                    lat = float(parts[1])
                    alt = float(parts[2]) if len(parts) > 2 and parts[2] != "" else None
                    result.append((lon, lat, alt))
                except ValueError:
                    continue
        return result

    def _estimate_contour_interval(self, unique_elevations: List[float]) -> float:
        """Estimate the contour interval from sorted unique elevation values."""
        if len(unique_elevations) < 2:
            return 1.0
        diffs = np.diff(unique_elevations)
        positive_diffs = diffs[diffs > 1e-4]
        if len(positive_diffs) == 0:
            return 1.0
        return float(np.round(np.median(positive_diffs), 2))
