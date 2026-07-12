"""satscout command-line interface.

    satscout catalogs
    satscout discover --keywords "sentinel-2 reflectance" --bbox ... --start ... --end ...
    satscout search   --catalog earth-search --collection sentinel-2-l2a --bbox ... --max-cloud 20
    satscout check    --catalog earth-search --collection sentinel-2-l2a --bbox ... --start ... --end ...
    satscout validate design --map-areas 200000,150000,3200000,6450000 --expected-users 0.7,0.6,0.9,0.95
    satscout validate assess --matrix matrix.csv --map-areas ... [--classes a,b,c,d]
"""

import argparse
import csv
import json
import sys

from . import __version__
from .aoi import load_aoi, parse_bbox
from .catalogs import CATALOGS
from .discover import discover
from .olofsson import assess, design_sample
from .report import build_report, format_report
from .search import search


def _aoi_bbox(args):
    if getattr(args, "aoi", None):
        return load_aoi(args.aoi)
    if getattr(args, "bbox", None):
        return parse_bbox(args.bbox)
    return None


def _floats(text: str) -> list[float]:
    return [float(x) for x in text.split(",") if x.strip()]


def cmd_catalogs(args) -> int:
    for cat in CATALOGS.values():
        print(f"{cat.id:20s} {cat.title}\n{'':20s} {cat.endpoint}\n{'':20s} {cat.notes}")
    return 0


def cmd_discover(args) -> int:
    hits = discover(
        keywords=args.keywords.split() if args.keywords else [],
        bbox=_aoi_bbox(args),
        start=args.start,
        end=args.end,
        catalog_ids=args.catalog or None,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps([h.to_dict() for h in hits], indent=2))
        return 0
    if not hits:
        print("No matching collections. Try fewer/looser keywords.")
        return 1
    print(f"{'score':>5}  {'catalog':<19} {'collection':<38} title")
    for h in hits:
        print(f"{h.score:5.2f}  {h.catalog:<19} {h.collection_id:<38} {h.title[:60]}")
    print(
        f"\n{len(hits)} candidates. Vet one with:\n"
        f"  satscout check --catalog {hits[0].catalog} --collection {hits[0].collection_id} "
        "--bbox <minx,miny,maxx,maxy> --start <date> --end <date>"
    )
    return 0


def cmd_search(args) -> int:
    scenes = search(
        args.catalog,
        args.collection,
        bbox=_aoi_bbox(args),
        start=args.start,
        end=args.end,
        max_cloud=args.max_cloud,
        max_items=args.max_items,
    )
    if args.json:
        print(json.dumps([s.to_dict() for s in scenes], indent=2))
        return 0
    if not scenes:
        print("No scenes matched.")
        return 1
    print(f"{'datetime':<22} {'cloud%':>6} {'platform':<14} id")
    for s in scenes:
        cc = f"{s.cloud_cover:.1f}" if s.cloud_cover is not None else "-"
        print(f"{(s.datetime or '?')[:19]:<22} {cc:>6} {(s.platform or '-'):<14} {s.id}")
    print(
        f"\n{len(scenes)} scenes from {args.catalog} (metadata only — nothing "
        "was downloaded). Use --json for per-scene STAC URLs (stac_href)."
    )
    return 0


def cmd_check(args) -> int:
    from datetime import datetime, timezone

    bbox = _aoi_bbox(args)
    scenes = search(
        args.catalog,
        args.collection,
        bbox=bbox,
        start=args.start,
        end=args.end,
        max_cloud=args.max_cloud,
        max_items=args.max_items,
    )
    provenance = {
        "catalog": args.catalog,
        "endpoint": CATALOGS[args.catalog].endpoint,
        "collection": args.collection,
        "bbox": list(bbox) if bbox else None,
        "start": args.start,
        "end": args.end,
        "max_cloud": args.max_cloud,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "satscout_version": __version__,
    }
    rep = build_report(
        args.collection, scenes, cloud_threshold=args.cloud_threshold, provenance=provenance
    )
    if args.json:
        print(json.dumps(rep.to_dict(), indent=2))
    else:
        print(format_report(rep))
    return 0 if scenes else 1


def _read_matrix_csv(path: str) -> tuple[list[list[float]], list[str] | None]:
    """CSV of counts; optional header row / label column are auto-detected."""
    with open(path) as f:
        rows = [r for r in csv.reader(f) if any(c.strip() for c in r)]

    def is_num(s: str) -> bool:
        try:
            float(s)
            return True
        except ValueError:
            return False

    names = None
    if rows and not all(is_num(c) for c in rows[0][1:] if c.strip()):
        names = [c.strip() for c in rows[0][1:]] or None
        rows = rows[1:]
    matrix = []
    for r in rows:
        cells = r[1:] if not is_num(r[0]) else r
        matrix.append([float(c) for c in cells if c.strip()])
    return matrix, names


