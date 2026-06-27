"""Build output layers from the Geofabrik index and ``.osm.pbf`` extracts.

* ``countries``           -- boundary polygons, from the Geofabrik index.
* ``water_bodies``        -- inland water polygons (oceans excluded), from PBF.
* ``roads``               -- a minimal major-road network (lines), from PBF.
* ``airports``            -- airport locations (points), from PBF.
* ``population_centres``  -- cities/towns/villages (points), from PBF.
* ``military``            -- military areas (polygons), from PBF.

Each builder takes the already-loaded :class:`~geofabrik_pipeline.osm.OsmExtract`
objects so a national PBF is parsed only once even though several layers draw
from the same underlying OSM layer.
"""

from __future__ import annotations

from typing import Iterable, List, Sequence

import geopandas as gpd
import pandas as pd

from . import geo_ops
from .geo_ops import WGS84, BBox
from .index import GeofabrikIndex
from .osm import OsmExtract

# OSM models oceans/seas as coastline (a line layer) -- never as water-area
# polygons -- so the area layer is inland-only. We still drop any explicit
# sea/ocean value as a guard, keeping the "excluding oceans" contract explicit.
OCEAN_WATER_VALUES = {"ocean", "sea"}

# "Minimal" road network: the classified through-roads, not every service road,
# track or footpath. Link ramps are kept so junctions stay connected.
MINIMAL_ROAD_CLASSES = {
    "motorway", "motorway_link",
    "trunk", "trunk_link",
    "primary", "primary_link",
    "secondary", "secondary_link",
}

# What counts as a "population centre".
PLACE_CLASSES = {"city", "town", "village"}


# ---------------------------------------------------------------------------
# Shared cleanup helpers
# ---------------------------------------------------------------------------

def _osm_id(gdf: gpd.GeoDataFrame) -> pd.Series:
    """Coalesce the driver's id columns into a single string id."""
    if "osm_id" in gdf.columns:
        ids = gdf["osm_id"].astype("string")
    else:
        ids = pd.Series(pd.NA, index=gdf.index, dtype="string")
    if "osm_way_id" in gdf.columns:
        ids = ids.fillna(gdf["osm_way_id"].astype("string"))
    return ids


def _process_polygons(gdf, bbox, tolerance, clip):
    gdf = geo_ops.make_valid(gdf)
    gdf = geo_ops.keep_polygonal(gdf)
    if clip:
        gdf = geo_ops.clip_to_bbox(gdf, bbox)
        gdf = geo_ops.make_valid(gdf)
    gdf = geo_ops.simplify(gdf, tolerance)
    gdf = geo_ops.make_valid(gdf)
    gdf = geo_ops.keep_polygonal(gdf)
    gdf = geo_ops.drop_empty(gdf)
    return geo_ops.sort_by_area(gdf, ascending=False)


def _process_lines(gdf, bbox, tolerance, clip):
    gdf = geo_ops.drop_empty(gdf)
    if clip:
        gdf = geo_ops.clip_to_bbox(gdf, bbox)
    gdf = geo_ops.simplify(gdf, tolerance)
    gdf = geo_ops.drop_empty(gdf)
    # Keep only (multi)line parts; clipping a line never yields polygons but may
    # drop a feature to a point where it merely grazes the extent edge.
    types = gdf.geom_type.isin(["LineString", "MultiLineString"])
    return gdf[types].reset_index(drop=True)


def _process_points(gdf, bbox, clip):
    gdf = geo_ops.drop_empty(gdf)
    if clip and not gdf.empty:
        extent = geo_ops.bbox_polygon(bbox)
        gdf = gdf[gdf.geometry.within(extent)]
    return gdf.reset_index(drop=True)


def _empty(columns: Sequence[str]) -> gpd.GeoDataFrame:
    data = {c: [] for c in columns if c != "geometry"}
    return gpd.GeoDataFrame(data, geometry=[], crs=WGS84)


def _concat(frames: List[gpd.GeoDataFrame], columns: Sequence[str]) -> gpd.GeoDataFrame:
    frames = [f for f in frames if not f.empty]
    if not frames:
        return _empty(columns)
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=WGS84)


# ---------------------------------------------------------------------------
# Countries (from the Geofabrik index)
# ---------------------------------------------------------------------------

def build_country_layer(index: GeofabrikIndex, bbox, tolerance, clip=True):
    countries = index.countries_in(bbox)
    gdf = gpd.GeoDataFrame(
        {
            "country_id": countries["id"].values,
            "name": countries["name"].values,
            "iso2": countries["iso2"].values,
        },
        geometry=countries.geometry.values,
        crs=WGS84,
    )
    gdf = _process_polygons(gdf, bbox, tolerance, clip)
    return gdf[["country_id", "name", "iso2", "geometry"]]


# ---------------------------------------------------------------------------
# Water bodies (PBF multipolygons, oceans excluded)
# ---------------------------------------------------------------------------

