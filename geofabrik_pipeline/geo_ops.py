"""Reusable geometry-processing primitives.

Every function here operates on GeoPandas objects in a single CRS (EPSG:4326
throughout the pipeline) and is deliberately small and side-effect free so the
pipeline stages can be composed and unit-tested in isolation.
"""

from __future__ import annotations

import warnings
from typing import Tuple

import geopandas as gpd
import shapely
from shapely.geometry import box

# Geofabrik / OpenStreetMap data is published in WGS84 lon/lat.
WGS84 = "EPSG:4326"

# A bounding box is (min_lon, min_lat, max_lon, max_lat).
BBox = Tuple[float, float, float, float]


def bbox_polygon(bbox: BBox):
    """Return a shapely polygon for ``(min_lon, min_lat, max_lon, max_lat)``."""
    min_lon, min_lat, max_lon, max_lat = bbox
    if not (min_lon < max_lon and min_lat < max_lat):
        raise ValueError(
            f"Invalid bbox {bbox!r}: expected min_lon < max_lon and min_lat < max_lat"
        )
    return box(min_lon, min_lat, max_lon, max_lat)


def make_valid(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Repair invalid geometries (self-intersections, bow-ties, ...).

    Uses Shapely 2's ``make_valid`` and only touches rows that actually report
    as invalid, which keeps the common case cheap. Geometries that survive are
    guaranteed to be valid according to the OGC simple-feature rules.
    """
    if gdf.empty:
        return gdf
    geom = gdf.geometry
    invalid = ~geom.is_valid & ~geom.is_empty & geom.notna()
    if invalid.any():
        gdf = gdf.copy()
        gdf.loc[invalid, gdf.geometry.name] = shapely.make_valid(
            geom[invalid].values
        )
    return gdf


def keep_polygonal(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Drop everything that is not (multi)polygonal.

    ``make_valid`` can turn a degenerate polygon into a line or a geometry
    collection; for area layers we only want the polygonal parts. Collections
    are exploded down to their polygonal members.
    """
    if gdf.empty:
        return gdf
    # Pull polygonal parts out of any GeometryCollections that make_valid produced.
    extracted = gdf.copy()
    extracted[extracted.geometry.name] = extracted.geometry.apply(_polygonal_part)
    extracted = extracted[~extracted.geometry.is_empty & extracted.geometry.notna()]
    types = extracted.geom_type
    return extracted[types.isin(["Polygon", "MultiPolygon"])]


def _polygonal_part(geom):
    if geom is None or geom.is_empty:
        return geom
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom
    if geom.geom_type == "GeometryCollection":
        polys = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        if not polys:
            return shapely.geometry.GeometryCollection()  # becomes empty -> dropped
        return shapely.union_all(polys)
    # Lines / points produced by validation of slivers are not area features.
    return shapely.geometry.GeometryCollection()


def drop_empty(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Remove null and empty geometries."""
    if gdf.empty:
        return gdf
    geom = gdf.geometry
    return gdf[geom.notna() & ~geom.is_empty]


def clip_to_bbox(gdf: gpd.GeoDataFrame, bbox: BBox) -> gpd.GeoDataFrame:
    """Clip geometries to the extent, keeping only the parts inside it."""
    if gdf.empty:
        return gdf
    clipped = gpd.clip(gdf, bbox_polygon(bbox))
    return drop_empty(clipped)


def simplify(gdf: gpd.GeoDataFrame, tolerance: float) -> gpd.GeoDataFrame:
    """Topology-preserving simplification.

    ``tolerance`` is expressed in CRS units (degrees for EPSG:4326). A value of
    ``0`` is a no-op so callers can disable simplification without branching.
    """
    if gdf.empty or not tolerance:
        return gdf
    gdf = gdf.copy()
    gdf[gdf.geometry.name] = gdf.geometry.simplify(
        tolerance, preserve_topology=True
    )
    return gdf


def sort_by_area(gdf: gpd.GeoDataFrame, ascending: bool = False) -> gpd.GeoDataFrame:
    """Sort polygon rows by geodesic-ish planar area (largest first by default)."""
    if gdf.empty:
        return gdf
    # Planar area in degrees is meaningless as a measurement but perfectly
    # adequate for ordering, so silence the geographic-CRS warning.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        order = gdf.geometry.area.sort_values(ascending=ascending).index
    return gdf.loc[order].reset_index(drop=True)
