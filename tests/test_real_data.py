"""Real-data tests against the live public STAC APIs (marked `network`).

Run with:  pytest -m network -v

These exist to answer the practical worries:
  * Does the AWS-hosted catalog (Earth Search) actually answer our
    queries, including bursts of back-to-back requests (rate limiting)?
  * Does server-side cloud-cover filtering really work there?
  * Does pagination walk across multiple pages correctly on real servers?
  * Do all three catalogs return sane, normalizable metadata?
"""

import time

import pytest

from satscout.discover import discover
from satscout.report import build_report
from satscout.search import search
from satscout.stac import list_collections, search_items

pytestmark = pytest.mark.network

SF = (-122.5, 37.6, -122.3, 37.9)
CENTRAL_VALLEY = (-121.5, 36.5, -120.5, 37.5)


# ------------------------------------------------------- Earth Search (AWS)

def test_earth_search_lists_collections():
    colls = list_collections("https://earth-search.aws.element84.com/v1")
    ids = {c["id"] for c in colls}
    assert "sentinel-2-l2a" in ids
    assert "sentinel-1-grd" in ids


def test_earth_search_server_side_cloud_filter():
    """The exact pain point: cloud cover must be filterable with no downloads."""
    scenes = search(
        "earth-search", "sentinel-2-l2a", bbox=SF,
        start="2024-06-01", end="2024-08-31", max_cloud=10, max_items=50,
    )
    assert scenes, "expected low-cloud Sentinel-2 scenes over SF in summer 2024"
    assert all(s.cloud_cover is not None and s.cloud_cover <= 10 for s in scenes)
    assert all(s.datetime and s.datetime.startswith("2024-") for s in scenes)


def test_earth_search_pagination_walks_multiple_pages():
    items = search_items(
        "https://earth-search.aws.element84.com/v1",
        ["sentinel-2-l2a"], bbox=CENTRAL_VALLEY,
        datetime_range="2023-01-01T00:00:00Z/2023-12-31T23:59:59Z",
        max_items=250, page_limit=100,
    )
    assert len(items) == 250  # a year over a big AOI has >250 scenes → 3 pages
    assert len({i["id"] for i in items}) == 250  # no duplicates across pages


def test_earth_search_burst_no_unhandled_rate_limit():
    """10 back-to-back searches. If AWS throttles, the client's backoff
    must absorb it — the burst has to complete without an exception."""
    t0 = time.monotonic()
    for i in range(10):
        scenes = search(
            "earth-search", "sentinel-2-l2a", bbox=SF,
            start="2024-07-01", end="2024-07-31", max_items=5,
        )
        assert scenes, f"burst request {i} returned nothing"
    elapsed = time.monotonic() - t0
    # generous ceiling: even with a few 429-backoffs this fits comfortably
    assert elapsed < 120, f"burst took {elapsed:.0f}s — throttled beyond usability"


def test_sar_scenes_have_no_cloud_cover_and_are_kept():
    scenes = search(
        "earth-search", "sentinel-1-grd", bbox=SF,
        start="2024-07-01", end="2024-07-31", max_cloud=20, max_items=5,
    )
    assert scenes, "expected Sentinel-1 SAR scenes over SF"
    assert all(s.cloud_cover is None for s in scenes)  # SAR: no eo:cloud_cover


# -------------------------------------------------- other catalogs

def test_planetary_computer_search():
    scenes = search(
        "planetary-computer", "sentinel-2-l2a", bbox=SF,
        start="2024-07-01", end="2024-07-31", max_cloud=50, max_items=10,
    )
    assert scenes
    assert all(s.cloud_cover is None or s.cloud_cover <= 50 for s in scenes)


def test_usgs_landsatlook_search():
    scenes = search(
        "usgs-landsatlook", "landsat-c2l2-sr", bbox=SF,
        start="2024-06-01", end="2024-08-31", max_items=10,
    )
    assert scenes, "expected Landsat C2 L2 SR scenes over SF"
    assert any(s.platform for s in scenes)


# -------------------------------------------------- full workflows, live

def test_discover_all_catalogs_end_to_end():
    hits = discover(
        ["sentinel-2"], bbox=SF, start="2023-01-01", end="2023-12-31", limit=30
    )
    catalogs_seen = {h.catalog for h in hits}
    assert "earth-search" in catalogs_seen
    assert "planetary-computer" in catalogs_seen
    assert any("sentinel-2" in h.collection_id for h in hits)
    # ranking: scores are sorted descending
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_check_report_end_to_end():
    scenes = search(
        "earth-search", "sentinel-2-l2a", bbox=CENTRAL_VALLEY,
        start="2022-06-01", end="2022-09-30", max_cloud=20, max_items=200,
    )
    rep = build_report("sentinel-2-l2a", scenes)
    assert rep.n_scenes > 50
    assert rep.cloud and rep.cloud["max"] <= 20
    assert rep.max_gap_days is not None and rep.max_gap_days < 30
    assert "sentinel-2a" in rep.platforms or "sentinel-2b" in rep.platforms
    assert "red" in rep.common_assets and "nir" in rep.common_assets
