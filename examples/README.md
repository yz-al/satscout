# Examples

`olofsson2014_matrix.csv` — the error matrix from the worked example of
Olofsson et al. (2014), Table 8. Reproduce the paper's results with:

```bash
satscout validate assess --matrix olofsson2014_matrix.csv \
  --map-areas 200000,150000,3200000,6450000
```

Expected: overall accuracy 0.947 ± 0.018 and a deforestation area of
235,086 ± 68,418 ha.
