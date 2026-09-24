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

Maharashtra is NOT separately reported. Only four entities break out (RJ+MP+J&K+Ladakh =
11,048 loans); the national total is 11,147. So every remaining state and UT COMBINED shares a
residual of 99 loans. Maharashtra's SVAMITVA-backed loan count is therefore bounded in [0, 99]
— nominal by construction — even though MH has issued cards at scale. This residual bound is the
Maharashtra numerator (see residual_others() / maha_state_total()).

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

_RESID = ("RESIDUAL UPPER BOUND — Maharashtra not separately reported; national total minus the "
          "four named states (RJ+MP+J&K+Ladakh = 11,048) leaves 99 loans for ALL remaining "
          "states+UTs COMBINED, so MH card-backed loans are bounded in [0, 99] — nominal.")

SEED = [
    # UNVETTED state splits (kept for provenance, excluded from the live verdict)
    ["state", "Madhya Pradesh", "", 2202, 177.77, _SEC, "SVAMITVA-backed loans (state-wise)", "2026-08", "2026-08-05", _KL, False, _PROV],
    ["state", "Rajasthan", "", 8808, 1519.68, _SEC, "SVAMITVA-backed loans (state-wise)", "2026-08", "2026-08-05", _KL, False, _PROV],
    ["state", "Jammu & Kashmir", "", 29, 3.97, _SEC, "SVAMITVA-backed loans (state-wise)", "2026-08", "2026-08-05", _KL, False, _PROV],
    ["state", "Ladakh", "", 9, 1.61, _SEC, "SVAMITVA-backed loans (state-wise)", "2026-08", "2026-08-05", _KL, False, _PROV],
    # Maharashtra: not separately reported -> residual upper bound only (all-others share 99)
    ["state", "Maharashtra", "", 99, 0.0, _RS, "SVAMITVA-backed loans (residual bound)", "2026-08-05", "2026-08-05", _ANI, False, _RESID],
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


_NAMED_STATES = ("Rajasthan", "Madhya Pradesh", "Jammu & Kashmir", "Ladakh")


def residual_others(data_dir: str = "data") -> dict | None:
    """National total minus the separately-named states = loans shared by ALL other states+UTs.
    This is the upper bound on any single unnamed state's card-backed loans (e.g. Maharashtra)."""
    df = load(data_dir)
    nat = df[(df.level == "national") & df.vetted]
    if nat.empty:
        return None
    named = df[(df.level == "state") & df.state.isin(_NAMED_STATES)]
    resid_loans = int(nat.iloc[0].loans_count) - int(named.loans_count.sum())
    resid_cr = round(float(nat.iloc[0].loan_amount_cr) - float(named.loan_amount_cr.sum()), 2)
    return {"loans_count": resid_loans, "loan_amount_cr": resid_cr,
            "named_states": list(_NAMED_STATES), "as_of": nat.iloc[0].as_of}


def maha_state_total(data_dir: str = "data") -> dict:
    """Maharashtra numerator: not separately reported, so an upper bound only.
    Returns the residual bound (all-unnamed-states share) as MH's ceiling."""
    r = residual_others(data_dir)
    bound = r["loans_count"] if r else None
    return {"loans_count_upper_bound": bound, "reported": False,
            "note": "MH not separately reported; loans bounded [0, %s] (residual of all unnamed states+UTs)"
                    % (bound if bound is not None else "?")}


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

    resid = residual_others(a.data_dir)
    mh = maha_state_total(a.data_dir)
    if resid:
        print(f"\nResidual (all states+UTs except {', '.join(resid['named_states'])}): "
              f"{resid['loans_count']:,} loans / Rs {resid['loan_amount_cr']:.2f} cr")
    print(f"Maharashtra numerator: {mh['note']}")
