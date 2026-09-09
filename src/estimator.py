"""
L4 — Stratified estimator.

From the RoR sample (collected for the 396-village holdout) estimate how many of ALL issued
cards are encumbered, by extrapolating a per-stratum rate. Stratum = district x settlement-size
tercile (same buckets as train_test_split). Uses Wilson score intervals; falls back district ->
global when a stratum has no sample. Cross-checks the sample-based estimate against the official
Lok Sabha loan total.

Input:  data/mp_vetting.parquet  (village grain, with plots_checked / plots_with_loan filled)
Output: data/estimates.parquet   (district_en, est_encumbered, ci_low, ci_high)

Usage:  python src/estimator.py
"""
from __future__ import annotations

import os
import math
import argparse
import numpy as np
import pandas as pd

try:
    from aggregate_numerator import mp_state_total
except ImportError:
    from src.aggregate_numerator import mp_state_total


def wilson(pos: float, n: float, z: float = 1.96):
    if not n:
        return math.nan, math.nan, math.nan
    p = pos / n
    d = 1 + z**2 / n
    c = p + z**2 / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return p, max(0.0, (c - m) / d), min(1.0, (c + m) / d)


def _rate_table(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    g = df.groupby(by, dropna=False).agg(pos=("plots_with_loan", "sum"),
                                         n=("plots_checked", "sum")).reset_index()
    rates = g.apply(lambda r: wilson(r["pos"], r["n"]), axis=1, result_type="expand")
    g[["rate", "lo", "hi"]] = rates
    return g


def estimate(data_dir: str) -> pd.DataFrame:
    df = pd.read_parquet(os.path.join(data_dir, "mp_vetting.parquet"))
    for c in ("plots_checked", "plots_with_loan"):
        df[c] = pd.to_numeric(df.get(c), errors="coerce").fillna(0)
    df["cards"] = pd.to_numeric(df["cards_distributed"], errors="coerce").fillna(0)

    # same size buckets as the split
    df["size_bucket"] = pd.qcut(df["cards_distributed"], 3,
                                labels=["small", "medium", "large"], duplicates="drop")

    sampled = df[df["plots_checked"] > 0]
    if sampled.empty:
        raise SystemExit("no sample yet — run ror_sampler.py to fill plots_checked/plots_with_loan")

    # rate lookups at three granularities
    g_all = wilson(sampled["plots_with_loan"].sum(), sampled["plots_checked"].sum())
    by_dist = _rate_table(sampled, ["district_en"]).set_index("district_en")
    by_str = _rate_table(sampled, ["district_en", "size_bucket"]).set_index(
        ["district_en", "size_bucket"])

    def pick(dist, bucket):
        if (dist, bucket) in by_str.index and by_str.loc[(dist, bucket), "n"] > 0:
            r = by_str.loc[(dist, bucket)]
        elif dist in by_dist.index and by_dist.loc[dist, "n"] > 0:
            r = by_dist.loc[dist]
        else:
            return g_all
        return r["rate"], r["lo"], r["hi"]

    # apply rate to every stratum's total cards
    strata = df.groupby(["district_en", "size_bucket"], observed=True)["cards"].sum().reset_index()
    strata[["rate", "lo", "hi"]] = strata.apply(
        lambda r: pick(r["district_en"], r["size_bucket"]), axis=1, result_type="expand")
    for col in ("rate", "lo", "hi"):
        strata[f"enc_{col}"] = strata[col] * strata["cards"]

    dist = strata.groupby("district_en", as_index=False).agg(
        est_encumbered=("enc_rate", "sum"),
        ci_low=("enc_lo", "sum"),
        ci_high=("enc_hi", "sum"))
    for c in ("est_encumbered", "ci_low", "ci_high"):
        dist[c] = dist[c].round().astype(int)
    dist.to_parquet(os.path.join(data_dir, "estimates.parquet"), index=False)

    # ---- report + cross-check ----
    tot = int(dist["est_encumbered"].sum())
    lo, hi = int(dist["ci_low"].sum()), int(dist["ci_high"].sum())
    mp = mp_state_total(data_dir)          # None if MP loan figure is unvetted
    print(f"sampled villages: {sampled['lgd_village_code'].nunique()}  "
          f"plots checked: {int(sampled['plots_checked'].sum()):,}  "
          f"with loan: {int(sampled['plots_with_loan'].sum()):,}")
    print(f"state encumbrance rate (sample): {g_all[0]*100:.3f}%  "
          f"[{g_all[1]*100:.3f}–{g_all[2]*100:.3f}]")
    print(f"estimated encumbered cards (extrapolated): {tot:,}  CI [{lo:,} – {hi:,}]")
    if mp:
        off = mp["loans_count"]
        print(f"official card-backed loans (vetted): {off:,}")
        print(f"cross-check estimate/official: {tot/off:.1f}x  "
              f"(RoR=any charge upper bound; official=card-backed precise)")
    else:
        print("cross-check: skipped — no vetted official MP loan figure to compare against.")
    print(f"-> {os.path.join(data_dir,'estimates.parquet')}")
    return dist


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    estimate(ap.parse_args().data_dir)
