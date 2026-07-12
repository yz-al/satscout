"""Alignment report: does this dataset actually fit my study?

Summarizes what a researcher checks by hand today — scene count over the
AOI/period, cloud-cover distribution, temporal gaps, resolution, bands —
into one report built purely from search metadata.
"""

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .search import Scene


@dataclass
class AlignmentReport:
    collection: str
    n_scenes: int
    first: str | None = None
    last: str | None = None
    max_gap_days: float | None = None
    median_gap_days: float | None = None
    cloud: dict | None = None  # min/median/mean/max + pct_under_20
    platforms: list[str] = field(default_factory=list)
    gsd_meters: list[float] = field(default_factory=list)
    common_assets: list[str] = field(default_factory=list)
    verdicts: list[str] = field(default_factory=list)
    # provenance: catalog/endpoint/query + retrieval time, so the report is
    # reproducible and citable (e.g. in a methods section)
    provenance: dict | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def build_report(
    collection: str,
    scenes: list[Scene],
    cloud_threshold: float = 20.0,
    provenance: dict | None = None,
) -> AlignmentReport:
    rep = AlignmentReport(collection=collection, n_scenes=len(scenes), provenance=provenance)
    if not scenes:
        rep.verdicts.append(
            "NO SCENES matched: the dataset likely does not cover this AOI/period "
            "(or the cloud filter is too strict)."
        )
        return rep

    times = sorted(_parse_dt(s.datetime) for s in scenes if s.datetime)
    if times:
        rep.first = times[0].date().isoformat()
        rep.last = times[-1].date().isoformat()
        if len(times) > 1:
            gaps = [
                (b - a).total_seconds() / 86400.0 for a, b in zip(times, times[1:])
            ]
            rep.max_gap_days = round(max(gaps), 1)
            rep.median_gap_days = round(statistics.median(gaps), 1)

    covers = [s.cloud_cover for s in scenes if s.cloud_cover is not None]
    if covers:
        rep.cloud = {
            "min": round(min(covers), 1),
            "median": round(statistics.median(covers), 1),
            "mean": round(statistics.fmean(covers), 1),
            "max": round(max(covers), 1),
            f"pct_under_{int(cloud_threshold)}": round(
                100.0 * sum(1 for c in covers if c <= cloud_threshold) / len(covers), 1
            ),
        }

    rep.platforms = sorted({s.platform for s in scenes if s.platform})
    rep.gsd_meters = sorted({s.gsd for s in scenes if s.gsd is not None})
    asset_sets = [set(s.assets) for s in scenes if s.assets]
    if asset_sets:
        rep.common_assets = sorted(set.intersection(*asset_sets))

    # Human-readable verdicts
    rep.verdicts.append(f"{len(scenes)} scenes over the AOI/period.")
    if rep.max_gap_days is not None and rep.max_gap_days > 60:
        rep.verdicts.append(
            f"WARNING: largest temporal gap is {rep.max_gap_days} days — check "
            "whether your analysis tolerates that revisit gap."
        )
    if rep.cloud:
        pct_key = f"pct_under_{int(cloud_threshold)}"
        rep.verdicts.append(
            f"Cloud cover: median {rep.cloud['median']}%, "
            f"{rep.cloud[pct_key]}% of scenes at or under {cloud_threshold}%."
        )
        if rep.cloud[pct_key] < 25:
            rep.verdicts.append(
                "WARNING: few low-cloud scenes — consider SAR (cloud-independent) "
                "or a longer compositing window."
            )
    elif covers == []:
        rep.verdicts.append(
            "No eo:cloud_cover metadata (normal for SAR/DEM/climate products)."
        )
    return rep


def format_report(rep: AlignmentReport) -> str:
    lines = [f"Alignment report — {rep.collection}", "=" * 40]
    lines.append(f"scenes:        {rep.n_scenes}")
    if rep.first:
        lines.append(f"date range:    {rep.first} → {rep.last}")
    if rep.median_gap_days is not None:
        lines.append(f"revisit gaps:  median {rep.median_gap_days} d, max {rep.max_gap_days} d")
    if rep.cloud:
        c = rep.cloud
        pct = next(v for k, v in c.items() if k.startswith("pct_under"))
        thr = next(k for k in c if k.startswith("pct_under")).split("_")[-1]
        lines.append(
            f"cloud cover:   min {c['min']} / median {c['median']} / max {c['max']} %"
            f"  ({pct}% of scenes ≤ {thr}%)"
        )
    if rep.platforms:
        lines.append(f"platforms:     {', '.join(rep.platforms)}")
    if rep.gsd_meters:
        lines.append(f"gsd (m):       {', '.join(str(g) for g in rep.gsd_meters)}")
    if rep.common_assets:
        lines.append(f"assets/bands:  {', '.join(rep.common_assets)}")
    lines.append("")
    for v in rep.verdicts:
        lines.append(f"  • {v}")
    if rep.provenance:
        lines.append("")
        lines.append("source:")
        for k, v in rep.provenance.items():
            if v is not None:
                lines.append(f"  {k}: {v}")
    return "\n".join(lines)
