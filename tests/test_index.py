import json

from geofabrik_pipeline.download import Downloader
from geofabrik_pipeline.index import GeofabrikIndex


def _load(synthetic_dataset):
    data = json.loads(synthetic_dataset["index_path"].read_text())
    return GeofabrikIndex.from_geojson(data)


def test_country_detection(synthetic_dataset):
    idx = _load(synthetic_dataset)
    assert idx.get("europe/wonderland").is_country is True
    # sub-region (has iso3166-2) is not a country
    assert idx.get("europe/wonderland/north").is_country is False
    # continent (no iso code) is not a country
    assert idx.get("europe").is_country is False


def test_countries_in_extent(synthetic_dataset):
    idx = _load(synthetic_dataset)
    countries = idx.countries_in(synthetic_dataset["bbox"])
    assert list(countries["id"]) == ["europe/wonderland"]


def test_is_ancestor(synthetic_dataset):
    idx = _load(synthetic_dataset)
    assert idx.is_ancestor("europe", "europe/wonderland/north")
    assert idx.is_ancestor("europe/wonderland", "europe/wonderland/north")
    assert not idx.is_ancestor("europe/wonderland/north", "europe/wonderland")


def test_select_extracts_prefers_granular(synthetic_dataset):
    idx = _load(synthetic_dataset)
    selected = idx.select_extracts(synthetic_dataset["bbox"])
    ids = [r.id for r in selected]
    # The whole-country extract is an ancestor of the northern one -> dropped.
    assert ids == ["europe/wonderland/north"]


def test_load_via_downloader(synthetic_dataset, tmp_path):
    dl = Downloader(tmp_path / "cache")
    idx = GeofabrikIndex.load(dl, synthetic_dataset["index_path"].as_uri())
    assert idx.get("europe/wonderland").iso2 == "WL"
