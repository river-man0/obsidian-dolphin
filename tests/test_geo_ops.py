import geopandas as gpd
import pytest
from shapely.geometry import LineString, Polygon, box

from geofabrik_pipeline import geo_ops


def _gdf(geoms):
    return gpd.GeoDataFrame({"id": range(len(geoms))}, geometry=geoms, crs="EPSG:4326")


def test_make_valid_repairs_bowtie(bowtie):
    gdf = _gdf([bowtie])
    assert not gdf.geometry.is_valid.all()
    fixed = geo_ops.make_valid(gdf)
    assert fixed.geometry.is_valid.all()


def test_keep_polygonal_drops_lines():
    gdf = _gdf([box(0, 0, 1, 1), LineString([(0, 0), (1, 1)])])
    kept = geo_ops.keep_polygonal(gdf)
    assert len(kept) == 1
    assert kept.geom_type.iloc[0] == "Polygon"


def test_clip_to_bbox_trims_geometry():
    # Polygon spans lon 0..4; clip to 0..2 should halve its area.
    gdf = _gdf([box(0, 0, 4, 1)])
    clipped = geo_ops.clip_to_bbox(gdf, (0, 0, 2, 1))
    assert clipped.geometry.area.sum() == pytest.approx(2.0)


def test_clip_drops_features_outside():
    gdf = _gdf([box(10, 10, 11, 11)])
    clipped = geo_ops.clip_to_bbox(gdf, (0, 0, 1, 1))
    assert clipped.empty


def test_simplify_reduces_vertices():
    # A many-vertex near-straight edge collapses under simplification.
    coords = [(x / 100.0, (x % 2) * 1e-6) for x in range(101)]
    coords += [(1, 1), (0, 1), (0, 0)]
    gdf = _gdf([Polygon(coords)])
    before = len(gdf.geometry.iloc[0].exterior.coords)
    after = len(geo_ops.simplify(gdf, 0.01).geometry.iloc[0].exterior.coords)
    assert after < before


def test_simplify_zero_is_noop():
    gdf = _gdf([box(0, 0, 1, 1)])
    out = geo_ops.simplify(gdf, 0)
    assert out.geometry.iloc[0].equals(gdf.geometry.iloc[0])


def test_sort_by_area_largest_first():
    gdf = _gdf([box(0, 0, 1, 1), box(0, 0, 3, 3), box(0, 0, 2, 2)])
    out = geo_ops.sort_by_area(gdf)
    areas = list(out.geometry.area)
    assert areas == sorted(areas, reverse=True)


def test_bbox_polygon_rejects_degenerate():
    with pytest.raises(ValueError):
        geo_ops.bbox_polygon((1, 0, 0, 1))
