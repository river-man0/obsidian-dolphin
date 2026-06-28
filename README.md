# geofabrik-pipeline

A Python data pipeline that turns [Geofabrik](https://download.geofabrik.de/)
`.osm.pbf` extracts into tidy, lightweight **GeoPackage** and/or **GeoParquet**
layers for a region of your choosing.

Given a bounding box, it will:

1. **Ingest** the Geofabrik index and the relevant `*-latest.osm.pbf` extract(s).
2. **Filter & sort** features into the layers below.
3. **Fix invalid geometries** (self-intersections, bow-ties, slivers).
4. **Create country polygons** from the Geofabrik region boundaries.
5. **Create water-body polygons, excluding oceans** (lakes, reservoirs,
   riverbanks, ponds — open sea is never included).
6. **Build a minimal road network**, airports, population centres and military
   areas from the OSM data.
7. **Simplify** geometry slightly to keep the output small, and **clip**
   everything to your requested extent.
8. **Output** as a multi-layer `.gpkg` and/or one GeoParquet file per layer.

## Output layers

| Layer | Geometry | Source | Attributes |
| --- | --- | --- | --- |
| `countries` | polygon | Geofabrik index boundaries | `country_id`, `name`, `iso2` |
| `water_bodies` | polygon | PBF `multipolygons` (inland water) | `osm_id`, `name`, `fclass` |
| `roads` | line | PBF `lines` (`motorway`/`trunk`/`primary`/`secondary` + links) | `osm_id`, `name`, `fclass`, `ref` |
| `airports` | point | PBF `aeroway=aerodrome` nodes + area centroids | `osm_id`, `name` |
| `population_centres` | point | PBF `place=city/town/village` | `osm_id`, `name`, `place`, `population` |
| `military` | polygon | PBF `landuse=military` / `military=*` | `osm_id`, `name` |

All layers are EPSG:4326.

## How it works

Geofabrik publishes [`index-v1.json`](https://download.geofabrik.de/index-v1.json),
a GeoJSON `FeatureCollection` where each feature is a downloadable region: the
feature *geometry* is that region's boundary polygon and the *properties* carry
its id, parent, ISO codes and download URLs (`pbf`, `shp`, ...).

* **Country polygons** come straight from those index boundaries.
* **Everything else** is read from the `.osm.pbf` extract(s) via GDAL's OSM
  driver, using a bundled [`osmconf.ini`](geofabrik_pipeline/osmconf.ini) that
  promotes the tags we filter on (`highway`, `place`, `aeroway`, `natural`,
  `landuse`, `military`, ...) to real columns so filters push down into the
  driver. OSM models oceans/seas as *coastline* (a line layer), so the water
  *area* layer is inland-only; sea/ocean values are dropped as an extra guard.

To minimise downloads, the pipeline auto-selects the **most granular** PBF
extract(s) covering your extent.

> **Note on size.** PBF extracts are large and the OSM driver scans the whole
> file, so prefer the smallest extract that covers your area (e.g. a province
> rather than a continent), or pass `--region` explicitly.

## Install

```bash
pip install -r requirements.txt   # or: pip install .
```

The geospatial stack (`geopandas`, `shapely>=2`, `pyogrio`, `pyarrow`) ships
GDAL in its wheels — no system GDAL required.

## Usage

```bash
# Bounding box is WGS84 degrees: MIN_LON MIN_LAT MAX_LON MAX_LAT

# Greenland, GeoPackage with every layer:
geofabrik-pipeline --bbox -73 59 -11 84 -o greenland.gpkg

# A slice of Canada, only roads + population centres, both formats:
geofabrik-pipeline --bbox -114 50 -113 51 -o calgary \
    --layers roads population --format gpkg parquet

# Force a specific extract instead of auto-selecting:
geofabrik-pipeline --bbox -141 41 -52 84 -o canada.gpkg \
    --region north-america/canada
```

### Named extents (hemispheres and latitude bands)

Large bands that span every longitude — a hemisphere, or "everything north of
40°N" — are awkward to express as a `--bbox` and easy to get wrong around the
antimeridian. Use `--extent` instead (mutually exclusive with `--bbox`):

```bash
# Every country polygon in the northern hemisphere:
geofabrik-pipeline --extent northern-hemisphere --layers countries -o north.gpkg

# Everything north of 40°N:
geofabrik-pipeline --extent north-of:40 --layers countries -o arctic.gpkg
```

| `--extent` value | Resulting bbox (`min_lon min_lat max_lon max_lat`) |
| --- | --- |
| `global` / `world` | `-180 -90 180 90` |
| `northern-hemisphere` / `northern` | `-180 0 180 90` |
| `southern-hemisphere` / `southern` | `-180 -90 180 0` |
| `eastern-hemisphere` / `eastern` | `0 -90 180 90` |
| `western-hemisphere` / `western` | `-180 -90 0 90` |
| `north-of:LAT` | `-180 LAT 180 90` |
| `south-of:LAT` | `-180 -90 180 LAT` |
| `lat-band:LO:HI` | `-180 LO 180 HI` |

Every named extent spans the full `-180..180` longitude range, so it is always a
valid `min_lon < max_lon` box and never straddles the ±180 antimeridian — that
wrap problem only arises for boxes that cross 180° (e.g. Fiji), which still need
to be split into two runs.

> **Heads-up on size.** A hemisphere-scale extent intersects almost every
> Geofabrik region, so building the **PBF-derived** layers (`water`, `roads`,
> `airports`, `population`, `military`) there would auto-download extracts for
> nearly the whole planet. To prevent surprise multi-hundred-GB downloads the
> pipeline refuses that combination unless you pass `--allow-large-pbf`, or name
> explicit `--region` ids. The `countries` layer is index-only and always works
> at any extent.

#### Batching a large extent one region at a time

`--list-extracts` prints the granular PBF region id(s) covering an extent (one
per line, to stdout) and exits without downloading anything — so you can loop
over them and pull each extract separately, clipping every run to the same band:

```bash
# See what a band covers (only the index is fetched):
geofabrik-pipeline --extent north-of:60 --list-extracts

# Build roads for each covered region, clipped to north-of:60, into out/:
mkdir -p out
for region in $(geofabrik-pipeline --extent north-of:60 --list-extracts); do
    geofabrik-pipeline --region "$region" --extent north-of:60 \
        --layers roads --format parquet -o "out/${region//\//_}"
done
```

The selection is the same "most granular extract" logic the auto-selector uses
(`--region` here just covers one at a time). It is hierarchy-based, so an
occasional broad region (e.g. `asia`) can still appear alongside finer ones that
overlap it geographically — eyeball the list and drop any you don't want before
batching.

Common options:

| Option | Description |
| --- | --- |
| `--bbox MIN_LON MIN_LAT MAX_LON MAX_LAT` | Extent to clip to (required unless `--extent`). |
| `--extent NAME` | Named hemisphere / latitude-band extent instead of `--bbox`. |
| `--allow-large-pbf` | Permit PBF layers over a planet-scale extent (huge download). |
| `--list-extracts` | Print the region id(s) covering the extent and exit (for batching). |
| `-o, --output PATH` | Output path; suffix is set per format. |
| `--layers ...` | Any of `countries water roads airports population military` (default: all). |
| `--format gpkg parquet` | One or both output formats (default `gpkg`). |
| `--region north-america/canada` | Force a specific extract id (repeatable). |
| `--simplify 0.0001` | Simplify tolerance in degrees (`0` disables). |
| `--no-clip` | Keep whole geometries instead of clipping. |
| `--cache-dir DIR` | Where downloads are cached (re-used across runs). |
| `--index-url URL` | Override the index location (URL or local path). |
| `-v` | Verbose logging. |

## Library use

```python
from geofabrik_pipeline import Pipeline, PipelineConfig

cfg = PipelineConfig(
    bbox=(-114.2, 50.8, -113.8, 51.2),
    output="calgary.gpkg",
    layers=("roads", "population"),
    formats=("gpkg", "parquet"),
)
Pipeline(cfg).run()
```

## Development

```bash
pip install -e .[test]
pytest
```

The test suite is fully offline: it fabricates Geofabrik-shaped fixtures (an
index document plus a hand-written `.osm` extract, read by the same OSM driver
that parses `.osm.pbf`) so the ingest → clean → clip → write path runs
end-to-end without network access.
