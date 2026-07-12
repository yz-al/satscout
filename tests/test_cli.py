"""End-to-end CLI tests (offline): argument parsing, CSV handling, output."""

import json

import pytest

from satscout.cli import main

AREAS = "200000,150000,3200000,6450000"
MATRIX_CSV = (
    ",deforestation,gain,stable-forest,stable-nonforest\n"
    "deforestation,66,0,5,4\n"
    "gain,0,55,8,12\n"
    "stable-forest,1,0,153,11\n"
    "stable-nonforest,2,1,9,313\n"
)


@pytest.fixture
def matrix_file(tmp_path):
    p = tmp_path / "matrix.csv"
    p.write_text(MATRIX_CSV)
    return str(p)


def test_catalogs_lists_endpoints(capsys):
    assert main(["catalogs"]) == 0
    out = capsys.readouterr().out
    assert "earth-search" in out
    assert "planetary-computer" in out
    assert "usgs-landsatlook" in out


def test_validate_assess_json_reproduces_paper(matrix_file, capsys):
    rc = main(["validate", "assess", "--matrix", matrix_file, "--map-areas", AREAS, "--json"])
    assert rc == 0
    d = json.loads(capsys.readouterr().out)
    assert d["overall_accuracy"] == pytest.approx(0.9465, abs=0.001)
    defo = d["per_class"][0]
    assert defo["class"] == "deforestation"  # names picked up from CSV header
    assert defo["adjusted_area"] == pytest.approx(235_086, abs=1)
    assert defo["adjusted_area_ci95"] == pytest.approx(68_418, abs=30)


def test_validate_assess_headerless_csv(tmp_path, capsys):
    p = tmp_path / "m.csv"
    p.write_text("66,0,5,4\n0,55,8,12\n1,0,153,11\n2,1,9,313\n")
    rc = main(["validate", "assess", "--matrix", str(p), "--map-areas", AREAS, "--json"])
    assert rc == 0
    d = json.loads(capsys.readouterr().out)
    assert d["per_class"][0]["class"] == "class_1"  # auto names
    assert d["per_class"][0]["adjusted_area"] == pytest.approx(235_086, abs=1)


def test_validate_assess_classes_flag_overrides_header(matrix_file, capsys):
    rc = main([
        "validate", "assess", "--matrix", matrix_file,
        "--map-areas", AREAS, "--classes", "a,b,c,d", "--json",
    ])
    assert rc == 0
    d = json.loads(capsys.readouterr().out)
    assert [r["class"] for r in d["per_class"]] == ["a", "b", "c", "d"]


def test_validate_design_paper_example(capsys):
    rc = main([
        "validate", "design",
        "--map-areas", AREAS, "--expected-users", "0.70,0.60,0.90,0.95",
        "--json",
    ])
    assert rc == 0
    d = json.loads(capsys.readouterr().out)
    assert abs(d["n_total"] - 641) <= 2
    assert len(d["allocation"]) == 4


def test_bad_matrix_is_a_clean_error(tmp_path, capsys):
    p = tmp_path / "m.csv"
    p.write_text("5,5\n1,0\n")  # stratum with n<2
    rc = main(["validate", "assess", "--matrix", str(p), "--map-areas", "50,50"])
    assert rc == 2
    assert "error:" in capsys.readouterr().err


def test_missing_matrix_file_is_a_clean_error(capsys):
    rc = main(["validate", "assess", "--matrix", "/nope.csv", "--map-areas", "1,1"])
    assert rc == 2
    assert "error:" in capsys.readouterr().err


def test_bad_bbox_is_a_clean_error(capsys):
    rc = main(["search", "--catalog", "earth-search", "--collection", "c", "--bbox", "1,2,3"])
    assert rc == 2
    assert "bbox" in capsys.readouterr().err


def test_search_offline_via_stub(monkeypatch, capsys):
    from satscout import cli
    from satscout.search import Scene

    def fake_search(catalog, collection, **kw):
        return [Scene(
            id="S2A_TEST", collection=collection, datetime="2024-07-01T10:00:00Z",
            cloud_cover=12.3, platform="sentinel-2a", gsd=10.0,
            assets=["red", "nir"], bbox=[0, 0, 1, 1],
        )]

    monkeypatch.setattr(cli, "search", fake_search)
    rc = main([
        "search", "--catalog", "earth-search", "--collection", "sentinel-2-l2a",
        "--bbox", "0,0,1,1", "--json",
    ])
    assert rc == 0
    d = json.loads(capsys.readouterr().out)
    assert d[0]["id"] == "S2A_TEST"
    assert d[0]["cloud_cover"] == 12.3


def test_check_offline_via_stub(monkeypatch, capsys):
    from satscout import cli

    monkeypatch.setattr(cli, "search", lambda *a, **k: [])
    rc = main([
        "check", "--catalog", "earth-search", "--collection", "sentinel-2-l2a",
        "--bbox", "0,0,1,1",
    ])
    assert rc == 1  # empty result → nonzero, scriptable
    out = capsys.readouterr().out
    assert "NO SCENES" in out
    # provenance trace is printed even for empty results
    assert "source:" in out and "earth-search.aws.element84.com" in out


def test_check_json_includes_provenance(monkeypatch, capsys):
    from satscout import cli

    monkeypatch.setattr(cli, "search", lambda *a, **k: [])
    main([
        "check", "--catalog", "usgs-landsatlook", "--collection", "landsat-c2l2-sr",
        "--bbox", "0,0,1,1", "--start", "2024-01-01", "--end", "2024-02-01",
        "--max-cloud", "20", "--json",
    ])
    d = json.loads(capsys.readouterr().out)
    prov = d["provenance"]
    assert prov["catalog"] == "usgs-landsatlook"
    assert prov["collection"] == "landsat-c2l2-sr"
    assert prov["bbox"] == [0, 0, 1, 1]
    assert prov["start"] == "2024-01-01" and prov["end"] == "2024-02-01"
    assert prov["max_cloud"] == 20
    assert "retrieved_at" in prov and "satscout_version" in prov


def test_validate_assess_json_cites_method(matrix_file, capsys):
    main(["validate", "assess", "--matrix", matrix_file, "--map-areas", AREAS, "--json"])
    d = json.loads(capsys.readouterr().out)
    assert "Olofsson" in d["method"]
