"""Shared fixtures: fully synthetic, offline Geofabrik-like data.

No network and no real Geofabrik files are touched. We fabricate:

* a GeoPackage that stands in for a ``*-free.shp.zip`` extract (it carries a
  ``gis_osm_water_a_free_1`` layer, matched by the same pattern), and
* an ``index-v1.json``-shaped GeoJSON document referencing those extracts via
  ``file://`` URLs, which the downloader passes through untouched.
"""

import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Polygon, box, mapping


def _water_gpkg(path: Path, polygons, fclasses, names) -> Path:
    gdf = gpd.GeoDataFrame(
        {"osm_id": [str(i) for i in range(len(polygons))],
         "fclass": fclasses,
         "name": names},
        geometry=polygons,
        crs="EPSG:4326",
    )
    gdf.to_file(path, layer="gis_osm_water_a_free_1", driver="GPKG")
    return path


@pytest.fixture
def bowtie():
    # Classic self-intersecting "bow-tie": invalid until repaired.
    return Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])


@pytest.fixture
def synthetic_dataset(tmp_path):
    """Build extracts + index. Returns (index_path, bbox, paths)."""
    # Country "Wonderland" spans lon 0..10, lat 0..10. A northern sub-region
    # spans lat 5..10 and has its own extract.
    country_geom = box(0, 0, 10, 10)
    north_geom = box(0, 5, 10, 10)

    # Water in the north extract: a valid lake fully inside the test bbox and a
    # lake that straddles the bbox edge (to exercise clipping).
    inside_lake = box(1, 6, 3, 8)
    straddle_lake = box(8, 6, 12, 8)  # extends past lon 10
    north_extract = _water_gpkg(
        tmp_path / "wonderland-north.gpkg",
        [inside_lake, straddle_lake],
        ["water", "reservoir"],
        ["Inside Lake", "Edge Lake"],
    )

    # Whole-country extract (should be skipped in favour of the sub-region).
    country_extract = _water_gpkg(
        tmp_path / "wonderland.gpkg",
        [box(1, 1, 2, 2)],
        ["water"],
        ["Southern Pond"],
    )

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
                    "urls": {"shp": country_extract.as_uri()},
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
                    "urls": {"shp": north_extract.as_uri()},
                },
            },
        ],
    }
    index_path = tmp_path / "index-v1.json"
    index_path.write_text(json.dumps(index))

    # A bbox entirely within the northern sub-region.
    bbox = (0.0, 6.0, 10.0, 9.0)
    return {
        "index_path": index_path,
        "bbox": bbox,
        "north_extract": north_extract,
        "country_extract": country_extract,
        "tmp_path": tmp_path,
    }