def cmd_validate_design(args) -> int:
    out = design_sample(
        weights=_floats(args.map_areas),
        expected_users=_floats(args.expected_users),
        target_se_overall=args.target_se,
        min_per_stratum=args.min_per_stratum,
    )
    if args.json:
        print(json.dumps(out, indent=2))
        return 0
    print(f"recommended total sample size (Eq. 13): n = {out['n_total']}")
    print(f"{'stratum':>8} {'weight':>8} {'n_i':>6}")
    for i, (w, n_i) in enumerate(zip(out["weights"], out["allocation"])):
        print(f"{i + 1:>8} {w:8.4f} {n_i:>6}")
    print(f"{'total':>8} {'':8} {out['allocated_total']:>6}")
    print(f"\n{out['note']}")
    return 0


def cmd_validate_assess(args) -> int:
    matrix, header_names = _read_matrix_csv(args.matrix)
    names = args.classes.split(",") if args.classes else header_names
    result = assess(
        matrix,
        mapped_areas=_floats(args.map_areas),
        class_names=names,
        total_area=args.total_area,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0
    d = result.to_dict()
    print(
        f"overall accuracy: {d['overall_accuracy']:.4f} "
        f"± {d['overall_accuracy_ci95']:.4f} (95% CI)"
    )
    print(
        f"\n{'class':<20} {'users':>7} {'±95%':>7} {'prods':>7} {'±95%':>7} "
        f"{'adj. area':>14} {'±95%':>12}"
    )
    for row in d["per_class"]:
        pa = f"{row['producers_accuracy']:.4f}" if row["producers_accuracy"] is not None else "  n/a"
        pc = f"{row['producers_ci95']:.4f}" if row["producers_ci95"] is not None else "  n/a"
        print(
            f"{row['class']:<20} {row['users_accuracy']:7.4f} {row['users_ci95']:7.4f} "
            f"{pa:>7} {pc:>7} {row['adjusted_area']:14.1f} {row['adjusted_area_ci95']:12.1f}"
        )
    print(
        "\nAreas are error-adjusted (stratified) estimates per Olofsson et al. "
        "(2014), in the units of --map-areas."
    )
    return 0


def _add_spatiotemporal(p: argparse.ArgumentParser) -> None:
    p.add_argument("--aoi", help="GeoJSON file for the area of interest")
    p.add_argument("--bbox", help="minx,miny,maxx,maxy (lon/lat)")
    p.add_argument("--start", help="YYYY-MM-DD")
    p.add_argument("--end", help="YYYY-MM-DD")
    p.add_argument("--json", action="store_true", help="machine-readable output")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="satscout", description=__doc__.split("\n")[0])
    ap.add_argument("--version", action="version", version=f"satscout {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("catalogs", help="list built-in public catalogs").set_defaults(fn=cmd_catalogs)

    p = sub.add_parser("discover", help="rank candidate datasets across catalogs")
    p.add_argument("--keywords", default="", help='e.g. "sentinel-2 surface reflectance"')
    p.add_argument("--catalog", action="append", choices=sorted(CATALOGS), help="restrict catalogs")
    p.add_argument("--limit", type=int, default=20)
    _add_spatiotemporal(p)
    p.set_defaults(fn=cmd_discover)

    for name, fn, hlp in [
        ("search", cmd_search, "list scenes + metadata (cloud cover etc.), no downloads"),
        ("check", cmd_check, "alignment report: does this dataset fit my AOI/period?"),
    ]:
        p = sub.add_parser(name, help=hlp)
        p.add_argument("--catalog", required=True, choices=sorted(CATALOGS))
        p.add_argument("--collection", required=True)
        p.add_argument("--max-cloud", type=float, help="max eo:cloud_cover percent")
        p.add_argument("--max-items", type=int, default=200)
        if name == "check":
            p.add_argument(
                "--cloud-threshold",
                type=float,
                default=20.0,
                help="report %% of scenes at/below this cloud cover",
            )
        _add_spatiotemporal(p)
        p.set_defaults(fn=fn)

    pv = sub.add_parser("validate", help="Olofsson et al. 2014 accuracy assessment")
    vsub = pv.add_subparsers(dest="vcmd", required=True)

    p = vsub.add_parser("design", help="plan a stratified sample (size + allocation)")
    p.add_argument("--map-areas", required=True, help="comma list: mapped area per class")
    p.add_argument("--expected-users", required=True, help="comma list: conjectured user's accuracy")
    p.add_argument("--target-se", type=float, default=0.01, help="target SE of overall accuracy")
    p.add_argument("--min-per-stratum", type=int, default=50)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_validate_design)

    p = vsub.add_parser("assess", help="error matrix -> accuracies + adjusted areas w/ CIs")
    p.add_argument("--matrix", required=True, help="CSV of counts (rows=map, cols=reference)")
    p.add_argument("--map-areas", required=True, help="comma list: mapped area per class")
    p.add_argument("--classes", help="comma list of class names")
    p.add_argument("--total-area", type=float, help="defaults to sum of --map-areas")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_validate_assess)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except (ValueError, KeyError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
