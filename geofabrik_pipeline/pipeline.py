"""End-to-end orchestration: index + PBF -> clean layers -> GeoPackage/Parquet."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import geopandas as gpd

from . import layers
from .download import Downloader
from .geo_ops import BBox, bbox_area_sqdeg
from .index import DEFAULT_INDEX_URL, GeofabrikIndex
from .osm import OsmExtract

log = logging.getLogger("geofabrik_pipeline")

# Default simplify tolerance in degrees (~10 m at the equator): "slightly".
DEFAULT_SIMPLIFY = 0.0001

# Above this extent area (sq.deg) the auto-selector would pull PBF extracts for
# nearly the whole planet, so building PBF layers there needs an explicit opt-in.
# ~10,000 sq.deg is roughly a 100x100-degree box; a hemisphere is ~32,400.
LARGE_EXTENT_SQDEG = 10_000.0

# Layer key -> output layer name in the GeoPackage / Parquet file stem.
LAYER_NAMES = {
    "countries": "countries",
    "water": "water_bodies",
    "roads": "roads",
    "airports": "airports",
    "population": "population_centres",
    "military": "military",
}
ALL_LAYERS = tuple(LAYER_NAMES)

# Which layers are derived from the (heavy) PBF extracts.
PBF_LAYERS = {"water", "roads", "airports", "population", "military"}

SUPPORTED_FORMATS = ("gpkg", "parquet")


@dataclass
class PipelineConfig:
    bbox: BBox
    output: Path
    simplify: float = DEFAULT_SIMPLIFY
    clip: bool = True
    layers: Sequence[str] = ALL_LAYERS
    formats: Sequence[str] = ("gpkg",)
    regions: Optional[Sequence[str]] = None  # force specific extract ids
    allow_large_pbf: bool = False  # opt in to PBF layers over a huge extent
    cache_dir: Path = field(default_factory=lambda: Path(".geofabrik_cache"))
    index_url: str = DEFAULT_INDEX_URL


class Pipeline:
    def __init__(self, config: PipelineConfig, downloader: Optional[Downloader] = None):
        self.config = config
        self.downloader = downloader or Downloader(config.cache_dir)

    # ---- ingest -----------------------------------------------------------

    def load_index(self) -> GeofabrikIndex:
        log.info("Loading Geofabrik index from %s", self.config.index_url)
        return GeofabrikIndex.load(self.downloader, self.config.index_url)

    def resolve_extracts(self, index: GeofabrikIndex) -> List[OsmExtract]:
        """Download and wrap the ``.osm.pbf`` extract(s) covering the extent."""
        if self.config.regions:
            regions = [index.get(r) for r in self.config.regions]
            missing = [r.id for r in regions if not r.pbf_url]
            if missing:
                raise ValueError(f"Regions have no PBF extract available: {missing}")
        else:
            self._guard_large_extent()
            regions = index.select_extracts(self.config.bbox)

        if not regions:
            log.warning("No Geofabrik PBF extract covers the requested extent.")
            return []

        log.info(
            "Selected %d extract(s): %s",
            len(regions),
            ", ".join(r.id for r in regions),
        )
        extracts = []
        for region in regions:
            log.info("Fetching %s", region.pbf_url)
            path = self.downloader.fetch(region.pbf_url)
            extracts.append(OsmExtract(path.as_posix(), self.config.bbox))
        return extracts

    def _guard_large_extent(self) -> None:
        """Block auto-selecting PBF extracts over a planet-scale extent.

        Reached only when PBF layers are requested *and* no ``--region`` was
        given (the auto-select path). The country layer is index-only and never
        gets here, so it stays freely usable at any extent.
        """
        cfg = self.config
        area = bbox_area_sqdeg(cfg.bbox)
        if area <= LARGE_EXTENT_SQDEG or cfg.allow_large_pbf:
            return
        pbf = sorted(layer for layer in cfg.layers if layer in PBF_LAYERS)
        raise ValueError(
            f"Extent spans ~{area:,.0f} sq.deg; auto-selecting PBF extracts for "
            f"{pbf} would download data for nearly the whole planet. Restrict to "
            "'--layers countries', name explicit '--region' ids, or pass "
            "'--allow-large-pbf' to override."
        )

    # ---- build ------------------------------------------------------------

    def build_layers(self) -> Dict[str, gpd.GeoDataFrame]:
        cfg = self.config
        index = self.load_index()

        extracts: List[OsmExtract] = []
        if any(layer in PBF_LAYERS for layer in cfg.layers):
            extracts = self.resolve_extracts(index)

        built: Dict[str, gpd.GeoDataFrame] = {}
        for key in cfg.layers:
            name = LAYER_NAMES[key]
            log.info("Building '%s'", name)
            built[name] = self._build_one(key, index, extracts)
            log.info("  %d feature(s)", len(built[name]))
        return built

    def _build_one(self, key, index, extracts) -> gpd.GeoDataFrame:
        cfg = self.config
        if key == "countries":
            return layers.build_country_layer(index, cfg.bbox, cfg.simplify, cfg.clip)
        if key == "water":
            return layers.build_water_layer(extracts, cfg.bbox, cfg.simplify, cfg.clip)
        if key == "roads":
            return layers.build_roads_layer(extracts, cfg.bbox, cfg.simplify, cfg.clip)
        if key == "airports":
            return layers.build_airports_layer(extracts, cfg.bbox, cfg.clip)
        if key == "population":
            return layers.build_population_layer(extracts, cfg.bbox, cfg.clip)
        if key == "military":
            return layers.build_military_layer(extracts, cfg.bbox, cfg.simplify, cfg.clip)
        raise ValueError(f"Unknown layer: {key}")

    # ---- write ------------------------------------------------------------

    def run(self) -> List[Path]:
        if not self.config.layers:
            raise ValueError("No layers selected to build.")
        built = self.build_layers()
        outputs: List[Path] = []
        if "gpkg" in self.config.formats:
            outputs.append(self._write_gpkg(built))
        if "parquet" in self.config.formats:
            outputs.extend(self._write_parquet(built))
        log.info("Wrote: %s", ", ".join(p.name for p in outputs))
        return outputs

    def _write_gpkg(self, built: Dict[str, gpd.GeoDataFrame]) -> Path:
        output = Path(self.config.output).with_suffix(".gpkg")
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            output.unlink()  # avoid stacking stale layers on append
        for name, gdf in built.items():
            gdf.to_file(output, layer=name, driver="GPKG")
            log.info("  gpkg layer '%s' (%d)", name, len(gdf))
        return output

    def _write_parquet(self, built: Dict[str, gpd.GeoDataFrame]) -> List[Path]:
        # Parquet is one table per file, so each layer becomes its own GeoParquet.
        base = Path(self.config.output)
        base.parent.mkdir(parents=True, exist_ok=True)
        paths = []
        for name, gdf in built.items():
            path = base.with_name(f"{base.stem}_{name}.parquet")
            gdf.to_parquet(path)
            log.info("  parquet '%s' (%d)", path.name, len(gdf))
            paths.append(path)
        return paths
