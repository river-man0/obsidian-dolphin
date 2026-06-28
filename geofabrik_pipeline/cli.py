"""Command-line interface for the Geofabrik data pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .geo_ops import EXTENT_SYNTAX, NAMED_EXTENTS, resolve_extent
from .index import DEFAULT_INDEX_URL
from .pipeline import ALL_LAYERS, DEFAULT_SIMPLIFY, Pipeline, PipelineConfig
from .download import Downloader


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geofabrik-pipeline",
        description=(
            "Ingest OpenStreetMap .osm.pbf extracts from download.geofabrik.de "
            "and produce clipped, simplified GeoPackage/GeoParquet layers: "
            "country polygons, inland water bodies (oceans excluded), a minimal "
            "road network, airports, population centres and military areas."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    extent = parser.add_mutually_exclusive_group(required=False)
    extent.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
        help="Extent to clip to, in WGS84 degrees (lon/lat).",
    )
    extent.add_argument(
        "--extent",
        metavar="NAME",
        help=(
            "Named full-width extent instead of --bbox: "
            f"{', '.join(sorted(set(NAMED_EXTENTS)))}; or a latitude band "
            f"({EXTENT_SYNTAX}). These span all longitudes, so the antimeridian "
            "is never crossed."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("geofabrik.gpkg"),
        help="Output path. Suffix is set per format (.gpkg / .parquet).",
    )
    parser.add_argument(
        "--layers",
        nargs="+",
        choices=ALL_LAYERS,
        default=list(ALL_LAYERS),
        help="Which layers to build.",
    )
    parser.add_argument(
        "--format",
        dest="formats",
        nargs="+",
        choices=("gpkg", "parquet"),
        default=["gpkg"],
        help="Output format(s). Parquet writes one file per layer.",
    )
    parser.add_argument(
        "--region",
        dest="regions",
        action="append",
        help=(
            "Force a specific Geofabrik region id for PBF extracts (e.g. "
            "'north-america/canada'). Repeatable. Default: auto-select by extent."
        ),
    )
    parser.add_argument(
        "--simplify",
        type=float,
        default=DEFAULT_SIMPLIFY,
        help="Simplify tolerance in degrees (0 disables).",
    )
    parser.add_argument(
        "--no-clip",
        action="store_true",
        help="Keep whole geometries instead of clipping to the extent.",
    )
    parser.add_argument(
        "--allow-large-pbf",
        action="store_true",
        help=(
            "Permit auto-selecting PBF extracts over a planet-scale extent "
            "(huge download). The 'countries' layer is unaffected."
        ),
    )
    parser.add_argument(
        "--list-extracts",
        action="store_true",
        help=(
            "Print the granular PBF region id(s) covering the extent (one per "
            "line) and exit, without downloading or building. Feed them back in "
            "one at a time via --region to batch a large extent."
        ),
    )
    parser.add_argument(
        "--list-regions",
        action="store_true",
        help=(
            "Print all available Geofabrik PBF download regions (id, name, "
            "parent, iso2) and exit. The extent and output are ignored."
        ),
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".geofabrik_cache"),
        help="Directory for cached downloads.",
    )
    parser.add_argument(
        "--index-url",
        default=DEFAULT_INDEX_URL,
        help="Override the Geofabrik index location (URL or local path).",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose logging."
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    # pyogrio chats at INFO on every write ("Created N records"); keep it quiet.
    logging.getLogger("pyogrio").setLevel(logging.WARNING)

    log = logging.getLogger("geofabrik_pipeline")

    # Early exit for --list-regions (doesn't need bbox/extent).
    if args.list_regions:
        try:
            config = PipelineConfig(
                bbox=(0.0, 0.0, 1.0, 1.0),  # dummy, unused
                output=args.output,
                index_url=args.index_url,
                cache_dir=args.cache_dir,
            )
            regions = Pipeline(config).list_regions()
            log.info("%d region(s) with PBF downloads", len(regions))
            # Print as tab-separated: id, name, parent, iso2
            for region in regions:
                parts = [region.id, region.name or region.id]
                if region.parent:
                    parts.append(region.parent)
                if region.iso2:
                    parts.append(region.iso2)
                print("\t".join(parts))
            return 0
        except Exception as exc:
            log.error("%s", exc)
            if args.verbose:
                raise
            return 1

    # Normal pipeline run requires bbox or extent.
    if not args.bbox and not args.extent:
        log.error("Either --bbox or --extent is required (or use --list-regions).")
        return 2

    try:
        bbox = tuple(args.bbox) if args.bbox else resolve_extent(args.extent)
    except ValueError as exc:
        log.error("%s", exc)
        return 2

    config = PipelineConfig(
        bbox=bbox,
        output=args.output,
        simplify=args.simplify,
        clip=not args.no_clip,
        layers=tuple(args.layers),
        formats=tuple(args.formats),
        regions=args.regions,
        allow_large_pbf=args.allow_large_pbf,
        cache_dir=args.cache_dir,
        index_url=args.index_url,
    )
    downloader = Downloader(args.cache_dir)
    try:
        pipeline = Pipeline(config, downloader)
        if args.list_extracts:
            regions = pipeline.list_extracts()
            log.info("%d extract(s) cover the extent", len(regions))
            for region in regions:
                print(region.id)
            return 0
        pipeline.run()
    except Exception as exc:  # surface a clean message, full trace in verbose
        log.error("%s", exc)
        if args.verbose:
            raise
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
