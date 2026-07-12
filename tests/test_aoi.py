import json

import pytest

from satscout.aoi import (
    bbox_from_geojson,
    bbox_overlap_fraction,
    bboxes_intersect,
    load_aoi,
    parse_bbox,
)


def test_parse_bbox():
    assert parse_bbox("-122.5, 37.5, -122.0, 38.0") == (-122.5, 37.5, -122.0, 38.0)


@pytest.mark.parametrize("bad", ["1,2,3", "5,5,1,1", "-200,0,10,10", "a,b,c,d"])
def test_parse_bbox_rejects(bad):
    with pytest.raises(ValueError):
        parse_bbox(bad)


def test_bbox_from_polygon_geometry():
    gj = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 0], [2, 3], [0, 3], [0, 0]]],
    }
    assert bbox_from_geojson(gj) == (0, 0, 2, 3)


def test_bbox_from_feature_collection():
    gj = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [10, 20]}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-5, 8]}},
        ],
    }
    assert bbox_from_geojson(gj) == (-5, 8, 10, 20)


def test_bbox_field_takes_precedence():
    gj = {"type": "Polygon", "bbox": [1, 2, 3, 4], "coordinates": [[[9, 9], [9, 9], [9, 9]]]}
    assert bbox_from_geojson(gj) == (1, 2, 3, 4)


def test_load_aoi(tmp_path):
    p = tmp_path / "aoi.geojson"
    p.write_text(json.dumps({"type": "Point", "coordinates": [7.5, 46.9]}))
    assert load_aoi(str(p)) == (7.5, 46.9, 7.5, 46.9)


def test_intersection_and_overlap():
    assert bboxes_intersect((0, 0, 2, 2), (1, 1, 3, 3))
    assert not bboxes_intersect((0, 0, 1, 1), (2, 2, 3, 3))
    assert bbox_overlap_fraction((0, 0, 2, 2), (1, 1, 3, 3)) == pytest.approx(0.25)
    assert bbox_overlap_fraction((0, 0, 2, 2), (-1, -1, 5, 5)) == pytest.approx(1.0)
