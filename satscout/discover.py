"""Collection-level discovery: which public datasets could match my work?

Given keywords + an AOI + a time range, fetch collections from the
public catalogs and rank the ones whose spatial/temporal extent covers
the request, scored by keyword relevance. This answers "what candidate
datasets exist?" without the researcher hand-browsing each portal.
"""

from dataclasses import dataclass

from .aoi import BBox, bboxes_intersect
from .catalogs import CATALOGS, Catalog
from .stac import list_collections


@dataclass
class CollectionHit:
    catalog: str
    collection_id: str
    title: str
    score: float
    temporal_extent: tuple[str | None, str | None]
    keywords: list[str]
    description: str
    endpoint: str = ""  # STAC API root this hit came from (provenance)

    def to_dict(self) -> dict:
        return {
            "catalog": self.catalog,
            "collection": self.collection_id,
            "title": self.title,
            "score": round(self.score, 3),
            "temporal_extent": list(self.temporal_extent),
            "keywords": self.keywords,
            "description": self.description,
            "endpoint": self.endpoint,
        }


def _collection_bboxes(coll: dict) -> list[BBox]:
    boxes = (coll.get("extent", {}).get("spatial", {}) or {}).get("bbox", []) or []
    out = []
    for b in boxes:
        if len(b) >= 4:
            # 3D bboxes are [minx, miny, minz, maxx, maxy, maxz]
            if len(b) == 6:
                out.append((b[0], b[1], b[3], b[4]))
            else:
                out.append((b[0], b[1], b[2], b[3]))
    return out


def _collection_interval(coll: dict) -> tuple[str | None, str | None]:
    intervals = (coll.get("extent", {}).get("temporal", {}) or {}).get("interval", []) or []
    if intervals and len(intervals[0]) >= 2:
        return (intervals[0][0], intervals[0][1])
    return (None, None)


def _temporal_overlaps(interval: tuple[str | None, str | None], start: str | None, end: str | None) -> bool:
    """ISO-8601 strings compare correctly lexicographically (same zero-padded format)."""
    c_start, c_end = interval
    if start and c_end and c_end[:10] < start[:10]:
        return False
    if end and c_start and c_start[:10] > end[:10]:
        return False
    return True


def score_collection(
    coll: dict,
    keywords: list[str],
    bbox: BBox | None = None,
    start: str | None = None,
    end: str | None = None,
) -> float | None:
    """Relevance in [0, 1], or None if the collection can't cover the request.

    Spatial/temporal extents are hard filters; keywords rank the survivors.
    With no keywords every surviving collection scores 1.0.
    """
    if bbox is not None:
        boxes = _collection_bboxes(coll)
        if boxes and not any(bboxes_intersect(bbox, b) for b in boxes):
            return None
    if (start or end) and not _temporal_overlaps(_collection_interval(coll), start, end):
        return None
    if not keywords:
        return 1.0
    haystack = " ".join(
        [
            coll.get("id", ""),
            coll.get("title", "") or "",
            coll.get("description", "") or "",
            " ".join(coll.get("keywords", []) or []),
        ]
    ).lower()
    hits = sum(1 for kw in keywords if kw.lower() in haystack)
    return hits / len(keywords) if hits else None


def discover(
    keywords: list[str],
    bbox: BBox | None = None,
    start: str | None = None,
    end: str | None = None,
    catalog_ids: list[str] | None = None,
    limit: int = 20,
) -> list[CollectionHit]:
    catalogs: list[Catalog] = [CATALOGS[c] for c in (catalog_ids or sorted(CATALOGS))]
    hits: list[CollectionHit] = []
    errors: list[str] = []
    for cat in catalogs:
        try:
            colls = list_collections(cat.endpoint)
        except Exception as e:  # a down catalog shouldn't kill the whole search
            errors.append(f"{cat.id}: {e}")
            continue
        for coll in colls:
            score = score_collection(coll, keywords, bbox, start, end)
            if score is None:
                continue
            hits.append(
                CollectionHit(
                    catalog=cat.id,
                    collection_id=coll.get("id", "?"),
                    title=coll.get("title") or coll.get("id", "?"),
                    score=score,
                    temporal_extent=_collection_interval(coll),
                    keywords=coll.get("keywords", []) or [],
                    description=(coll.get("description") or "").strip().split("\n")[0][:200],
                    endpoint=cat.endpoint,
                )
            )
    hits.sort(key=lambda h: (-h.score, h.catalog, h.collection_id))
    if errors:
        import sys

        print(f"warning: some catalogs failed: {'; '.join(errors)}", file=sys.stderr)
    return hits[:limit]
