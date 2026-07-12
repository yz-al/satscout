"""Item-level (scene-level) search with metadata-only vetting.

The pain point this solves, verbatim from user research: "I find data on
AWS, sometimes need to dwl metadata to see for example what is the cloud
cover in the case of optical data." Here the STAC API is queried directly
for scene properties — cloud cover, resolution, platform, bands — so no
metadata files (let alone imagery) need to be downloaded to vet a dataset.
"""

from dataclasses import dataclass

from .aoi import BBox
from .catalogs import get_catalog
from .stac import search_items


@dataclass
class Scene:
    id: str
    collection: str
    datetime: str | None
    cloud_cover: float | None  # percent, None for non-optical (e.g. SAR)
    platform: str | None
    gsd: float | None  # ground sample distance, meters
    assets: list[str]
    bbox: list[float] | None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "collection": self.collection,
            "datetime": self.datetime,
            "cloud_cover": self.cloud_cover,
            "platform": self.platform,
            "gsd": self.gsd,
            "assets": self.assets,
            "bbox": self.bbox,
        }


def _normalize(item: dict) -> Scene:
    props = item.get("properties", {}) or {}
    cc = props.get("eo:cloud_cover")
    return Scene(
        id=item.get("id", "?"),
        collection=item.get("collection", "?"),
        datetime=props.get("datetime") or props.get("start_datetime"),
        cloud_cover=float(cc) if cc is not None else None,
        platform=props.get("platform") or props.get("constellation"),
        gsd=props.get("gsd"),
        assets=sorted((item.get("assets") or {}).keys()),
        bbox=item.get("bbox"),
    )


def search(
    catalog_id: str,
    collection: str,
    bbox: BBox | None = None,
    start: str | None = None,
    end: str | None = None,
    max_cloud: float | None = None,
    max_items: int = 200,
) -> list[Scene]:
    cat = get_catalog(catalog_id)
    dt = None
    if start or end:
        dt = f"{start or '..'}T00:00:00Z/{end or '..'}T23:59:59Z".replace(
            "..T00:00:00Z", ".."
        ).replace("..T23:59:59Z", "..")
    query = None
    if max_cloud is not None and cat.supports_query:
        query = {"eo:cloud_cover": {"lte": max_cloud}}
    try:
        items = search_items(
            cat.endpoint, [collection], bbox=bbox, datetime_range=dt, query=query, max_items=max_items
        )
    except Exception:
        if query is None:
            raise
        # Server may not implement the query extension — retry plain and
        # filter on the returned metadata instead.
        query = None
        items = search_items(
            cat.endpoint, [collection], bbox=bbox, datetime_range=dt, max_items=max_items
        )
    if not items and query is not None:
        # A server-side eo:cloud_cover query excludes scenes that lack the
        # property entirely (SAR, DEM, climate products). Retry unfiltered;
        # the client-side filter below keeps no-metadata scenes.
        items = search_items(
            cat.endpoint, [collection], bbox=bbox, datetime_range=dt, max_items=max_items
        )
    scenes = [_normalize(i) for i in items]
    if max_cloud is not None:
        scenes = [s for s in scenes if s.cloud_cover is None or s.cloud_cover <= max_cloud]
    return scenes
