"""Good-practice accuracy assessment & area estimation.

Implements the stratified estimators of:

  Olofsson, Foody, Herold, Stehman, Woodcock & Wulder (2014),
  "Good practices for estimating area and assessing accuracy of land
  change", Remote Sensing of Environment 148:42-57.

Given an error matrix of sample counts (rows = map class / stratum,
columns = reference class) and the mapped area of each class, this
computes:

  * cell proportions          p̂_ij = W_i · n_ij / n_i·          (Eq. 4)
  * overall accuracy          Ô = Σ_j p̂_jj                       (Eq. 1)
  * user's accuracy           Û_i = p̂_ii / p̂_i·                  (Eq. 2)
  * producer's accuracy       P̂_j = p̂_jj / p̂_·j                  (Eq. 3)
  * their standard errors                                        (Eqs. 5-7)
  * unbiased (error-adjusted) area of each class and its CI      (Eqs. 9-11)
  * the recommended sample size for planning a new assessment    (Eq. 13)

Everything is pure Python — no dependencies.
"""

import math
from dataclasses import dataclass, field

Matrix = list[list[float]]


@dataclass
class AccuracyAssessment:
    class_names: list[str]
    weights: list[float]            # W_i, mapped area proportions
    row_totals: list[float]         # n_i·
    proportions: Matrix             # p̂_ij
    overall_accuracy: float
    overall_se: float
    users: list[float]
    users_se: list[float]
    producers: list[float | None]   # None if a class never appears in reference
    producers_se: list[float | None]
    area_proportions: list[float]   # p̂_·j
    area_proportions_se: list[float]
    total_area: float | None = None
    adjusted_areas: list[float] = field(default_factory=list)
    adjusted_areas_se: list[float] = field(default_factory=list)
    z: float = 1.96

    def to_dict(self) -> dict:
        d = {
            "method": (
                "Stratified estimators per Olofsson et al. (2014), Remote "
                "Sensing of Environment 148:42-57, doi:10.1016/j.rse.2014.02.015"
            ),
            "classes": self.class_names,
            "overall_accuracy": self.overall_accuracy,
            "overall_accuracy_ci95": self.z * self.overall_se,
            "per_class": [],
        }
        for j, name in enumerate(self.class_names):
            row: dict = {
                "class": name,
                "users_accuracy": self.users[j],
                "users_ci95": self.z * self.users_se[j],
                "producers_accuracy": self.producers[j],
                "producers_ci95": (
                    self.z * self.producers_se[j] if self.producers_se[j] is not None else None
                ),
                "area_proportion": self.area_proportions[j],
                "area_proportion_ci95": self.z * self.area_proportions_se[j],
            }
            if self.adjusted_areas:
                row["adjusted_area"] = self.adjusted_areas[j]
                row["adjusted_area_ci95"] = self.z * self.adjusted_areas_se[j]
            d["per_class"].append(row)
        if self.total_area is not None:
            d["total_area"] = self.total_area
        return d


def _validate(matrix: Matrix, mapped_areas: list[float]) -> None:
    q = len(matrix)
    if q < 2:
        raise ValueError("need at least 2 classes")
    if len(mapped_areas) != q:
        raise ValueError(f"{q} matrix rows but {len(mapped_areas)} mapped areas")
    for i, row in enumerate(matrix):
        if len(row) != q:
            raise ValueError(f"matrix must be square; row {i} has {len(row)} entries")
        if any(v < 0 for v in row):
            raise ValueError(f"negative count in row {i}")
        if sum(row) < 2:
            raise ValueError(
                f"stratum {i} has fewer than 2 samples; variance estimators need n_i >= 2"
            )
    if any(a <= 0 for a in mapped_areas):
        raise ValueError("mapped areas must be positive")


