"""
L2 — Aggregate numerator: official loans sanctioned against SVAMITVA property cards.

Per-parcel loan data is captcha/replay-gated (see plan), and there is no public district-wise
release, so the authoritative numerator is the state total placed before Parliament. This module
curates those figures (with provenance) into data/aggregate_loans.csv and joins them to the
scraped card denominator to give an official collateral-uptake rate.

Seeded from the Lok Sabha reply (Ministry of Panchayati Raj), loan data as on 2026-08-05:
  Madhya Pradesh   2,202 loans / Rs 177.77 cr
  Rajasthan        8,808 loans / Rs 1,519.68 cr   (peer benchmark — highest uptake)
  Jammu & Kashmir     29 loans / Rs 3.97 cr
  Ladakh               9 loans / Rs 1.61 cr
  ALL INDIA       11,147 loans / Rs 1,713.68 cr

The CSV is the editable source of truth: add district rows (e.g. from an RTI reply or a
readable SLBC table) with level=district and they flow straight into the dashboard.

Usage:
  python src/aggregate_numerator.py            # seed csv if absent, print MP uptake
"""
from __future__ import annotations

import os
import argparse
import pandas as pd

COLUMNS = ["level", "state", "district", "loans_count", "loan_amount_cr",
           "source", "doc_title", "doc_date", "as_of", "url", "note"]

_SRC = "Lok Sabha (Ministry of Panchayati Raj)"
_URL = ("https://kashmirlife.net/29-svamitva-backed-loans-worth-rs-3-97-crore-"
        "disbursed-in-jammu-kashmir-lok-sabha-told-447515/")
_DOC = "Lok Sabha reply on SVAMITVA-backed loans"

SEED = [
    ["state", "Madhya Pradesh", "", 2202, 177.77, _SRC, _DOC, "2026-08-11", "2026-08-05", _URL, ""],
    ["state", "Rajasthan", "", 8808, 1519.68, _SRC, _DOC, "2026-08-11", "2026-08-05", _URL, "peer benchmark"],
    ["state", "Jammu & Kashmir", "", 29, 3.97, _SRC, _DOC, "2026-08-11", "2026-08-05", _URL, ""],
    ["state", "Ladakh", "", 9, 1.61, _SRC, _DOC, "2026-08-11", "2026-08-05", _URL, ""],
    ["national", "ALL INDIA", "", 11147, 1713.68, _SRC, _DOC, "2026-08-11", "2026-08-05", _URL, "national total"],
]


def seed_csv(path: str) -> pd.DataFrame:
    df = pd.DataFrame(SEED, columns=COLUMNS)
    df.to_csv(path, index=False)
    return df


def load(data_dir: str = "data") -> pd.DataFrame:
    path = os.path.join(data_dir, "aggregate_loans.csv")
    if not os.path.exists(path):
        seed_csv(path)
    return pd.read_csv(path)


def mp_state_total(data_dir: str = "data") -> dict:
    df = load(data_dir)
    row = df[(df.level == "state") & (df.state == "Madhya Pradesh")].iloc[0]
    return {"loans_count": int(row.loans_count), "loan_amount_cr": float(row.loan_amount_cr),
            "as_of": row.as_of, "url": row.url}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    a = ap.parse_args()

    agg = load(a.data_dir)
    print(f"aggregate_loans.csv rows: {len(agg)}")
    print(agg[["level", "state", "loans_count", "loan_amount_cr", "as_of"]].to_string(index=False))

    dpath = os.path.join(a.data_dir, "svamitva_districts.parquet")
    if os.path.exists(dpath):
        cards = int(pd.read_parquet(dpath).cards_distributed.fillna(0).sum())
        mp = mp_state_total(a.data_dir)
        rate = mp["loans_count"] / cards * 100 if cards else 0
        print(f"\nMP cards distributed: {cards:,}")
        print(f"MP loans against cards (official): {mp['loans_count']:,} "
              f"(Rs {mp['loan_amount_cr']:.2f} cr, as on {mp['as_of']})")
        print(f"Official collateral-uptake rate: {rate:.4f}%  "
              f"(1 loan per ~{cards // max(mp['loans_count'],1):,} cards)")
