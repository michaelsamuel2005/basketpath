"""Small, dependency-free statistics. Each function is checked against a known value in tests/test_stats.py."""
from __future__ import annotations

import math
from statistics import NormalDist

Z95 = NormalDist().inv_cdf(0.975)
NAN = float("nan")


def wilson(x: int, n: int, z: float = Z95) -> tuple[float, float, float]:
    """Proportion with a Wilson score interval, which behaves at small counts where the textbook one does not."""
    if n <= 0:
        return NAN, NAN, NAN
    p = x / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, centre - half), min(1.0, centre + half)


def two_proportions(x1: int, n1: int, x0: int, n0: int, z: float = Z95) -> dict:
    """p1 - p0 with an unpooled 95% interval and a pooled two-sided z-test."""
    if min(n1, n0) <= 0:
        return dict(p1=NAN, p0=NAN, diff=NAN, lo=NAN, hi=NAN, p_value=NAN, rel=NAN)
    p1, p0 = x1 / n1, x0 / n0
    diff = p1 - p0
    se = math.sqrt(p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0)
    pool = (x1 + x0) / (n1 + n0)
    se0 = math.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n0))
    p_value = math.erfc(abs(diff / se0) / math.sqrt(2)) if se0 > 0 else 1.0
    return dict(p1=p1, p0=p0, diff=diff, lo=diff - z * se, hi=diff + z * se, p_value=p_value,
                rel=diff / p0 if p0 > 0 else NAN)


def standardised_difference(strata, z: float = Z95) -> dict:
    """Difference between groups after re-weighting the comparison group to the first group's mix.

    `strata` yields (n1, x1, n0, x0) per stratum. Strata where either group is empty cannot be
    compared; they are dropped and the share of the first group they held is reported as lost coverage.
    """
    rows = [tuple(int(v) for v in r) for r in strata]
    total = sum(r[0] for r in rows)
    kept = [r for r in rows if r[0] > 0 and r[2] > 0]
    kept_n1 = sum(r[0] for r in kept)
    if kept_n1 == 0:
        return dict(diff=NAN, se=NAN, lo=NAN, hi=NAN, coverage=0.0, strata_used=0, strata_total=len(rows))
    diff = var = 0.0
    for n1, x1, n0, x0 in kept:
        w = n1 / kept_n1
        p1, p0 = x1 / n1, x0 / n0
        diff += w * (p1 - p0)
        var += w * w * (p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0)
    se = math.sqrt(var)
    return dict(diff=diff, se=se, lo=diff - z * se, hi=diff + z * se, coverage=kept_n1 / total,
                strata_used=len(kept), strata_total=len(rows))


def n_per_arm(p0: float, relative_lift: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Users per arm to detect p0 -> p0 * (1 + lift) with a two-sided two-proportion test."""
    p1 = p0 * (1 + relative_lift)
    za, zb = NormalDist().inv_cdf(1 - alpha / 2), NormalDist().inv_cdf(power)
    pbar = (p0 + p1) / 2
    num = (za * math.sqrt(2 * pbar * (1 - pbar)) + zb * math.sqrt(p0 * (1 - p0) + p1 * (1 - p1))) ** 2
    return math.ceil(num / (p1 - p0) ** 2)
