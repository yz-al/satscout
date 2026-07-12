"""Offline tests for collection scoring, item normalization, and the report.

Network-dependent behavior is covered separately by tests marked
@pytest.mark.network (skipped by default in CI-like environments).
"""

import pytest

from satscout.discover import score_collection
from satscout.report import build_report
from satscout.search import _normalize

S2_COLLECTION = {
    "id": "sentinel-2-l2a",
    "title": "Sentinel-2 Level-2A",
    "description": "Global Sentinel-2 data from the MSI onboard Sentinel-2, "
    "atmospherically corrected surface reflectance.",
    "keywords": ["sentinel", "esa", "msi", "reflectance"],
    "extent": {
        "spatial": {"bbox": [[-180, -90, 180, 90]]},
        "temporal": {"interval": [["2015-06-27T10:25:31Z", None]]},
    },
}


def test_score_keyword_match():
    assert score_collection(S2_COLLECTION, ["sentinel-2", "reflectance"]) == 1.0
    assert score_collection(S2_COLLECTION, ["sentinel-2", "thermal"]) == 0.5
    assert score_collection(S2_COLLECTION, ["landsat"]) is None


def test_score_no_keywords_passes_filters():
    assert score_collection(S2_COLLECTION, []) == 1.0


def test_score_temporal_hard_filter():
    # collection starts 2015 → a 2010 study period can't be covered
    assert score_collection(S2_COLLECTION, ["sentinel"], start="2010-01-01", end="2014-12-31") is None
    assert score_collection(S2_COLLECTION, ["sentinel"], start="2020-01-01", end="2020-12-31") == 1.0
    # open-ended collection end covers any future range
    assert score_collection(S2_COLLECTION, ["sentinel"], start="2030-01-01", end=None) == 1.0


def test_score_spatial_hard_filter():
    regional = {**S2_COLLECTION, "extent": {
        "spatial": {"bbox": [[-125, 24, -66, 50]]},  # CONUS
        "temporal": {"interval": [["2015-01-01T00:00:00Z", None]]},
    }}
    assert score_collection(regional, ["sentinel"], bbox=(-122, 37, -121, 38)) == 1.0
    assert score_collection(regional, ["sentinel"], bbox=(10, 45, 11, 46)) is None  # Europe


FAKE_ITEM = {
    "id": "S2B_10SEG_20240712",
    "collection": "sentinel-2-l2a",
    "bbox": [-122.0, 37.0, -121.0, 38.0],
    "properties": {
        "datetime": "2024-07-12T18:49:19Z",
        "eo:cloud_cover": 3.2,
        "platform": "sentinel-2b",
        "gsd": 10,
    },
    "assets": {"red": {}, "green": {}, "blue": {}, "nir": {}},
}


def test_normalize_item():
    s = _normalize(FAKE_ITEM)
    assert s.id == "S2B_10SEG_20240712"
    assert s.cloud_cover == pytest.approx(3.2)
    assert s.platform == "sentinel-2b"
    assert s.gsd == 10
    assert s.assets == ["blue", "green", "nir", "red"]


def test_normalize_item_without_cloud_cover():
    item = {"id": "sar-1", "properties": {"datetime": "2024-01-01T00:00:00Z"}}
    s = _normalize(item)
    assert s.cloud_cover is None
    assert s.assets == []


def _scene(dt, cc):
    item = {
        "id": dt,
        "collection": "c",
        "properties": {"datetime": dt, "eo:cloud_cover": cc, "platform": "p", "gsd": 10},
        "assets": {"red": {}},
    }
    return _normalize(item)


def test_report_stats_and_verdicts():
    scenes = [
        _scene("2024-01-01T00:00:00Z", 5),
        _scene("2024-01-11T00:00:00Z", 50),
        _scene("2024-04-01T00:00:00Z", 15),  # 81-day gap
    ]
    rep = build_report("c", scenes, cloud_threshold=20)
    assert rep.n_scenes == 3
    assert rep.first == "2024-01-01" and rep.last == "2024-04-01"
    assert rep.max_gap_days == pytest.approx(81, abs=0.1)
    assert rep.cloud["median"] == 15
    assert rep.cloud["pct_under_20"] == pytest.approx(66.7, abs=0.1)
    assert any("temporal gap" in v for v in rep.verdicts)


def test_report_empty():
    rep = build_report("c", [])
    assert rep.n_scenes == 0
    assert any("NO SCENES" in v for v in rep.verdicts)


@pytest.mark.network
def test_live_earth_search_sentinel2():
    """Live smoke: a summer week over San Francisco has Sentinel-2 scenes."""
    from satscout.search import search

    scenes = search(
        "earth-search",
        "sentinel-2-l2a",
        bbox=(-122.5, 37.6, -122.3, 37.9),
        start="2024-07-01",
        end="2024-07-15",
        max_cloud=80,
        max_items=10,
    )
    assert scenes, "expected at least one Sentinel-2 scene over SF in July 2024"
    assert all(s.cloud_cover is None or s.cloud_cover <= 80 for s in scenes)


@pytest.mark.network
def test_live_discover_finds_sentinel2():
    from satscout.discover import discover

    hits = discover(["sentinel-2"], catalog_ids=["earth-search"], limit=10)
    assert any("sentinel-2" in h.collection_id for h in hits)
