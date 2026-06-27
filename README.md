# geofabrik-pipeline

A small Python data pipeline that turns [Geofabrik](https://download.geofabrik.de/)
OpenStreetMap extracts into a tidy, lightweight **GeoPackage** for a region of
your choosing.

Given a bounding box, it will:

1. **Ingest** the Geofabrik index and the relevant `*-free.shp.zip` extract(s).
2. **Filter & sort** features (inland water areas, country boundaries).
3. **Fix invalid geometries** (self-intersections, bow-ties, slivers).
4. **Create country polygons** from the Geofabrik region boundaries.
5. **Create water-body polygons, excluding oceans** (lakes, reservoirs,
   riverbanks, ponds — open sea is never included).
6. **Simplify** the geometry slightly to keep the output small.
7. **Clip** every geometry to your requested extent.
8. **Output** everything as layers in a single `.gpkg`.

## How it works

Geofabrik publishes [`index-v1.json`](https://download.geofabrik.de/index-v1.json),
a GeoJSON `FeatureCollection` where each feature is a downloadable region: the
feature *geometry* is that region's boundary polygon and the *properties* carry
its id, parent, ISO codes and download URLs.

* **Country polygons** come straight from those index boundaries — no heavy
  download is needed to draw national outlines.
* **Water bodies** come from the `gis_osm_water_a_free_1` layer inside the
  `*-free.shp.zip` extract(s). OSM models oceans/seas as *coastline* (a separate
  layer), so this area layer is inland-water only; the pipeline additionally
  drops any `ocean`/`sea` feature class as an explicit guard.

To minimise downloads, the pipeline auto-selects the **most granular** extracts
covering your extent (e.g. individual German states rather than all of Germany).

## Install

```bash
pip install -r requirements.txt   # or: pip install .
```

The geospatial stack (`geopandas`, `shapely>=2`, `pyogrio`) needs GDAL, which
ships with the wheels — no system GDAL required.

## Usage

```bash
# Bounding box is WGS84 degrees: MIN_LON MIN_LAT MAX_LON MAX_LAT
geofabrik-pipeline --bbox 13.0 52.3 13.8 52.7 --output berlin.gpkg
```

Common options:

| Option | Description |
| --- | --- |
| `--bbox MIN_LON MIN_LAT MAX_LON MAX_LAT` | Extent to clip to (required). |
| `-o, --output PATH` | Output GeoPackage (default `geofabrik.gpkg`). |
| `--layers countries water` | Which layers to build. |
| `--region europe/germany/berlin` | Force a specific extract id (repeatable). |
| `--simplify 0.0001` | Simplify tolerance in degrees (`0` disables). |
| `--no-clip` | Keep whole geometries instead of clipping. |
| `--cache-dir DIR` | Where downloads are cached (re-used across runs). |
| `--index-url URL` | Override the index location (URL or local path). |
| `-v` | Verbose logging. |

### Output

A single GeoPackage with up to two layers (all EPSG:4326):

* `countries` — `country_id`, `name`, `iso2`, geometry.
* `water_bodies` — `osm_id`, `fclass`, `name`, geometry.

## Library use

```python
from geofabrik_pipeline import Pipeline, PipelineConfig

cfg = PipelineConfig(bbox=(13.0, 52.3, 13.8, 52.7), output="berlin.gpkg")
Pipeline(cfg).run()
```

## Development

```bash
pip install -e .[test]
pytest
```

The test suite is fully offline: it fabricates Geofabrik-shaped fixtures (an
index document plus stand-in extracts referenced by `file://` URLs) so the
ingest → clean → clip → write path runs end-to-end without network access.
