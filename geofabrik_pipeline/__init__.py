"""Geofabrik data pipeline.

Ingest OpenStreetMap extracts from download.geofabrik.de, filter/sort/repair
geometries, build country and inland-water polygons, simplify and clip them to a
requested extent, and write the result to a GeoPackage.
"""

from .geo_ops import BBox
from .index import GeofabrikIndex, Region
from .pipeline import Pipeline, PipelineConfig

__version__ = "0.1.0"

__all__ = [
    "BBox",
    "GeofabrikIndex",
    "Region",
    "Pipeline",
    "PipelineConfig",
    "__version__",
]
