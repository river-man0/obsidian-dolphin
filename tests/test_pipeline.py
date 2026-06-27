import geopandas as gpd
import pyogrio

from geofabrik_pipeline.download import Downloader
from geofabrik_pipeline.pipeline import ALL_LAYERS, Pipeline, PipelineConfig

EXPECTED_LAYERS = {
    "countries", "water_bodies", "roads",
    "airports", "population_centres", "military",
}


def _config(synthetic_dataset, tmp_path, **kw):
    return PipelineConfig(
        bbox=synthetic_dataset["bbox"],
        output=tmp_path / "out.gpkg",
        cache_dir=tmp_path / "cache",
        index_url=synthetic_dataset["index_path"].as_uri(),
        **kw,
    )


def test_pipeline_all_layers_gpkg(synthetic_dataset, tmp_path):
    cfg = _config(synthetic_dataset, tmp_path)
    [out] = Pipeline(cfg, Downloader(tmp_path / "cache")).run()

    assert out.exists()
    layers = {name for name, _ in pyogrio.list_layers(out)}
    assert EXPECTED_LAYERS <= layers

    countries = gpd.read_file(out, layer="countries")
    assert list(countries["iso2"]) == ["WL"]

    for layer in ("water_bodies", "roads", "airports", "population_centres", "military"):
        gdf = gpd.read_file(out, layer=layer)
        assert not gdf.empty, layer
        assert gdf.geometry.is_valid.all(), layer
        # Everything is inside the requested extent.
        minx, miny, maxx, maxy = gdf.total_bounds
        bbox = synthetic_dataset["bbox"]
        assert maxx <= bbox[2] + 1e-9 and maxy <= bbox[3] + 1e-9, layer


def test_pipeline_parquet_output(synthetic_dataset, tmp_path):
    cfg = _config(
        synthetic_dataset, tmp_path,
        layers=("countries", "roads"), formats=("parquet",),
    )
    outputs = Pipeline(cfg, Downloader(tmp_path / "cache")).run()
    names = {p.name for p in outputs}
    assert names == {"out_countries.parquet", "out_roads.parquet"}
    for p in outputs:
        gdf = gpd.read_parquet(p)
        assert gdf.crs is not None


def test_pipeline_both_formats(synthetic_dataset, tmp_path):
    cfg = _config(
        synthetic_dataset, tmp_path,
        layers=("roads",), formats=("gpkg", "parquet"),
    )
    outputs = Pipeline(cfg, Downloader(tmp_path / "cache")).run()
    suffixes = sorted(p.suffix for p in outputs)
    assert suffixes == [".gpkg", ".parquet"]


def test_default_layers_cover_all(synthetic_dataset, tmp_path):
    # The default config builds every documented layer.
    assert set(ALL_LAYERS) == {
        "countries", "water", "roads", "airports", "population", "military"
    }
