# satscout — find, vet, and validate public satellite/climate datasets

An open-source tool for remote-sensing researchers who need to match public
satellite/climate archives to their own work. Built around two pain points
that came up repeatedly in user interviews:

1. **"I find data on AWS, sometimes need to download metadata just to see
   the cloud cover."** → satscout searches the big public STAC catalogs and
   surfaces scene metadata (cloud cover, revisit gaps, bands, resolution)
   directly — **nothing is downloaded**.
2. **"If validation means validating remote sensing products as per
   Olofsson et al. 2014, that would be huge."** → satscout ships a complete,
   tested implementation of the good-practice accuracy-assessment workflow:
   stratified sample design, error-matrix analysis, and unbiased
   (error-adjusted) area estimates with confidence intervals.

## Install

```bash
git clone https://github.com/yz-al/satscout && cd satscout
pip install .                   # dev: pip install -e '.[dev]'
```

Only dependency: `requests`. Python ≥ 3.10.

## Quick start

### 1. Discover candidate datasets

Which public collections could cover a 2020–2023 study of surface
reflectance over the Central Valley?

```bash
satscout discover \
  --keywords "sentinel-2 surface reflectance" \
  --bbox -121.5,36.5,-120.5,37.5 --start 2020-01-01 --end 2023-12-31
```

Ranks matching collections across **Earth Search (AWS Open Data)**,
**Microsoft Planetary Computer**, and **USGS LandsatLook**. Collections
whose spatial/temporal extent can't cover the request are filtered out;
the rest are ranked by keyword relevance. `satscout catalogs` lists the
endpoints.

### 2. Vet a dataset without downloading anything

```bash
satscout check --catalog earth-search --collection sentinel-2-l2a \
  --bbox -121.5,36.5,-120.5,37.5 --start 2022-06-01 --end 2022-09-30 \
  --max-cloud 20
```

Produces an alignment report: scene count, date coverage, revisit-gap
statistics, the cloud-cover distribution, platforms, resolution, and the
bands/assets present in every scene — plus plain-language warnings (e.g.
"largest temporal gap is 74 days"). `satscout search` lists the individual
scenes; add `--json` to either for machine-readable output.

### 3. Validate a map per Olofsson et al. (2014)

Plan the reference sample (Eq. 13 + allocation with a rare-class floor):

```bash
satscout validate design \
  --map-areas 200000,150000,3200000,6450000 \
  --expected-users 0.70,0.60,0.90,0.95 --target-se 0.01
```

Then, with reference labels collected, feed the error matrix
(CSV, rows = map class, columns = reference class, same order as
`--map-areas`):

```bash
satscout validate assess --matrix matrix.csv \
  --map-areas 200000,150000,3200000,6450000 \
  --classes deforestation,gain,stable-forest,stable-nonforest
```

Output: overall/user's/producer's accuracies with 95% CIs and
**error-adjusted area estimates** with CIs (Eqs. 1–11 of the paper).
The implementation reproduces the paper's worked example — including the
flagship result, deforestation area = 235,086 ± 68,418 ha — in
`tests/test_olofsson.py`.

The same functionality is importable:

```python
from satscout import assess, design_sample
result = assess(matrix, mapped_areas, class_names=names)
print(result.overall_accuracy, result.adjusted_areas)
```

## Tests

```bash
pytest tests -m "not network"   # offline unit tests (fast, no internet)
pytest tests -m network         # real-data tests against the live public APIs
```

The offline suite includes a scripted fake server exercising rate-limit
(HTTP 429) recovery, Retry-After handling, exponential backoff, and both
STAC pagination styles. The network suite hits Earth Search, Planetary
Computer, and USGS live — including a 10-request burst against the
AWS-hosted API to prove throttling is absorbed, not fatal.

## Scope (MVP)

- AOIs are reduced to lon/lat bounding boxes (GeoJSON in, bbox out);
  antimeridian-crossing AOIs must be split.
- Discovery covers the three largest free STAC APIs; adding a catalog is a
  one-line entry in `satscout/catalogs.py`.
- The validation module implements stratified estimators for the standard
  "map classes = strata" design. Reference:
  Olofsson, Foody, Herold, Stehman, Woodcock & Wulder (2014). *Good
  practices for estimating area and assessing accuracy of land change.*
  Remote Sensing of Environment 148:42–57. doi:10.1016/j.rse.2014.02.015
