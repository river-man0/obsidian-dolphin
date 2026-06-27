"""Build the two output layers: country polygons and water-body polygons."""

from __future__ import annotations

import re
from typing import Iterable, List, Optional

import geopandas as gpd
import pandas as pd
import pyogrio

from . import geo_ops
from .geo_ops import WGS84, BBox
from .index import GeofabrikIndex, Region

# Layer inside a Geofabrik ``*-free.shp.zip`` that holds inland water *areas*
# (lakes, reservoirs, ponds, riverbanks). It is matched by pattern so the tool
# keeps working if Geofabrik bumps the trailing version number.
WATER_AREA_LAYER_PATTERN = re.compile(r"water_a", re.IGNORECASE)

# OpenStreetMap models oceans/seas as *coastline* (a separate line layer), never
# as water-area polygons -- so ``gis_osm_water_a`` is already ocean-free. We
# additionally guard against any fclass that would denote open sea, which keeps
# the "excluding oceans" contract explicit and future-proof.
OCEAN_FCLASSES = {"ocean", "sea"}


def _process_polygons(
    gdf: gpd.GeoDataFrame,
    bbox: BBox,
    tolerance: float,
    clip: bool,
    sort_largest_first: bool,
) -> gpd.GeoDataFrame:
    """Shared cleanup pipeline for an area layer.

    Order matters: validate first so clipping operates on sound geometry, clip
    to the extent, re-validate (clipping can create slivers), simplify, then
    validate once more and drop anything that collapsed to empty.
    """
    gdf = geo_ops.make_valid(gdf)
    gdf = geo_ops.keep_polygonal(gdf)
    if clip:
        gdf = geo_ops.clip_to_bbox(gdf, bbox)
        gdf = geo_ops.make_valid(gdf)
    gdf = geo_ops.simplify(gdf, tolerance)
    gdf = geo_ops.make_valid(gdf)
    gdf = geo_ops.keep_polygonal(gdf)
    gdf = geo_ops.drop_empty(gdf)
    gdf = geo_ops.sort_by_area(gdf, ascending=not sort_largest_first)
    return gdf


# ---------------------------------------------------------------------------
# Country polygons
# ---------------------------------------------------------------------------

def build_country_layer(
    index: GeofabrikIndex,
    bbox: BBox,
    tolerance: float,
    clip: bool = True,
) -> gpd.GeoDataFrame:
    """Country boundary polygons covering the extent.

    The boundary geometry comes straight from the Geofabrik index, so no heavy
    extract download is needed to draw national outlines.
    """
    countries = index.countries_in(bbox)
    cols = {
        "country_id": countries["id"],
        "name": countries["name"],
        "iso2": countries["iso2"],
    }
    gdf = gpd.GeoDataFrame(
        cols, geometry=countries.geometry.values, crs=WGS84
    ).reset_index(drop=True)
    gdf = _process_polygons(
        gdf, bbox, tolerance, clip, sort_largest_first=True
    )
    return gdf[["country_id", "name", "iso2", "geometry"]]


# ---------------------------------------------------------------------------
# Water bodies (excluding oceans)
# ---------------------------------------------------------------------------

def _find_water_layer(source: str) -> Optional[str]:
    """Locate the water-area layer name inside a shapefile zip / datasource."""
    try:
        layers = [name for name, _ in pyogrio.list_layers(source)]
    except Exception:
        return None
    for name in layers:
        if WATER_AREA_LAYER_PATTERN.search(name):
            return name
    return None


def read_water_extract(source: str, bbox: BBox) -> gpd.GeoDataFrame:
    """Read inland water polygons from a single Geofabrik extract.

    ``source`` is a path to a ``*-free.shp.zip`` (or any datasource pyogrio can
    open). The ``bbox`` is pushed down to the driver so only features in the
    extent are read off disk.
    """
    layer = _find_water_layer(source)
    if layer is None:
        return gpd.GeoDataFrame(
            {"osm_id": [], "fclass": [], "name": []},
            geometry=[],
            crs=WGS84,
        )
    gdf = gpd.read_file(source, layer=layer, bbox=bbox)
    if gdf.crs is None:
        gdf = gdf.set_crs(WGS84)
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(WGS84)
    return gdf


def build_water_layer(
    sources: Iterable[str],
    bbox: BBox,
    tolerance: float,
    clip: bool = True,
) -> gpd.GeoDataFrame:
    """Combine, clean and simplify inland water polygons from extracts."""
    frames: List[gpd.GeoDataFrame] = []
    for source in sources:
        part = read_water_extract(source, bbox)
        if not part.empty:
            frames.append(part)

    if not frames:
        empty = gpd.GeoDataFrame(
            {"osm_id": [], "fclass": [], "name": []}, geometry=[], crs=WGS84
        )
        return empty

    gdf = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), crs=WGS84
    )

    # Normalise attribute columns and explicitly drop any ocean/sea features.
    for col in ("osm_id", "fclass", "name"):
        if col not in gdf.columns:
            gdf[col] = pd.NA
    gdf = gdf[~gdf["fclass"].astype("string").str.lower().isin(OCEAN_FCLASSES)]

    gdf = gdf[["osm_id", "fclass", "name", gdf.geometry.name]]
    gdf = _process_polygons(
        gdf, bbox, tolerance, clip, sort_largest_first=True
    )
    return gdf[["osm_id", "fclass", "name", "geometry"]]