def assess(
    matrix: Matrix,
    mapped_areas: list[float],
    class_names: list[str] | None = None,
    total_area: float | None = None,
    z: float = 1.96,
) -> AccuracyAssessment:
    """Stratified accuracy assessment + unbiased area estimation.

    matrix       -- sample counts, rows = map class (the sampling strata),
                    columns = reference class, in the same class order.
    mapped_areas -- area of each map class (any consistent unit: ha, km²,
                    or pixel counts — only proportions matter, except for
                    the adjusted-area output which uses these units).
    total_area   -- optional; defaults to sum(mapped_areas).
    """
    _validate(matrix, mapped_areas)
    q = len(matrix)
    names = class_names or [f"class_{i + 1}" for i in range(q)]
    if len(names) != q:
        raise ValueError(f"{q} classes but {len(names)} names")
    A_tot = total_area if total_area is not None else sum(mapped_areas)
    W = [a / sum(mapped_areas) for a in mapped_areas]
    n_row = [sum(row) for row in matrix]

    # Eq. 4: estimated cell proportions
    p = [[W[i] * matrix[i][j] / n_row[i] for j in range(q)] for i in range(q)]
    p_col = [sum(p[i][j] for i in range(q)) for j in range(q)]  # p̂_·j

    # Accuracies (Eqs. 1-3)
    overall = sum(p[j][j] for j in range(q))
    users = [matrix[i][i] / n_row[i] for i in range(q)]  # p̂_ii/p̂_i· = n_ii/n_i·
    producers = [p[j][j] / p_col[j] if p_col[j] > 0 else None for j in range(q)]

    # Eq. 5: V̂(Ô) = Σ W_i² Û_i (1-Û_i) / (n_i - 1)
    v_overall = sum(W[i] ** 2 * users[i] * (1 - users[i]) / (n_row[i] - 1) for i in range(q))
    # Eq. 6: V̂(Û_i) = Û_i (1-Û_i) / (n_i - 1)
    users_se = [math.sqrt(users[i] * (1 - users[i]) / (n_row[i] - 1)) for i in range(q)]

    # Eq. 7: V̂(P̂_j). Written with mapped areas N_i; scale-invariant, so
    # the mapped areas can be used directly in place of pixel counts.
    producers_se: list[float | None] = []
    N = mapped_areas
    for j in range(q):
        if producers[j] is None:
            producers_se.append(None)
            continue
        N_hat_j = sum(N[i] / n_row[i] * matrix[i][j] for i in range(q))
        Pj, Uj = producers[j], users[j]
        term1 = N[j] ** 2 * (1 - Pj) ** 2 * Uj * (1 - Uj) / (n_row[j] - 1)
        term2 = Pj ** 2 * sum(
            N[i] ** 2
            * (matrix[i][j] / n_row[i])
            * (1 - matrix[i][j] / n_row[i])
            / (n_row[i] - 1)
            for i in range(q)
            if i != j
        )
        producers_se.append(math.sqrt((term1 + term2) / N_hat_j ** 2))

    # Eq. 10: S(p̂_·k) — standard error of the stratified area proportion
    p_col_se = [
        math.sqrt(
            sum(
                W[i] ** 2
                * (matrix[i][k] / n_row[i])
                * (1 - matrix[i][k] / n_row[i])
                / (n_row[i] - 1)
                for i in range(q)
            )
        )
        for k in range(q)
    ]

    # Eqs. 9, 11: error-adjusted area Â_j = A_tot · p̂_·j and its SE
    adj_areas = [A_tot * pc for pc in p_col]
    adj_areas_se = [A_tot * se for se in p_col_se]

    return AccuracyAssessment(
        class_names=names,
        weights=W,
        row_totals=n_row,
        proportions=p,
        overall_accuracy=overall,
        overall_se=math.sqrt(v_overall),
        users=users,
        users_se=users_se,
        producers=producers,
        producers_se=producers_se,
        area_proportions=p_col,
        area_proportions_se=p_col_se,
        total_area=A_tot,
        adjusted_areas=adj_areas,
        adjusted_areas_se=adj_areas_se,
        z=z,
    )


def design_sample(
    weights: list[float],
    expected_users: list[float],
    target_se_overall: float = 0.01,
    min_per_stratum: int = 50,
) -> dict:
    """Plan a stratified random sample per Olofsson et al. (2014) §5.1.1.

    weights          -- mapped area proportions W_i (will be normalized).
    expected_users   -- conjectured user's accuracy per stratum, in (0, 1].
    target_se_overall-- desired standard error of overall accuracy
                        (0.01 is the paper's example).
    min_per_stratum  -- floor per stratum; the paper suggests 50-100 for
                        rare (change) classes.

    Returns total n from Eq. 13 and a proportional allocation with the
    floor applied. Practitioners should compare this against equal
    allocation for producer's-accuracy goals (see paper §5.1.2).
    """
    if len(weights) != len(expected_users):
        raise ValueError("weights and expected_users must have equal length")
    if any(w <= 0 for w in weights):
        raise ValueError("weights must be positive")
    if any(not (0 < u <= 1) for u in expected_users):
        raise ValueError("expected user's accuracies must be in (0, 1]")
    total_w = sum(weights)
    W = [w / total_w for w in weights]
    S = [math.sqrt(u * (1 - u)) for u in expected_users]
    # Eq. 13 (simplified for large N): n = (Σ W_i S_i / S(Ô))²
    n = math.ceil((sum(Wi * Si for Wi, Si in zip(W, S)) / target_se_overall) ** 2)

    q = len(W)
    flexible = max(n - q * min_per_stratum, 0)
    alloc = [min_per_stratum + round(flexible * Wi) for Wi in W]
    return {
        "n_total": n,
        "allocation": alloc,
        "allocated_total": sum(alloc),
        "weights": W,
        "note": (
            "Proportional allocation with a per-stratum floor of "
            f"{min_per_stratum}. Compare with equal allocation if precise "
            "producer's accuracies for rare classes are the priority "
            "(Olofsson et al. 2014, §5.1.2)."
        ),
    }
