"""Area-of-interest handling. MVP works on lon/lat bounding boxes.

An AOI can come in as a "minx,miny,maxx,maxy" string or a GeoJSON file
(Feature, FeatureCollection, or bare geometry); either way it is reduced
to a WGS84 bbox for STAC queries. Antimeridian-crossing AOIs are not
handled — split them into two boxes.
"""

import json

BBox = tuple[float, float, float, float]


def parse_bbox(text: str) -> BBox:
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 4:
        raise ValueError(f"bbox must be 'minx,miny,maxx,maxy', got {text!r}")
    minx, miny, maxx, maxy = (float(p) for p in parts)
    if not (minx < maxx and miny < maxy):
        raise ValueError(f"degenerate bbox {text!r} (min must be < max)")
    if not (-180 <= minx <= 180 and -180 <= maxx <= 180 and -90 <= miny <= 90 and -90 <= maxy <= 90):
        raise ValueError(f"bbox {text!r} out of lon/lat range")
    return (minx, miny, maxx, maxy)


def _walk_coords(obj, points: list):
    """Collect all [lon, lat] pairs from arbitrarily nested coordinate arrays."""
    if (
        isinstance(obj, (list, tuple))
        and len(obj) >= 2
        and all(isinstance(v, (int, float)) for v in obj[:2])
    ):
        points.append((float(obj[0]), float(obj[1])))
        return
    if isinstance(obj, (list, tuple)):
        for item in obj:
            _walk_coords(item, points)


def bbox_from_geojson(gj: dict) -> BBox:
    if "bbox" in gj and len(gj["bbox"]) >= 4:
        b = gj["bbox"]
        return (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
    points: list[tuple[float, float]] = []
    if gj.get("type") == "FeatureCollection":
        for feat in gj.get("features", []):
            geom = feat.get("geometry") or {}
            _walk_coords(geom.get("coordinates", []), points)
    elif gj.get("type") == "Feature":
        geom = gj.get("geometry") or {}
        _walk_coords(geom.get("coordinates", []), points)
    else:  # bare geometry
        _walk_coords(gj.get("coordinates", []), points)
    if not points:
        raise ValueError("GeoJSON contains no coordinates")
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def load_aoi(path: str) -> BBox:
    with open(path) as f:
        return bbox_from_geojson(json.load(f))


def bboxes_intersect(a: BBox, b: BBox) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def bbox_overlap_fraction(aoi: BBox, other: BBox) -> float:
    """Fraction of the AOI box covered by `other` (0..1, planar approximation)."""
    ix = max(0.0, min(aoi[2], other[2]) - max(aoi[0], other[0]))
    iy = max(0.0, min(aoi[3], other[3]) - max(aoi[1], other[1]))
    aoi_area = (aoi[2] - aoi[0]) * (aoi[3] - aoi[1])
    if aoi_area <= 0:
        return 0.0
    return (ix * iy) / aoi_area
