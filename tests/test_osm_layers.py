"""Tests for the PBF-derived feature layers (read via the GDAL OSM driver)."""

import pytest

from geofabrik_pipeline import layers
from geofabrik_pipeline.osm import OsmExtract

BBOX = (0.0, 6.0, 10.0, 9.0)


@pytest.fixture
def extract(osm_extract_file):
    return OsmExtract(osm_extract_file.as_posix(), BBOX)


def test_water_layer(extract):
    gdf = layers.build_water_layer([extract], BBOX, tolerance=0.0, clip=True)
    assert len(gdf) == 1
    assert gdf.geometry.is_valid.all()
    assert "Lake" in set(gdf["name"])
    assert set(gdf.geometry.geom_type) <= {"Polygon", "MultiPolygon"}


def test_roads_layer_is_minimal_and_clipped(extract):
    gdf = layers.build_roads_layer([extract], BBOX, tolerance=0.0, clip=True)
    assert len(gdf) == 1
    assert set(gdf["fclass"]) == {"motorway"}
    assert set(gdf.geometry.geom_type) <= {"LineString", "MultiLineString"}
    # The road runs out to lon 12; clipping must trim it to the extent.
    assert gdf.total_bounds[2] <= 10.0 + 1e-9


def test_airports_layer_points(extract):
    gdf = layers.build_airports_layer([extract], BBOX, clip=True)
    assert len(gdf) == 1
    assert list(gdf["name"]) == ["Intl Airport"]
    assert set(gdf.geometry.geom_type) == {"Point"}


def test_population_layer_sorted(extract):
    gdf = layers.build_population_layer([extract], BBOX, clip=True)
    assert set(gdf["name"]) == {"Metropolis", "Townsville"}
    assert set(gdf["place"]) <= {"city", "town", "village"}
    # Sorted by population descending.
    assert list(gdf["name"]) == ["Metropolis", "Townsville"]


def test_military_layer(extract):
    gdf = layers.build_military_layer([extract], BBOX, tolerance=0.0, clip=True)
    assert len(gdf) == 1
    assert list(gdf["name"]) == ["Base"]
    assert gdf.geometry.is_valid.all()
