"""Unit tests for the STAC client: retry/backoff, rate limiting, pagination.

All offline — a FakeSession plays the server, scripted with a queue of
responses, so we can simulate exactly the failure modes we're worried
about (AWS throttling with 429s, transient 503s, timeouts, paging).
"""

import pytest
import requests

from satscout import stac
from satscout.stac import _request, list_collections, search_items


class FakeResponse:
    def __init__(self, status=200, json_body=None, headers=None):
        self.status_code = status
        self._json = json_body if json_body is not None else {}
        self.headers = headers or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


class FakeSession:
    """Pops one scripted response (or exception) per request, records calls."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []  # (method, url, json_body)

    def _next(self, method, url, json_body):
        self.calls.append((method, url, json_body))
        if not self.script:
            raise AssertionError("FakeSession script exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, timeout=None):
        return self._next("GET", url, None)

    def post(self, url, json=None, timeout=None):
        return self._next("POST", url, json)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Backoff must not actually sleep in unit tests; record delays instead."""
    delays = []
    monkeypatch.setattr(stac, "_sleep", delays.append)
    return delays


def _use(monkeypatch, session):
    monkeypatch.setattr(stac, "_session", lambda: session)


# ---------------------------------------------------------------- retries

def test_rate_limited_then_succeeds(no_sleep):
    """The AWS-throttling scenario: two 429s, then a 200. Must recover."""
    s = FakeSession([
        FakeResponse(429),
        FakeResponse(429),
        FakeResponse(200, {"ok": True}),
    ])
    resp = _request(s, "GET", "http://x/collections")
    assert resp.json() == {"ok": True}
    assert len(s.calls) == 3
    assert len(no_sleep) == 2  # backed off twice


def test_retry_after_header_is_honored(no_sleep):
    s = FakeSession([
        FakeResponse(429, headers={"Retry-After": "7"}),
        FakeResponse(200, {"ok": True}),
    ])
    _request(s, "GET", "http://x/search")
    assert no_sleep == [7.0]


def test_retry_after_capped_at_60s(no_sleep):
    s = FakeSession([
        FakeResponse(429, headers={"Retry-After": "3600"}),
        FakeResponse(200),
    ])
    _request(s, "GET", "http://x/search")
    assert no_sleep == [60.0]


def test_backoff_grows_exponentially(no_sleep):
    s = FakeSession([FakeResponse(503)] * 3 + [FakeResponse(200)])
    _request(s, "GET", "http://x/search")
    assert no_sleep == [1.5, 3.0, 6.0]


def test_persistent_429_finally_raises(no_sleep):
    """If the rate limiter never relents, surface the 429 (not a hang)."""
    s = FakeSession([FakeResponse(429)] * (stac.MAX_RETRIES + 1))
    with pytest.raises(requests.HTTPError):
        _request(s, "GET", "http://x/search")
    assert len(s.calls) == stac.MAX_RETRIES + 1


def test_timeout_then_recovery(no_sleep):
    s = FakeSession([
        requests.Timeout("read timed out"),
        requests.ConnectionError("reset"),
        FakeResponse(200, {"ok": 1}),
    ])
    assert _request(s, "GET", "http://x/c").json() == {"ok": 1}


def test_persistent_timeout_raises_last_error(no_sleep):
    s = FakeSession([requests.Timeout("t")] * (stac.MAX_RETRIES + 1))
    with pytest.raises(requests.Timeout):
        _request(s, "GET", "http://x/c")


def test_client_error_is_not_retried(no_sleep):
    """400 (e.g. unsupported query extension) must fail fast, not back off."""
    s = FakeSession([FakeResponse(400)])
    with pytest.raises(requests.HTTPError):
        _request(s, "GET", "http://x/search")
    assert len(s.calls) == 1
    assert no_sleep == []


# ------------------------------------------------------------- pagination

def _item(i):
    return {"id": f"item-{i}", "properties": {}}