def build_water_layer(extracts: Iterable[OsmExtract], bbox, tolerance, clip=True):
    cols = ["osm_id", "name", "fclass", "geometry"]
    frames = []
    for ex in extracts:
        mp = ex.multipolygons()
        if mp.empty:
            continue
        is_water = (
            mp["natural"].isin(["water", "wetland"])
            | mp["water"].notna()
            | mp["waterway"].isin(["riverbank", "dock"])
            | mp["landuse"].isin(["reservoir", "basin"])
        )
        water = mp[is_water]
        # Explicitly exclude any sea/ocean polygons.
        water = water[~water["water"].astype("string").str.lower().isin(OCEAN_WATER_VALUES)]
        if water.empty:
            continue
        fclass = (
            water["water"].astype("string")
            .fillna(water["natural"].astype("string"))
            .fillna(water["waterway"].astype("string"))
            .fillna(water["landuse"].astype("string"))
        )
        frames.append(
            gpd.GeoDataFrame(
                {"osm_id": _osm_id(water), "name": water["name"], "fclass": fclass},
                geometry=water.geometry.values,
                crs=WGS84,
            )
        )
    gdf = _concat(frames, cols)
    gdf = _process_polygons(gdf, bbox, tolerance, clip)
    return gdf[cols] if not gdf.empty else _empty(cols)


# ---------------------------------------------------------------------------
# Roads (PBF lines, minimal network)
# ---------------------------------------------------------------------------

def build_roads_layer(
    extracts: Iterable[OsmExtract], bbox, tolerance, clip=True,
    classes: Sequence[str] = None,
):
    classes = set(classes) if classes else MINIMAL_ROAD_CLASSES
    cols = ["osm_id", "name", "fclass", "ref", "geometry"]
    frames = []
    for ex in extracts:
        lines = ex.lines()
        if lines.empty:
            continue
        roads = lines[lines["highway"].isin(classes)]
        if roads.empty:
            continue
        frames.append(
            gpd.GeoDataFrame(
                {
                    "osm_id": _osm_id(roads),
                    "name": roads["name"],
                    "fclass": roads["highway"],
                    "ref": roads["ref"] if "ref" in roads.columns else pd.NA,
                },
                geometry=roads.geometry.values,
                crs=WGS84,
            )
        )
    gdf = _concat(frames, cols)
    gdf = _process_lines(gdf, bbox, tolerance, clip)
    return gdf[cols] if not gdf.empty else _empty(cols)


# ---------------------------------------------------------------------------
# Airports (PBF points + aerodrome polygons reduced to points)
# ---------------------------------------------------------------------------

def build_airports_layer(extracts: Iterable[OsmExtract], bbox, clip=True):
    cols = ["osm_id", "name", "geometry"]
    frames = []
    for ex in extracts:
        pts = ex.points()
        node_air = pts[pts["aeroway"] == "aerodrome"] if not pts.empty else pts
        if not node_air.empty:
            frames.append(
                gpd.GeoDataFrame(
                    {"osm_id": _osm_id(node_air), "name": node_air["name"]},
                    geometry=node_air.geometry.values,
                    crs=WGS84,
                )
            )
        mp = ex.multipolygons()
        area_air = mp[mp["aeroway"] == "aerodrome"] if not mp.empty else mp
        if not area_air.empty:
            # Reduce aerodrome areas to a single representative point each.
            frames.append(
                gpd.GeoDataFrame(
                    {"osm_id": _osm_id(area_air), "name": area_air["name"]},
                    geometry=area_air.geometry.representative_point().values,
                    crs=WGS84,
                )
            )
    gdf = _concat(frames, cols)
    gdf = _process_points(gdf, bbox, clip)
    if not gdf.empty:
        gdf = gdf.sort_values("name", na_position="last").reset_index(drop=True)
    return gdf[cols] if not gdf.empty else _empty(cols)


# ---------------------------------------------------------------------------
# Population centres (PBF place points)
# ---------------------------------------------------------------------------

def build_population_layer(extracts: Iterable[OsmExtract], bbox, clip=True):
    cols = ["osm_id", "name", "place", "population", "geometry"]
    frames = []
    for ex in extracts:
        pts = ex.points()
        if pts.empty:
            continue
        centres = pts[pts["place"].isin(PLACE_CLASSES)]
        if centres.empty:
            continue
        population = pd.to_numeric(centres["population"], errors="coerce")
        frames.append(
            gpd.GeoDataFrame(
                {
                    "osm_id": _osm_id(centres),
                    "name": centres["name"],
                    "place": centres["place"],
                    "population": population.values,
                },
                geometry=centres.geometry.values,
                crs=WGS84,
            )
        )
    gdf = _concat(frames, cols)
    gdf = _process_points(gdf, bbox, clip)
    if not gdf.empty:
        gdf = gdf.sort_values(
            "population", ascending=False, na_position="last"
        ).reset_index(drop=True)
    return gdf[cols] if not gdf.empty else _empty(cols)


# ---------------------------------------------------------------------------
# Military areas (PBF multipolygons)
# ---------------------------------------------------------------------------

def build_military_layer(extracts: Iterable[OsmExtract], bbox, tolerance, clip=True):
    cols = ["osm_id", "name", "geometry"]
    frames = []
    for ex in extracts:
        mp = ex.multipolygons()
        if mp.empty:
            continue
        is_mil = (
            (mp["landuse"] == "military")
            | mp["military"].notna()
            | (mp["boundary"] == "military")
        )
        mil = mp[is_mil]
        if mil.empty:
            continue
        frames.append(
            gpd.GeoDataFrame(
                {"osm_id": _osm_id(mil), "name": mil["name"]},
                geometry=mil.geometry.values,
                crs=WGS84,
            )
        )
    gdf = _concat(frames, cols)
    gdf = _process_polygons(gdf, bbox, tolerance, clip)
    return gdf[cols] if not gdf.empty else _empty(cols)
