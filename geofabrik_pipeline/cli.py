"""Command-line interface for the Geofabrik data pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

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
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
        required=True,
        help="Extent to clip to, in WGS84 degrees (lon/lat).",
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

    config = PipelineConfig(
        bbox=tuple(args.bbox),
        output=args.output,
        simplify=args.simplify,
        clip=not args.no_clip,
        layers=tuple(args.layers),
        formats=tuple(args.formats),
        regions=args.regions,
        cache_dir=args.cache_dir,
        index_url=args.index_url,
    )
    downloader = Downloader(args.cache_dir)
    try:
        Pipeline(config, downloader).run()
    except Exception as exc:  # surface a clean message, full trace in verbose
        logging.getLogger("geofabrik_pipeline").error("%s", exc)
        if args.verbose:
            raise
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
