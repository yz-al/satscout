"""Validate against the worked example of Olofsson et al. (2014), §6.

Four classes: deforestation, forest gain, stable forest, stable non-forest.
Mapped areas (ha): 200,000 / 150,000 / 3,200,000 / 6,450,000 (10M total).
Error matrix of sample counts (rows = map, cols = reference), Table 8.

The paper's headline numbers: user's accuracies 0.88/0.73/0.93/0.96,
producer's accuracy for deforestation 0.75, overall accuracy ~0.95, and
an error-adjusted deforestation area of 235,086 ha ± 68,418 ha (95% CI).
"""

import math

import pytest

from satscout.olofsson import assess, design_sample

MATRIX = [
    [66, 0, 5, 4],
    [0, 55, 8, 12],
    [1, 0, 153, 11],
    [2, 1, 9, 313],
]
AREAS = [200_000, 150_000, 3_200_000, 6_450_000]
NAMES = ["deforestation", "forest gain", "stable forest", "stable non-forest"]


@pytest.fixture(scope="module")
def result():
    return assess(MATRIX, AREAS, class_names=NAMES)


def test_weights(result):
    assert result.weights == pytest.approx([0.020, 0.015, 0.320, 0.645])


def test_users_accuracy(result):
    assert result.users == pytest.approx([66 / 75, 55 / 75, 153 / 165, 313 / 325])
    # paper rounds to 0.88, 0.73, 0.93, 0.96
    assert [round(u, 2) for u in result.users] == [0.88, 0.73, 0.93, 0.96]


def test_producers_accuracy_deforestation(result):
    assert result.producers[0] == pytest.approx(0.75, abs=0.005)


def test_overall_accuracy(result):
    assert result.overall_accuracy == pytest.approx(0.9465, abs=0.001)


def test_adjusted_deforestation_area_and_ci(result):
    # The paper's flagship result: 235,086 ha ± 68,418 ha
    assert result.adjusted_areas[0] == pytest.approx(235_086, abs=1)
    assert 1.96 * result.adjusted_areas_se[0] == pytest.approx(68_418, abs=30)


def test_area_proportions_sum_to_one(result):
    assert sum(result.area_proportions) == pytest.approx(1.0)
    assert sum(result.adjusted_areas) == pytest.approx(sum(AREAS))


def test_proportions_rows_sum_to_weights(result):
    for i, row in enumerate(result.proportions):
        assert sum(row) == pytest.approx(result.weights[i])


def test_two_class_hand_check():
    """2x2 case worked by hand.

    matrix = [[8, 2], [1, 9]], areas = [60, 40]  =>  W = [0.6, 0.4]
    p11=0.6*8/10=0.48  p12=0.12  p21=0.04  p22=0.36
    overall = 0.48+0.36 = 0.84
    p.1 = 0.52, adjusted area class1 = 0.52*100 = 52
    S(p.1) = sqrt(0.36*0.8*0.2/9 + 0.16*0.1*0.9/9) = sqrt(0.0064+0.0016) = sqrt(0.008)
    producer1 = 0.48/0.52
    """
    r = assess([[8, 2], [1, 9]], [60, 40])
    assert r.overall_accuracy == pytest.approx(0.84)
    assert r.adjusted_areas[0] == pytest.approx(52.0)
    assert r.area_proportions_se[0] == pytest.approx(math.sqrt(0.008))
    assert r.producers[0] == pytest.approx(0.48 / 0.52)
    assert r.users == pytest.approx([0.8, 0.9])


def test_validation_errors():
    with pytest.raises(ValueError):
        assess([[5, 5]], [100])  # 1 class
    with pytest.raises(ValueError):
        assess([[5, 5], [1, 0]], [50, 50])  # stratum with n < 2
    with pytest.raises(ValueError):
        assess([[5, 5], [5, 5]], [100])  # mismatched areas
    with pytest.raises(ValueError):
        assess([[5, -1], [5, 5]], [50, 50])  # negative count


def test_design_sample_paper_example():
    """§5.1.1: W=(0.02,0.015,0.32,0.645), conjectured U=(0.7,0.6,0.9,0.95),
    S(Ô)=0.01 gives n ≈ 641."""
    out = design_sample(
        weights=[0.02, 0.015, 0.32, 0.645],
        expected_users=[0.70, 0.60, 0.90, 0.95],
        target_se_overall=0.01,
    )
    assert out["n_total"] == pytest.approx(641, abs=2)
    assert all(a >= 50 for a in out["allocation"])
    assert out["allocated_total"] >= out["n_total"] - len(out["allocation"])


def test_design_sample_validation():
    with pytest.raises(ValueError):
        design_sample([0.5, 0.5], [0.9])
    with pytest.raises(ValueError):
        design_sample([0.5, 0.5], [0.9, 1.5])
