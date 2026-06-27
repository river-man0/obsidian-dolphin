"""Geofabrik data pipeline.

Ingest OpenStreetMap ``.osm.pbf`` extracts from download.geofabrik.de,
filter/sort/repair geometries, build country polygons, inland-water polygons, a
minimal road network, airports, population centres and military areas, simplify
and clip them to a requested extent, and write the result to GeoPackage and/or
GeoParquet.
"""

from .geo_ops import BBox
from .index import GeofabrikIndex, Region
from .osm import OsmExtract
from .pipeline import ALL_LAYERS, Pipeline, PipelineConfig

__version__ = "0.2.0"

__all__ = [
    "BBox",
    "GeofabrikIndex",
    "Region",
    "OsmExtract",
    "Pipeline",
    "PipelineConfig",
    "ALL_LAYERS",
    "__version__",
]
