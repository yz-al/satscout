"""Minimal STAC API client — enough for collection listing and item search.

Deliberately dependency-light (requests only). Handles the pagination
styles used by Earth Search, Planetary Computer, and LandsatLook, and
retries transient failures (429 rate limiting, 5xx, timeouts) with
exponential backoff, honoring Retry-After when the server sends one.
"""

import time

import requests

USER_AGENT = "satscout/0.1 (+https://github.com/yz-al/deln-gpu)"
TIMEOUT = 30
MAX_RETRIES = 4
BACKOFF_BASE = 1.5  # seconds; grows 1.5, 3, 6, 12
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def _sleep(seconds: float) -> None:  # separated so tests can stub it out
    time.sleep(seconds)


def _request(s: requests.Session, method: str, url: str, json_body=None) -> requests.Response:
    """One HTTP call with retry/backoff for rate limits and transient errors.

    Non-retryable client errors (400/404, and a 400 from an unsupported
    query extension) raise immediately so callers can react.
    """
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            if method == "POST":
                resp = s.post(url, json=json_body, timeout=TIMEOUT)
            else:
                resp = s.get(url, timeout=TIMEOUT)
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                _sleep(BACKOFF_BASE * 2**attempt)
            continue
        if resp.status_code in RETRYABLE_STATUS and attempt < MAX_RETRIES:
            retry_after = resp.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else BACKOFF_BASE * 2**attempt
            except ValueError:
                delay = BACKOFF_BASE * 2**attempt
            _sleep(min(delay, 60.0))
            continue
        resp.raise_for_status()
        return resp
    raise last_exc if last_exc else RuntimeError(f"{method} {url}: retries exhausted")


def list_collections(endpoint: str, max_pages: int = 20) -> list[dict]:
    """GET {endpoint}/collections, following rel=next links."""
    s = _session()
    url = f"{endpoint}/collections"
    collections: list[dict] = []
    for _ in range(max_pages):
        resp = _request(s, "GET", url)
        body = resp.json()
        collections.extend(body.get("collections", []))
        nxt = next(
            (l for l in body.get("links", []) if l.get("rel") == "next" and l.get("href")),
            None,
        )
        if nxt is None or nxt["href"] == url:
            break
        url = nxt["href"]
    return collections


def search_items(
    endpoint: str,
    collections: list[str],
    bbox=None,
    datetime_range: str | None = None,
    query: dict | None = None,
    max_items: int = 200,
    page_limit: int = 100,
) -> list[dict]:
    """POST {endpoint}/search, following next links until max_items.

    `query` uses the STAC query extension, e.g. {"eo:cloud_cover": {"lte": 20}}.
    If the server rejects the query extension, the caller is responsible for
    client-side filtering (see search.py).
    """
    s = _session()
    body: dict = {"collections": collections, "limit": min(page_limit, max_items)}
    if bbox is not None:
        body["bbox"] = list(bbox)
    if datetime_range:
        body["datetime"] = datetime_range
    if query:
        body["query"] = query

    url = f"{endpoint}/search"
    method = "POST"
    items: list[dict] = []
    while len(items) < max_items:
        resp = _request(s, method, url, json_body=body if method == "POST" else None)
        page = resp.json()
        feats = page.get("features", [])
        if not feats:
            break
        items.extend(feats)
        nxt = next((l for l in page.get("links", []) if l.get("rel") == "next"), None)
        if nxt is None:
            break
        # STAC POST paging: the next link may carry a body (possibly to be
        # merged with the request), or be a plain GET href with a token.
        if nxt.get("body"):
            body = {**body, **nxt["body"]} if nxt.get("merge") else nxt["body"]
            url = nxt.get("href", url)
            method = str(nxt.get("method", "POST")).upper()
        elif nxt.get("href"):
            url = nxt["href"]
            method = str(nxt.get("method", "GET")).upper()
        else:
            break
    return items[:max_items]
