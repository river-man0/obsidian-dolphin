import json

import pytest

from geofabrik_pipeline.download import Downloader
from geofabrik_pipeline.geo_ops import bbox_area_sqdeg, resolve_extent
from geofabrik_pipeline.index import GeofabrikIndex
from geofabrik_pipeline.pipeline import Pipeline, PipelineConfig


def test_named_hemispheres():
    assert resolve_extent("northern-hemisphere") == (-180.0, 0.0, 180.0, 90.0)
    assert resolve_extent("southern-hemisphere") == (-180.0, -90.0, 180.0, 0.0)
    assert resolve_extent("eastern-hemisphere") == (0.0, -90.0, 180.0, 90.0)
    assert resolve_extent("western-hemisphere") == (-180.0, -90.0, 0.0, 90.0)
    assert resolve_extent("global") == (-180.0, -90.0, 180.0, 90.0)


def test_named_polar_circles():
    arctic = resolve_extent("arctic-circle")
    assert arctic[1] == pytest.approx(66.5627)  # min_lat at Arctic Circle
    assert arctic == resolve_extent("arctic")
    antarctic = resolve_extent("antarctic-circle")
    assert antarctic[3] == pytest.approx(-66.5627)  # max_lat at Antarctic Circle
    assert antarctic == resolve_extent("antarctic")


def test_named_extents_are_case_and_alias_insensitive():
    assert resolve_extent("Northern") == resolve_extent("NORTHERN-HEMISPHERE")
    assert resolve_extent("world") == resolve_extent("global")


def test_parametric_latitude_bands():
    assert resolve_extent("north-of:40") == (-180.0, 40.0, 180.0, 90.0)
    assert resolve_extent("south-of:-30") == (-180.0, -90.0, 180.0, -30.0)
    assert resolve_extent("lat-band:10:40") == (-180.0, 10.0, 180.0, 40.0)


def test_extents_never_cross_the_antimeridian():
    # Every resolved extent is a valid min_lon < max_lon box (no +/-180 wrap).
    for spec in ("northern-hemisphere", "global", "north-of:40", "lat-band:-10:10"):
        min_lon, _, max_lon, _ = resolve_extent(spec)
        assert min_lon < max_lon


@pytest.mark.parametrize(
    "spec",
    ["", "nonsense", "north-of:100", "north-of:abc", "lat-band:40:10", "lat-band:5"],
)
def test_invalid_extents_raise(spec):
    with pytest.raises(ValueError):
        resolve_extent(spec)


def test_bbox_area_sqdeg():
    assert bbox_area_sqdeg((-180.0, 0.0, 180.0, 90.0)) == pytest.approx(32400.0)
    assert bbox_area_sqdeg((0.0, 0.0, 10.0, 10.0)) == pytest.approx(100.0)


def _index(synthetic_dataset):
    data = json.loads(synthetic_dataset["index_path"].read_text())
    return GeofabrikIndex.from_geojson(data)


def test_large_extent_guards_pbf_layers(synthetic_dataset, tmp_path):
    cfg = PipelineConfig(
        bbox=resolve_extent("northern-hemisphere"),
        output=tmp_path / "out.gpkg",
        layers=("roads",),
        index_url=synthetic_dataset["index_path"].as_uri(),
        cache_dir=tmp_path / "cache",
    )
    pipeline = Pipeline(cfg, Downloader(tmp_path / "cache"))
    with pytest.raises(ValueError, match="whole planet"):
        pipeline.resolve_extracts(_index(synthetic_dataset))


def test_large_extent_allowed_with_override(synthetic_dataset, tmp_path):
    cfg = PipelineConfig(
        bbox=resolve_extent("northern-hemisphere"),
        output=tmp_path / "out.gpkg",
        layers=("roads",),
        allow_large_pbf=True,
        index_url=synthetic_dataset["index_path"].as_uri(),
        cache_dir=tmp_path / "cache",
    )
    pipeline = Pipeline(cfg, Downloader(tmp_path / "cache"))
    # Override lets selection proceed (the synthetic extract covers the extent).
    extracts = pipeline.resolve_extracts(_index(synthetic_dataset))
    assert len(extracts) == 1


def test_list_extracts_returns_granular_regions(synthetic_dataset, tmp_path):
    # A global extent intersects every region; the whole-country extract is an
    # ancestor of the northern one, so only the granular descendant is listed.
    cfg = PipelineConfig(
        bbox=resolve_extent("global"),
        output=tmp_path / "out.gpkg",
        index_url=synthetic_dataset["index_path"].as_uri(),
        cache_dir=tmp_path / "cache",
    )
    regions = Pipeline(cfg, Downloader(tmp_path / "cache")).list_extracts()
    assert [r.id for r in regions] == ["europe/wonderland/north"]
    # Listing never downloads, so it is not blocked by the large-extent guard.


def test_list_extracts_honours_explicit_regions(synthetic_dataset, tmp_path):
    cfg = PipelineConfig(
        bbox=resolve_extent("global"),
        output=tmp_path / "out.gpkg",
        regions=["europe/wonderland"],
        index_url=synthetic_dataset["index_path"].as_uri(),
        cache_dir=tmp_path / "cache",
    )
    regions = Pipeline(cfg, Downloader(tmp_path / "cache")).list_extracts()
    assert [r.id for r in regions] == ["europe/wonderland"]


def test_large_extent_does_not_block_countries(synthetic_dataset, tmp_path):
    # countries is index-only and never resolves extracts, so a huge extent is fine.
    cfg = PipelineConfig(
        bbox=resolve_extent("global"),
        output=tmp_path / "out.gpkg",
        layers=("countries",),
        formats=("gpkg",),
        index_url=synthetic_dataset["index_path"].as_uri(),
        cache_dir=tmp_path / "cache",
    )
    outputs = Pipeline(cfg, Downloader(tmp_path / "cache")).run()
    assert outputs
