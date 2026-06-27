"""End-to-end orchestration: index -> extracts -> clean layers -> GeoPackage."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

import geopandas as gpd

from . import layers
from .download import Downloader
from .geo_ops import BBox
from .index import DEFAULT_INDEX_URL, GeofabrikIndex

log = logging.getLogger("geofabrik_pipeline")

# Default simplify tolerance in degrees (~10 m at the equator): "slightly".
DEFAULT_SIMPLIFY = 0.0001


@dataclass
class PipelineConfig:
    bbox: BBox
    output: Path
    simplify: float = DEFAULT_SIMPLIFY
    clip: bool = True
    layers: Sequence[str] = ("countries", "water")
    regions: Optional[Sequence[str]] = None  # force specific extract ids
    cache_dir: Path = field(default_factory=lambda: Path(".geofabrik_cache"))
    index_url: str = DEFAULT_INDEX_URL


class Pipeline:
    def __init__(self, config: PipelineConfig, downloader: Optional[Downloader] = None):
        self.config = config
        self.downloader = downloader or Downloader(config.cache_dir)

    # ---- stages -----------------------------------------------------------

    def load_index(self) -> GeofabrikIndex:
        log.info("Loading Geofabrik index from %s", self.config.index_url)
        return GeofabrikIndex.load(self.downloader, self.config.index_url)

    def resolve_extracts(self, index: GeofabrikIndex) -> List[str]:
        """Resolve the set of shp.zip sources to read water bodies from."""
        if self.config.regions:
            regions = [index.get(r) for r in self.config.regions]
            missing = [r.id for r in regions if not r.shp_url]
            if missing:
                raise ValueError(
                    f"Regions have no shapefile extract available: {missing}"
                )
        else:
            regions = index.select_extracts(self.config.bbox)

        if not regions:
            log.warning(
                "No Geofabrik shapefile extract covers the requested extent."
            )
        else:
            log.info(
                "Selected %d extract(s): %s",
                len(regions),
                ", ".join(r.id for r in regions),
            )
        return [self.downloader.fetch(r.shp_url).as_posix() for r in regions]

    def build_countries(self, index: GeofabrikIndex) -> gpd.GeoDataFrame:
        log.info("Building country polygons")
        gdf = layers.build_country_layer(
            index, self.config.bbox, self.config.simplify, self.config.clip
        )
        log.info("  %d country polygon(s)", len(gdf))
        return gdf

    def build_water(self, index: GeofabrikIndex) -> gpd.GeoDataFrame:
        log.info("Building water-body polygons (excluding oceans)")
        sources = self.resolve_extracts(index)
        gdf = layers.build_water_layer(
            sources, self.config.bbox, self.config.simplify, self.config.clip
        )
        log.info("  %d water-body polygon(s)", len(gdf))
        return gdf

    # ---- driver -----------------------------------------------------------

    def run(self) -> Path:
        index = self.load_index()
        output = Path(self.config.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            output.unlink()  # GeoPackage append would otherwise stack stale layers

        wrote_any = False
        if "countries" in self.config.layers:
            countries = self.build_countries(index)
            self._write_layer(countries, "countries", output)
            wrote_any = True

        if "water" in self.config.layers:
            water = self.build_water(index)
            self._write_layer(water, "water_bodies", output)
            wrote_any = True

        if not wrote_any:
            raise ValueError("No layers selected to build.")

        log.info("Wrote %s", output)
        return output

    @staticmethod
    def _write_layer(gdf: gpd.GeoDataFrame, layer: str, output: Path) -> None:
        # Always create the layer, even when empty, so downstream consumers find
        # a predictable schema.
        gdf.to_file(output, layer=layer, driver="GPKG")
        log.info("  -> layer '%s' (%d features)", layer, len(gdf))
