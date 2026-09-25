import math

from basketpath import stats


def test_wilson_matches_the_textbook_interval():
    p, lo, hi = stats.wilson(10, 100)
    assert (round(lo, 4), round(hi, 4)) == (0.0552, 0.1744)
    assert math.isnan(stats.wilson(0, 0)[0])


def test_two_proportions_z_test_matches_a_hand_calculation():
    t = stats.two_proportions(60, 1000, 40, 1000)
    assert math.isclose(t["diff"], 0.02)
    assert abs(t["p_value"] - 0.0402) < 0.0005


def test_sample_size_matches_the_classic_value():
    # 10% -> 12% at alpha 0.05 and 80% power needs 3,841 per arm.
    assert stats.n_per_arm(0.10, 0.20) == 3841


def test_standardisation_removes_a_pure_simpsons_paradox():
    # Within each stratum the groups convert identically; the naive gap is entirely mix.
    strata = [(100, 10, 900, 90), (900, 450, 100, 50)]
    naive = stats.two_proportions(460, 1000, 140, 1000)
    adjusted = stats.standardised_difference(strata)
    assert math.isclose(naive["diff"], 0.32)
    assert abs(adjusted["diff"]) < 1e-12 and adjusted["coverage"] == 1.0


def test_standardisation_reports_strata_it_cannot_compare():
    adjusted = stats.standardised_difference([(100, 10, 100, 10), (50, 5, 0, 0)])
    assert math.isclose(adjusted["coverage"], 100 / 150) and adjusted["strata_used"] == 1
