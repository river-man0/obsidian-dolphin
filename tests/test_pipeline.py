import geopandas as gpd
import pyogrio

from geofabrik_pipeline.download import Downloader
from geofabrik_pipeline.layers import build_water_layer
from geofabrik_pipeline.pipeline import Pipeline, PipelineConfig


def test_build_water_layer_clips_and_excludes_ocean(synthetic_dataset):
    bbox = synthetic_dataset["bbox"]
    gdf = build_water_layer(
        [synthetic_dataset["north_extract"].as_posix()],
        bbox=bbox,
        tolerance=0.0,
        clip=True,
    )
    assert not gdf.empty
    # All geometry must be valid and inside the extent after clipping.
    assert gdf.geometry.is_valid.all()
    minx, miny, maxx, maxy = gdf.total_bounds
    assert minx >= bbox[0] - 1e-9 and maxx <= bbox[2] + 1e-9
    assert miny >= bbox[1] - 1e-9 and maxy <= bbox[3] + 1e-9


def test_pipeline_end_to_end(synthetic_dataset, tmp_path):
    out = tmp_path / "out.gpkg"
    config = PipelineConfig(
        bbox=synthetic_dataset["bbox"],
        output=out,
        simplify=0.0001,
        cache_dir=tmp_path / "cache",
        index_url=synthetic_dataset["index_path"].as_uri(),
    )
    Pipeline(config, Downloader(tmp_path / "cache")).run()

    assert out.exists()
    layers = {name for name, _ in pyogrio.list_layers(out)}
    assert {"countries", "water_bodies"} <= layers

    countries = gpd.read_file(out, layer="countries")
    assert list(countries["iso2"]) == ["WL"]
    assert countries.geometry.is_valid.all()

    water = gpd.read_file(out, layer="water_bodies")
    assert not water.empty
    assert water.geometry.is_valid.all()
    # Clipped to extent.
    minx, miny, maxx, maxy = water.total_bounds
    bbox = synthetic_dataset["bbox"]
    assert maxx <= bbox[2] + 1e-9 and maxy <= bbox[3] + 1e-9


def test_pipeline_countries_only(synthetic_dataset, tmp_path):
    out = tmp_path / "countries.gpkg"
    config = PipelineConfig(
        bbox=synthetic_dataset["bbox"],
        output=out,
        layers=("countries",),
        cache_dir=tmp_path / "cache",
        index_url=synthetic_dataset["index_path"].as_uri(),
    )
    Pipeline(config, Downloader(tmp_path / "cache")).run()
    layers = {name for name, _ in pyogrio.list_layers(out)}
    assert layers == {"countries"}
