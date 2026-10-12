"""Small, dependency-free significance helpers (numpy only).

A permutation test makes no distributional assumptions, which matters for P&L: it is fat-tailed
and heteroskedastic. Reused by the demo no-edge tests and, later, by the dashboard's Insights so
it never reports a "pattern" that a shuffle of the labels would produce as often.
"""

import numpy as np
import pandas as pd


def _between_group_stat(values: np.ndarray, codes: np.ndarray, k: int) -> float:
    counts = np.bincount(codes, minlength=k)
    sums = np.bincount(codes, weights=values, minlength=k)
    nonempty = counts > 0
    means = sums[nonempty] / counts[nonempty]
    return float(np.sum(counts[nonempty] * (means - values.mean()) ** 2))


def permutation_pvalue(values, labels, n_perm: int = 2000, seed: int = 0) -> float:
    """P(between-group variation >= observed) if labels were unrelated to values.

    Works for means of continuous values and, with 0/1 values, for win rates across groups.
    """
    values = np.asarray(values, dtype=float)
    codes, uniques = pd.factorize(pd.Series(labels))
    k = len(uniques)
    if k < 2 or len(values) < 2:
        return 1.0
    observed = _between_group_stat(values, codes, k)
    rng = np.random.default_rng(seed)
    hits = sum(
        _between_group_stat(values, rng.permutation(codes), k) >= observed for _ in range(n_perm)
    )
    return (hits + 1) / (n_perm + 1)


def signflip_pvalue(values, n_perm: int = 5000, seed: int = 0) -> float:
    """Two-sided p-value for 'the mean is zero': flip each value's sign at random.

    Distribution-free (P&L is fat-tailed and skewed), needs no assumption except that a
    zero-expectancy trader's results are symmetric around zero.
    """
    v = np.asarray(values, dtype=float)
    if len(v) < 2 or not np.any(v):
        return 1.0
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n_perm, len(v)))
    means = np.abs((signs * v).mean(axis=1))
    return float((np.sum(means >= abs(v.mean()) - 1e-12) + 1) / (n_perm + 1))
