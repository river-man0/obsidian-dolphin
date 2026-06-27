"""Read feature layers out of an ``.osm.pbf`` extract via the GDAL OSM driver.

The driver flattens OSM into five layers (``points``, ``lines``,
``multilinestrings``, ``multipolygons``, ``other_relations``). We only need
three of them, and we read each one *at most once* per extract -- behind a small
cache on :class:`OsmExtract` -- because parsing a national PBF is expensive. The
bundled ``osmconf.ini`` promotes the tags we care about to real columns so the
filtering below can run as SQL pushed into the driver.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import geopandas as gpd
import pyogrio

from .geo_ops import WGS84, BBox

# Bundled GDAL OSM driver config (tag->column mapping, polygon detection).
OSM_CONFIG_FILE = str(Path(__file__).with_name("osmconf.ini"))

# Coarse pushdown filters: pull only tagged features that *might* feed a layer,
# then refine in pandas inside the layer builders.
POINTS_WHERE = (
    "place IS NOT NULL OR aeroway IS NOT NULL OR military IS NOT NULL"
)
LINES_WHERE = "highway IS NOT NULL"
MULTIPOLYGONS_WHERE = (
    "natural IS NOT NULL OR water IS NOT NULL OR waterway IS NOT NULL "
    "OR landuse IS NOT NULL OR military IS NOT NULL OR aeroway IS NOT NULL "
    "OR boundary IS NOT NULL"
)


def _read_layer(path: str, layer: str, bbox: BBox, where: str) -> gpd.GeoDataFrame:
    pyogrio.set_gdal_config_options({"OSM_CONFIG_FILE": OSM_CONFIG_FILE})
    try:
        gdf = pyogrio.read_dataframe(path, layer=layer, bbox=bbox, where=where)
    except Exception:
        # Custom indexing assumes monotonically increasing node ids. Fall back to
        # the slower in-memory index for files that violate that assumption.
        pyogrio.set_gdal_config_options(
            {"OSM_CONFIG_FILE": OSM_CONFIG_FILE, "OSM_USE_CUSTOM_INDEXING": "NO"}
        )
        try:
            gdf = pyogrio.read_dataframe(path, layer=layer, bbox=bbox, where=where)
        finally:
            pyogrio.set_gdal_config_options({"OSM_USE_CUSTOM_INDEXING": None})

    if gdf.crs is None:
        gdf = gdf.set_crs(WGS84)
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(WGS84)
    return gdf


class OsmExtract:
    """A single ``.osm.pbf`` extract, with cached per-layer reads."""

    def __init__(self, path, bbox: BBox):
        self.path = str(path)
        self.bbox = bbox
        self._cache: Dict[str, gpd.GeoDataFrame] = {}

    def _get(self, layer: str, where: str) -> gpd.GeoDataFrame:
        if layer not in self._cache:
            self._cache[layer] = _read_layer(self.path, layer, self.bbox, where)
        return self._cache[layer]

    def points(self) -> gpd.GeoDataFrame:
        return self._get("points", POINTS_WHERE)

    def lines(self) -> gpd.GeoDataFrame:
        return self._get("lines", LINES_WHERE)

    def multipolygons(self) -> gpd.GeoDataFrame:
        return self._get("multipolygons", MULTIPOLYGONS_WHERE)
