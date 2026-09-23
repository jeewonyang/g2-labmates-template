"""Comparisons between conditions, for flow metrics with a handful of wells each.

The test is **Welch's unpaired t-test** — the unequal-variance form — with
**Holm-Sidak** correction across the comparisons made for one metric. That is
the same analysis GraphPad Prism calls "multiple unpaired t-tests", so the
numbers here can be reproduced in Prism from the tables in `prism/`. It is also
the test this lab's own writing reports: the worked example in *Anatomy of a
Manuscript* quotes "d.f. = 12.73", and a fractional d.f. is Welch.

Equal-variance (Student) t-tests are deliberately not offered. Replicate
spread in this lab's runs ranges from ~1% to ~12% CV between conditions in the
same plate, so the equal-variance assumption is not one to make silently.

Everything here is pure: no plotting, no file I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import stats

METHOD = "Welch's unpaired t-test, Holm-Sidak corrected across the comparisons for each metric"


@dataclass
class Comparison:
    metric: str
    a: str                  # condition name
    b: str
    n_a: int = 0
    n_b: int = 0
    mean_a: float = float("nan")
    mean_b: float = float("nan")
    sd_a: float = float("nan")
    sd_b: float = float("nan")
    difference: float = float("nan")   # mean_a - mean_b
    ci_low: float = float("nan")
    ci_high: float = float("nan")
    t: float = float("nan")
    df: float = float("nan")
    p: float = float("nan")
    p_adjusted: float = float("nan")
    skipped: str | None = None         # why, when the test could not be run

    @property
    def ok(self) -> bool:
        return self.skipped is None and np.isfinite(self.p)

    def stars(self, use_adjusted: bool = True) -> str:
        p = self.p_adjusted if use_adjusted else self.p
        if not np.isfinite(p):
            return ""
        if p < 1e-4:
            return "****"
        if p < 1e-3:
            return "***"
        if p < 1e-2:
            return "**"
        if p < 0.05:
            return "*"
        return "n.s."

    def label(self, use_adjusted: bool = True) -> str:
        """What goes on a figure: stars over the p-value at 2 significant figures.

        Two figures, not four: with n = 3 per group the third digit is noise,
        and the shorter label is what lets exact values fit over 9 mm bars.
        Full precision stays in comparisons.csv and RESULTS.md.
        """
        if not self.ok:
            return ""
        p = self.p_adjusted if use_adjusted else self.p
        return f"{self.stars(use_adjusted)}\n{format_p_short(p)}"


def format_p(p: float) -> str:
    """`p = 0.0032`, `p < 0.0001` — never a rounded-to-zero `p = 0.000`."""
    if not np.isfinite(p):
        return "p = n/a"
    if p < 1e-4:
        return "p < 0.0001"
    if p < 0.001:
        return f"p = {p:.5f}"
    return f"p = {p:.4f}"


def format_p_short(p: float) -> str:
    """Figure form: `0.0064`, `0.76`, `<0.0001` — 2 significant figures, no `p =`."""
    if not np.isfinite(p):
        return "n/a"
    if p < 1e-4:
        return "<0.0001"
    return f"{p:.2g}" if p < 0.1 else f"{p:.2f}"


def welch(a, b, alpha: float = 0.05) -> dict:
    """Welch's t-test on two samples, with the difference and its CI.

    The degrees of freedom are computed explicitly (Welch-Satterthwaite)
    rather than read off a scipy result: the CI needs them, and the `df`
    attribute of `ttest_ind` only exists in scipy >= 1.11 while this lab's
    interpreter has 1.7.
    """
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    a = a[np.isfinite(a)]
    b = b[np.isfinite(b)]

    out = {
        "n_a": int(a.size), "n_b": int(b.size),
        "mean_a": float(a.mean()) if a.size else float("nan"),
        "mean_b": float(b.mean()) if b.size else float("nan"),
        "sd_a": float(a.std(ddof=1)) if a.size > 1 else float("nan"),
        "sd_b": float(b.std(ddof=1)) if b.size > 1 else float("nan"),
        "difference": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"),
        "t": float("nan"), "df": float("nan"), "p": float("nan"),
        "skipped": None,
    }

    if a.size < 2 or b.size < 2:
        out["skipped"] = f"need >= 2 values per group, got {a.size} and {b.size}"
        return out

    va, vb = a.var(ddof=1), b.var(ddof=1)
    se2 = va / a.size + vb / b.size
    out["difference"] = float(a.mean() - b.mean())

    if se2 <= 0:
        # Both groups have zero variance. The difference is exact, but a
        # t-test on it is undefined rather than infinitely significant.
        out["skipped"] = ("zero variance in both groups; the difference is "
                          f"{out['difference']:.4g} but no test is defined")
        return out

    se = math.sqrt(se2)
    df = se2 ** 2 / ((va / a.size) ** 2 / (a.size - 1)
                     + (vb / b.size) ** 2 / (b.size - 1))
    t = out["difference"] / se
    p = float(2.0 * stats.t.sf(abs(t), df))
    crit = float(stats.t.ppf(1 - alpha / 2, df))

    out.update(t=float(t), df=float(df), p=p,
               ci_low=out["difference"] - crit * se,
               ci_high=out["difference"] + crit * se)
    return out


def holm_sidak(pvalues) -> np.ndarray:
    """Holm-Sidak step-down adjusted p-values.

    Controls the family-wise error rate while being slightly less conservative
    than Holm-Bonferroni. NaNs pass through untouched and are excluded from the
    family size, so a skipped comparison does not make the others stricter.
    """
    p = np.asarray(pvalues, float)
    adj = np.full(p.shape, np.nan)
    finite = np.where(np.isfinite(p))[0]
    m = finite.size
    if m == 0:
        return adj
    if m == 1:
        adj[finite] = np.clip(p[finite], 0, 1)
        return adj

    order = finite[np.argsort(p[finite], kind="stable")]
    ranked = p[order]
    stepped = 1.0 - np.power(1.0 - ranked, m - np.arange(m))
    # Step-down monotonicity: an adjusted p can never fall below the one
    # before it.
    stepped = np.maximum.accumulate(stepped)
    adj[order] = np.clip(stepped, 0, 1)
    return adj


@dataclass
class ComparisonSet:
    """All comparisons for one run, corrected per metric."""
    comparisons: list[Comparison] = field(default_factory=list)
    method: str = METHOD

    def for_metric(self, metric: str) -> list[Comparison]:
        return [c for c in self.comparisons if c.metric == metric]

    def rows(self) -> list[dict]:
        return [{
            "metric": c.metric, "condition_A": c.a, "condition_B": c.b,
            "n_A": c.n_a, "n_B": c.n_b,
            "mean_A": c.mean_a, "sd_A": c.sd_a,
            "mean_B": c.mean_b, "sd_B": c.sd_b,
            "difference_A_minus_B": c.difference,
            "ci95_low": c.ci_low, "ci95_high": c.ci_high,
            "t": c.t, "df": c.df,
            "p": c.p, "p_holm_sidak": c.p_adjusted,
            "significant_0.05": ("" if not c.ok else
                                 ("yes" if c.p_adjusted < 0.05 else "no")),
            "skipped_reason": c.skipped or "",
        } for c in self.comparisons]


def run(values_by_condition: dict[str, dict[str, list[float]]],
        pairs: list[tuple[str, str]],
        metrics: list[str],
        alpha: float = 0.05) -> ComparisonSet:
    """Test every `pair` on every `metric`.

    `values_by_condition[condition][metric]` is the list of per-well values.
    Correction is applied **within each metric**, across that metric's
    comparisons — not across metrics, which are different questions.
    """
    cs = ComparisonSet()
    for metric in metrics:
        block: list[Comparison] = []
        for a, b in pairs:
            va = values_by_condition.get(a, {}).get(metric, [])
            vb = values_by_condition.get(b, {}).get(metric, [])
            res = welch(va, vb, alpha=alpha)
            block.append(Comparison(metric=metric, a=a, b=b, **res))
        for c, padj in zip(block, holm_sidak([c.p for c in block])):
            c.p_adjusted = float(padj)
        cs.comparisons.extend(block)
    return cs


if __name__ == "__main__":
    import sys
    # _console_safe: a cp949/cp1252 console cannot print "—"; replace, never crash.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    # Cross-check the hand-rolled Welch against scipy, and Holm-Sidak against
    # its definition. Run this after touching anything above.
    rng = np.random.default_rng(0)
    worst_p = worst_df = 0.0
    for _ in range(2000):
        a = rng.normal(0, rng.uniform(0.2, 3), rng.integers(2, 8))
        b = rng.normal(rng.uniform(-2, 2), rng.uniform(0.2, 3), rng.integers(2, 8))
        mine = welch(a, b)
        ref = stats.ttest_ind(a, b, equal_var=False)
        worst_p = max(worst_p, abs(mine["p"] - float(ref.pvalue)))
        worst_df = max(worst_df, abs(mine["t"] - float(ref.statistic)))
    print(f"Welch vs scipy: max |dp| = {worst_p:.2e}, max |dt| = {worst_df:.2e}")
    assert worst_p < 1e-10 and worst_df < 1e-10, "Welch implementation disagrees with scipy"

    ps = [0.001, 0.02, 0.04, 0.6]
    adj = holm_sidak(ps)
    expect = [1 - (1 - p) ** (4 - i) for i, p in enumerate(ps)]
    expect = np.maximum.accumulate(expect)
    print("Holm-Sidak:", np.round(adj, 6), "expected", np.round(expect, 6))
    assert np.allclose(adj, expect), "Holm-Sidak disagrees with its definition"

    print("zero variance:", welch([1, 1, 1], [2, 2, 2])["skipped"])
    print("too few:", welch([1], [2, 3, 4])["skipped"])
    print("format_p:", format_p(1e-9), "|", format_p(0.00032), "|", format_p(0.0321))
    print("all checks passed")