def test_search_pagination_post_body_next(monkeypatch):
    """Earth Search style: next link carries a POST body with a token."""
    page1 = FakeResponse(200, {
        "features": [_item(1), _item(2)],
        "links": [{"rel": "next", "href": "http://x/search",
                   "method": "POST", "body": {"token": "p2"}, "merge": True}],
    })
    page2 = FakeResponse(200, {"features": [_item(3)], "links": []})
    s = FakeSession([page1, page2])
    _use(monkeypatch, s)
    items = search_items("http://x", ["c"], max_items=10, page_limit=2)
    assert [i["id"] for i in items] == ["item-1", "item-2", "item-3"]
    # merge=True keeps the original body and adds the token
    assert s.calls[1][2]["token"] == "p2"
    assert s.calls[1][2]["collections"] == ["c"]


def test_search_pagination_get_href_next(monkeypatch):
    """Planetary Computer style: next link is a plain GET href."""
    page1 = FakeResponse(200, {
        "features": [_item(1)],
        "links": [{"rel": "next", "href": "http://x/search?token=abc"}],
    })
    page2 = FakeResponse(200, {"features": [_item(2)], "links": []})
    s = FakeSession([page1, page2])
    _use(monkeypatch, s)
    items = search_items("http://x", ["c"], max_items=10)
    assert [i["id"] for i in items] == ["item-1", "item-2"]
    assert s.calls[1][0] == "GET"
    assert s.calls[1][1] == "http://x/search?token=abc"


def test_search_stops_at_max_items(monkeypatch):
    pages = [
        FakeResponse(200, {
            "features": [_item(i), _item(i + 1)],
            "links": [{"rel": "next", "href": "http://x/search", "body": {"page": i}}],
        })
        for i in range(100)
    ]
    s = FakeSession(pages)
    _use(monkeypatch, s)
    items = search_items("http://x", ["c"], max_items=5, page_limit=2)
    assert len(items) == 5
    assert len(s.calls) == 3  # ceil(5/2) pages, then stop — no runaway walk


def test_search_stops_on_empty_page(monkeypatch):
    page = FakeResponse(200, {"features": [], "links": [{"rel": "next", "href": "u"}]})
    s = FakeSession([page])
    _use(monkeypatch, s)
    assert search_items("http://x", ["c"]) == []


def test_search_request_body_shape(monkeypatch):
    s = FakeSession([FakeResponse(200, {"features": []})])
    _use(monkeypatch, s)
    search_items(
        "http://x", ["sentinel-2-l2a"], bbox=(1, 2, 3, 4),
        datetime_range="2024-01-01/2024-02-01",
        query={"eo:cloud_cover": {"lte": 20}}, max_items=50,
    )
    method, url, body = s.calls[0]
    assert (method, url) == ("POST", "http://x/search")
    assert body == {
        "collections": ["sentinel-2-l2a"],
        "limit": 50,
        "bbox": [1, 2, 3, 4],
        "datetime": "2024-01-01/2024-02-01",
        "query": {"eo:cloud_cover": {"lte": 20}},
    }


def test_list_collections_paginated(monkeypatch):
    page1 = FakeResponse(200, {
        "collections": [{"id": "a"}],
        "links": [{"rel": "next", "href": "http://x/collections?page=2"}],
    })
    page2 = FakeResponse(200, {"collections": [{"id": "b"}], "links": []})
    s = FakeSession([page1, page2])
    _use(monkeypatch, s)
    assert [c["id"] for c in list_collections("http://x")] == ["a", "b"]


def test_list_collections_survives_rate_limit(monkeypatch, no_sleep):
    s = FakeSession([
        FakeResponse(429),
        FakeResponse(200, {"collections": [{"id": "a"}], "links": []}),
    ])
    _use(monkeypatch, s)
    assert [c["id"] for c in list_collections("http://x")] == ["a"]
