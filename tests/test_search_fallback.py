"""The cloud-cover filter must work even on servers without the STAC
query extension: satscout retries the search plain and filters
client-side on the returned metadata."""

import pytest
import requests

from satscout import search as search_mod


def _item(i, cc):
    return {
        "id": f"scene-{i}",
        "collection": "c",
        "properties": {"datetime": "2024-01-01T00:00:00Z", "eo:cloud_cover": cc},
        "assets": {},
    }


def test_query_extension_rejected_falls_back_to_client_filter(monkeypatch):
    calls = []

    def fake_search_items(endpoint, collections, bbox=None, datetime_range=None,
                          query=None, max_items=200, page_limit=100):
        calls.append(query)
        if query is not None:  # server that 400s on the query extension
            raise requests.HTTPError("400 Bad Request")
        return [_item(1, 5.0), _item(2, 55.0), _item(3, 10.0)]

    monkeypatch.setattr(search_mod, "search_items", fake_search_items)
    scenes = search_mod.search("earth-search", "c", max_cloud=20)
    assert calls == [{"eo:cloud_cover": {"lte": 20}}, None]  # tried, then fell back
    assert [s.id for s in scenes] == ["scene-1", "scene-3"]  # 55% one filtered out


def test_no_cloud_filter_passes_query_none(monkeypatch):
    def fake_search_items(endpoint, collections, **kw):
        assert kw.get("query") is None
        return [_item(1, None)]

    monkeypatch.setattr(search_mod, "search_items", fake_search_items)
    scenes = search_mod.search("earth-search", "c")
    assert len(scenes) == 1


def test_scenes_without_cloud_metadata_survive_the_filter(monkeypatch):
    """SAR/DEM scenes have no eo:cloud_cover — must not be dropped."""
    def fake_search_items(endpoint, collections, **kw):
        return [_item(1, None), _item(2, 90.0)]

    monkeypatch.setattr(search_mod, "search_items", fake_search_items)
    scenes = search_mod.search("earth-search", "c", max_cloud=20)
    assert [s.id for s in scenes] == ["scene-1"]


def test_server_side_filter_excluding_everything_falls_back(monkeypatch):
    """Regression (found live): a server-side eo:cloud_cover query drops SAR
    scenes that have no cloud property at all. An empty filtered result must
    trigger an unfiltered retry so those scenes come back."""
    calls = []

    def fake_search_items(endpoint, collections, bbox=None, datetime_range=None,
                          query=None, max_items=200, page_limit=100):
        calls.append(query)
        if query is not None:
            return []  # server-side filter excludes property-less items
        return [_item(1, None), _item(2, None)]

    monkeypatch.setattr(search_mod, "search_items", fake_search_items)
    scenes = search_mod.search("earth-search", "sentinel-1-grd", max_cloud=20)
    assert calls == [{"eo:cloud_cover": {"lte": 20}}, None]
    assert [s.id for s in scenes] == ["scene-1", "scene-2"]


def test_error_without_query_propagates(monkeypatch):
    def fake_search_items(endpoint, collections, **kw):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(search_mod, "search_items", fake_search_items)
    with pytest.raises(requests.ConnectionError):
        search_mod.search("earth-search", "c")


def test_datetime_range_formatting(monkeypatch):
    seen = {}

    def fake_search_items(endpoint, collections, bbox=None, datetime_range=None, **kw):
        seen["dt"] = datetime_range
        return []

    monkeypatch.setattr(search_mod, "search_items", fake_search_items)
    search_mod.search("earth-search", "c", start="2024-01-01", end="2024-02-01")
    assert seen["dt"] == "2024-01-01T00:00:00Z/2024-02-01T23:59:59Z"
    search_mod.search("earth-search", "c", start="2024-01-01")
    assert seen["dt"] == "2024-01-01T00:00:00Z/.."
    search_mod.search("earth-search", "c", end="2024-02-01")
    assert seen["dt"] == "../2024-02-01T23:59:59Z"


def test_unknown_catalog_raises():
    with pytest.raises(KeyError, match="unknown catalog"):
        search_mod.search("nope", "c")
