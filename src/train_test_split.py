"""
Stratified train/test split of the SVAMITVA village dataset.

Why: we cannot census the loan column (per-parcel RoR is captcha/replay-gated). Instead
we hold out a statistically valid, hand-checkable TEST sample to vet against. Ground-truth
(RoR encumbrance) is collected only for the test villages; the train set is everything else,
used to model/extrapolate the collateralisation rate.

Stratification: by district x settlement-size tercile (card count), so the holdout spans
small/medium/large villages in every district. Reproducible (seed).

Inputs:  data/mp_svamitva.parquet   (from build_dataset.py)
Outputs: data/train.parquet, data/test.parquet   (all villages, tagged with `split`)
         data/vet_worklist.csv     (the test set + blank columns to fill during RoR checks)

Usage:
  python src/train_test_split.py                 # ~384-village test holdout (95% CI, ±5%)
  python src/train_test_split.py --n-test 800
  python src/train_test_split.py --test-frac 0.2
"""
from __future__ import annotations

import os
import argparse
import numpy as np
import pandas as pd

SEED = 42


def make_split(data_dir: str, n_test: int | None, test_frac: float | None):
    df = pd.read_parquet(os.path.join(data_dir, "mp_svamitva.parquet"))
    df = df[df["cards_distributed"].fillna(0) > 0].reset_index(drop=True)
    n = len(df)

    # settlement-size tercile (global), used with district for stratification
    df["size_bucket"] = pd.qcut(df["cards_distributed"], 3,
                                labels=["small", "medium", "large"], duplicates="drop")
    df["stratum"] = df["district_en"].astype(str) + " | " + df["size_bucket"].astype(str)

    # target test size
    if test_frac is None and n_test is None:
        n_test = 384  # 95% confidence, ±5% margin for a proportion
    target = int(round(n * test_frac)) if test_frac else min(n_test, n)
    frac = target / n

    rng = np.random.default_rng(SEED)

    # proportional allocation per stratum, >=1 where the stratum is non-trivial
    parts = []
    for _, g in df.groupby("stratum", sort=False):
        k = int(round(len(g) * frac))
        k = max(k, 1) if len(g) >= 2 else 0
        k = min(k, len(g))
        if k:
            parts.append(g.sample(n=k, random_state=int(rng.integers(1e9))))
    test = pd.concat(parts).sort_index() if parts else df.sample(n=target, random_state=SEED)
    test = test.head(max(target, len(test)))  # keep proportional result

    df["split"] = "train"
    df.loc[test.index, "split"] = "test"

    train_df = df[df.split == "train"].copy()
    test_df = df[df.split == "test"].copy()

    # write splits
    train_df.to_parquet(os.path.join(data_dir, "train.parquet"), index=False)
    test_df.to_parquet(os.path.join(data_dir, "test.parquet"), index=False)

    # hand-vetting worklist: what to look up on webgis2 + blanks to fill
    work = test_df[["district_en", "block_en", "village_en", "village_hi",
                    "lgd_code" if "lgd_code" in test_df.columns else "lgd_village_code",
                    "cards_distributed", "properties_total", "size_bucket"]].copy()
    work = work.rename(columns={"lgd_village_code": "lgd_code"})
    work["plots_checked"] = ""
    work["plots_with_loan"] = ""
    work["encumbrance_notes"] = ""
    work.to_csv(os.path.join(data_dir, "vet_worklist.csv"), index=False)

    # summary
    print(f"villages (cards>0): {n:,}")
    print(f"train: {len(train_df):,}   test: {len(test_df):,}   ({len(test_df)/n*100:.1f}%)")
    print(f"strata: {df['stratum'].nunique()}  (district x size tercile)")
    print("test cards_distributed sum:", f"{int(test_df.cards_distributed.sum()):,}")
    print("districts covered in test:", test_df.district_en.nunique(), "/", df.district_en.nunique())
    print("size mix in test:", test_df.size_bucket.value_counts().to_dict())
    print(f"\n-> {data_dir}/train.parquet, {data_dir}/test.parquet")
    print(f"-> {data_dir}/vet_worklist.csv  (fill plots_checked / plots_with_loan during RoR checks)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--n-test", type=int, default=None, help="absolute test villages (default 384)")
    ap.add_argument("--test-frac", type=float, default=None, help="fractional test size, e.g. 0.2")
    a = ap.parse_args()
    make_split(a.data_dir, a.n_test, a.test_frac)
