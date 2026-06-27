"""Access to the Geofabrik download index.

Geofabrik publishes ``index-v1.json`` -- a GeoJSON ``FeatureCollection`` where
every feature is one downloadable region. The feature *geometry* is the region
boundary polygon and the feature *properties* carry the region id, its parent,
ISO codes and the set of download URLs (``pbf``, ``shp``, ...).

We lean on this single file for two things:

* the **country polygons** themselves (a country's boundary *is* its index
  geometry), and
* discovering which ``*-free.shp.zip`` extract(s) cover a requested extent so
  we can pull water bodies out of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

from .geo_ops import WGS84, BBox, bbox_polygon

# Default location of the index. ``index-v1.json`` includes the geometries we
# need for country polygons (``index-v1-nogeom.json`` does not).
DEFAULT_INDEX_URL = "https://download.geofabrik.de/index-v1.json"


@dataclass(frozen=True)
class Region:
    """One Geofabrik download region."""

    id: str
    name: str
    parent: Optional[str]
    iso2: Optional[str]
    iso_sub: Optional[str]
    shp_url: Optional[str]
    pbf_url: Optional[str]

    @property
    def is_country(self) -> bool:
        """A top-level country has an ISO-3166-1 code but no sub-national code.

        That distinguishes e.g. ``germany`` (alpha2 ``DE``) from
        ``germany/bayern`` (sub-code ``DE-BY``) and from continents such as
        ``europe`` (no ISO code at all).
        """
        return bool(self.iso2) and not self.iso_sub


class GeofabrikIndex:
    """Queryable view over the Geofabrik index."""

    def __init__(self, regions: gpd.GeoDataFrame):
        # regions: GeoDataFrame indexed by region id with Region metadata columns.
        self.regions = regions
        self._by_id: Dict[str, Region] = {
            row.id: _row_to_region(row) for row in regions.itertuples()
        }

    # ---- construction -----------------------------------------------------

    @classmethod
    def from_geojson(cls, data: dict) -> "GeofabrikIndex":
        """Build an index from a parsed ``index-v1.json`` dictionary."""
        records = []
        geoms = []
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            urls = props.get("urls", {}) or {}
            records.append(
                {
                    "id": props.get("id"),
                    "name": props.get("name") or props.get("id"),
                    "parent": props.get("parent"),
                    "iso2": _first(props.get("iso3166-1:alpha2")),
                    "iso_sub": _first(props.get("iso3166-2")),
                    "shp_url": urls.get("shp"),
                    "pbf_url": urls.get("pbf"),
                }
            )
            geom = feature.get("geometry")
            geoms.append(shape(geom) if geom else None)
        gdf = gpd.GeoDataFrame(records, geometry=geoms, crs=WGS84)
        gdf = gdf[gdf["id"].notna()].set_index("id", drop=False)
        return cls(gdf)

    @classmethod
    def load(cls, downloader, url: str = DEFAULT_INDEX_URL) -> "GeofabrikIndex":
        """Fetch and parse the index using the given downloader."""
        return cls.from_geojson(downloader.fetch_json(url))

    # ---- queries ----------------------------------------------------------

    def get(self, region_id: str) -> Region:
        return self._by_id[region_id]

    def intersecting(self, bbox: BBox) -> gpd.GeoDataFrame:
        """All regions whose boundary intersects the extent."""
        extent = bbox_polygon(bbox)
        has_geom = self.regions.geometry.notna()
        hits = self.regions[has_geom & self.regions.geometry.intersects(extent)]
        return hits

    def countries_in(self, bbox: BBox) -> gpd.GeoDataFrame:
        """Country regions whose boundary intersects the extent."""
        hits = self.intersecting(bbox)
        if not len(hits):
            return hits
        mask = hits["id"].map(lambda rid: self._by_id[rid].is_country)
        return hits[mask]

    def is_ancestor(self, ancestor_id: str, region_id: str) -> bool:
        """True if ``ancestor_id`` is somewhere up ``region_id``'s parent chain."""
        seen = set()
        current = self._by_id.get(region_id)
        while current and current.parent and current.parent not in seen:
            if current.parent == ancestor_id:
                return True
            seen.add(current.parent)
            current = self._by_id.get(current.parent)
        return False

    def select_extracts(self, bbox: BBox) -> List[Region]:
        """Pick the *most granular* ``.osm.pbf`` extracts covering the extent.

        Among all pbf-bearing regions intersecting the extent we drop any region
        that is an ancestor of another selected region. That prefers, say, the
        individual German states over the whole-Germany extract, minimising the
        download while still covering the requested area.
        """
        candidates = self.intersecting(bbox)
        candidates = candidates[candidates["pbf_url"].notna()]
        ids = list(candidates["id"])
        selected = []
        for region_id in ids:
            if any(
                other != region_id and self.is_ancestor(region_id, other)
                for other in ids
            ):
                continue  # a more granular descendant is also selected
            selected.append(self._by_id[region_id])
        return selected


def _first(value):
    """Geofabrik stores ISO codes as single-element lists; unwrap them."""
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def _row_to_region(row) -> Region:
    return Region(
        id=row.id,
        name=row.name,
        parent=row.parent if not pd.isna(row.parent) else None,
        iso2=row.iso2 if not pd.isna(row.iso2) else None,
        iso_sub=row.iso_sub if not pd.isna(row.iso_sub) else None,
        shp_url=row.shp_url if not pd.isna(row.shp_url) else None,
        pbf_url=row.pbf_url if not pd.isna(row.pbf_url) else None,
    )
