"""Shared fixtures: a fully synthetic, offline Geofabrik-like dataset.

No network and no real Geofabrik files are touched. We fabricate:

* a small ``.osm`` XML extract -- read by the very same GDAL OSM driver that
  parses ``.osm.pbf`` -- carrying one feature of each kind the pipeline builds
  (water, road, airport node, place node, military area), and
* an ``index-v1.json``-shaped GeoJSON document whose ``pbf`` URLs point at that
  extract via ``file://`` (the downloader passes local paths straight through).
"""

import json
from pathlib import Path

import pytest
from shapely.geometry import Polygon, box, mapping


@pytest.fixture
def bowtie():
    # Classic self-intersecting "bow-tie": invalid until repaired.
    return Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])


def _osm_file(path: Path, nodes, ways) -> Path:
    """Write a minimal .osm XML file with monotonically increasing ids.

    nodes: list of (lat, lon, {tag: value})
    ways:  list of ([node_index, ...], {tag: value})  -- indices into ``nodes``
    """
    lines = [
        "<?xml version='1.0' encoding='UTF-8'?>",
        "<osm version='0.6' generator='test'>",
    ]
    node_ids = []
    for i, (lat, lon, tags) in enumerate(nodes, start=1):
        node_ids.append(i)
        lines.append(f"<node id='{i}' lat='{lat}' lon='{lon}'>")
        for k, v in tags.items():
            lines.append(f"  <tag k='{k}' v='{v}'/>")
        lines.append("</node>")
    way_id = len(nodes) + 1
    for refs, tags in ways:
        lines.append(f"<way id='{way_id}'>")
        for r in refs:
            lines.append(f"  <nd ref='{node_ids[r]}'/>")
        for k, v in tags.items():
            lines.append(f"  <tag k='{k}' v='{v}'/>")
        lines.append("</way>")
        way_id += 1
    lines.append("</osm>")
    path.write_text("\n".join(lines))
    return path


@pytest.fixture
def osm_extract_file(tmp_path):
    """A .osm extract whose features sit inside bbox (0, 6, 10, 9)."""
    nodes = [
        # tagged feature nodes (sorted ids first)
        (7.0, 2.0, {"place": "city", "name": "Metropolis", "population": "100000"}),
        (7.5, 5.0, {"place": "town", "name": "Townsville", "population": "5000"}),
        (8.0, 3.0, {"aeroway": "aerodrome", "name": "Intl Airport"}),
        # geometry-only nodes for ways
        (6.5, 1.0, {}),    # 4 road start
        (6.5, 12.0, {}),   # 5 road end (extends past lon 10 -> clipped)
        (7.0, 1.0, {}),    # 6 lake
        (7.0, 3.0, {}),    # 7
        (8.0, 3.0, {}),    # 8
        (8.0, 1.0, {}),    # 9
        (7.0, 6.0, {}),    # 10 military
        (7.0, 8.0, {}),    # 11
        (8.0, 8.0, {}),    # 12
        (8.0, 6.0, {}),    # 13
    ]
    ways = [
        ([3, 4], {"highway": "motorway", "name": "A1", "ref": "1"}),
        ([5, 6, 7, 8, 5], {"natural": "water", "name": "Lake"}),
        ([9, 10, 11, 12, 9], {"landuse": "military", "name": "Base"}),
    ]
    return _osm_file(tmp_path / "wonderland-north.osm", nodes, ways)


@pytest.fixture
def synthetic_dataset(tmp_path, osm_extract_file):
    """Index + extract. Returns dict with index_path, bbox, extract path."""
    country_geom = box(0, 0, 10, 10)
    north_geom = box(0, 5, 10, 10)

    index = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": mapping(box(-30, -30, 60, 60)),
                "properties": {"id": "europe", "name": "Europe", "urls": {}},
            },
            {
                "type": "Feature",
                "geometry": mapping(country_geom),
                "properties": {
                    "id": "europe/wonderland",
                    "name": "Wonderland",
                    "parent": "europe",
                    "iso3166-1:alpha2": ["WL"],
                    "urls": {"pbf": osm_extract_file.as_uri()},
                },
            },
            {
                "type": "Feature",
                "geometry": mapping(north_geom),
                "properties": {
                    "id": "europe/wonderland/north",
                    "name": "Wonderland North",
                    "parent": "europe/wonderland",
                    "iso3166-2": ["WL-N"],
                    "urls": {"pbf": osm_extract_file.as_uri()},
                },
            },
        ],
    }
    index_path = tmp_path / "index-v1.json"
    index_path.write_text(json.dumps(index))

    return {
        "index_path": index_path,
        "bbox": (0.0, 6.0, 10.0, 9.0),
        "extract": osm_extract_file,
    }
