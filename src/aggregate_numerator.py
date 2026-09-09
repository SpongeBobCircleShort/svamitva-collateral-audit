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
           "source", "doc_title", "doc_date", "as_of", "url", "vetted", "note"]

# Attribution status (see the citation trail in the session):
#  - National total is wire-reported (ANI) from a Rajya Sabha written reply, 05-08-2026,
#    by the Min. of Panchayati Raj (Rajiv Ranjan "Lalan" Singh) -> treated as VETTED context.
#  - The state-wise split (incl. MP 2,202) appears only in a single secondary outlet, with an
#    unresolved House attribution and no retrievable primary annexure -> UNVETTED / provisional.
_ANI = "https://aninews.in/news/national/general-news/330-lakh-villages-mapped-under-svamitva-scheme-rs-1713-cr-loans-disbursed-using-property-cards20260805182142/"
_KL = ("https://kashmirlife.net/29-svamitva-backed-loans-worth-rs-3-97-crore-"
       "disbursed-in-jammu-kashmir-lok-sabha-told-447515/")
_RS = "Rajya Sabha written reply, Ministry of Panchayati Raj"
_SEC = "News report (secondary) citing a parliamentary reply"
_PROV = "PROVISIONAL — single secondary source; House attribution unresolved; primary annexure not retrieved"

SEED = [
    # UNVETTED state splits (kept for provenance, excluded from the live verdict)
    ["state", "Madhya Pradesh", "", 2202, 177.77, _SEC, "SVAMITVA-backed loans (state-wise)", "2026-08", "2026-08-05", _KL, False, _PROV],
    ["state", "Rajasthan", "", 8808, 1519.68, _SEC, "SVAMITVA-backed loans (state-wise)", "2026-08", "2026-08-05", _KL, False, _PROV],
    ["state", "Jammu & Kashmir", "", 29, 3.97, _SEC, "SVAMITVA-backed loans (state-wise)", "2026-08", "2026-08-05", _KL, False, _PROV],
    ["state", "Ladakh", "", 9, 1.61, _SEC, "SVAMITVA-backed loans (state-wise)", "2026-08", "2026-08-05", _KL, False, _PROV],
    # VETTED national context (wire-reported RS reply)
    ["national", "ALL INDIA", "", 11147, 1713.68, _RS, "SVAMITVA-backed loans (national total)", "2026-08-05", "2026-08-05", _ANI, True, "national total, wire-reported (ANI)"],
]


def seed_csv(path: str) -> pd.DataFrame:
    df = pd.DataFrame(SEED, columns=COLUMNS)
    df.to_csv(path, index=False)
    return df


def load(data_dir: str = "data") -> pd.DataFrame:
    path = os.path.join(data_dir, "aggregate_loans.csv")
    if not os.path.exists(path):
        seed_csv(path)
    df = pd.read_csv(path)
    if "vetted" not in df.columns:      # older csv -> treat everything as unvetted
        df["vetted"] = False
    df["vetted"] = df["vetted"].astype(bool)
    return df


def mp_state_total(data_dir: str = "data") -> dict | None:
    """Vetted MP state loan total, or None if no vetted figure exists."""
    df = load(data_dir)
    row = df[(df.level == "state") & (df.state == "Madhya Pradesh") & df.vetted]
    if row.empty:
        return None
    r = row.iloc[0]
    return {"loans_count": int(r.loans_count), "loan_amount_cr": float(r.loan_amount_cr),
            "as_of": r.as_of, "url": r.url}


def national_context(data_dir: str = "data") -> dict | None:
    """Vetted national total, shown only as clearly-labelled external context."""
    df = load(data_dir)
    row = df[(df.level == "national") & df.vetted]
    if row.empty:
        return None
    r = row.iloc[0]
    return {"loans_count": int(r.loans_count), "loan_amount_cr": float(r.loan_amount_cr),
            "as_of": r.as_of, "url": r.url}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    a = ap.parse_args()

    agg = load(a.data_dir)
    print(f"aggregate_loans.csv rows: {len(agg)}")
    print(agg[["level", "state", "loans_count", "loan_amount_cr", "vetted", "as_of"]].to_string(index=False))

    mp = mp_state_total(a.data_dir)
    nat = national_context(a.data_dir)
    print(f"\nVetted MP loan figure: {mp if mp else 'NONE — MP loan numerator is unvetted, excluded from the verdict'}")
    print(f"Vetted national context: {nat['loans_count']:,} loans / Rs {nat['loan_amount_cr']:.2f} cr" if nat else "none")
