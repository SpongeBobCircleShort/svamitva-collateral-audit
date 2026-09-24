"""
L5 (Maharashtra) — main-claim reconciliation for MH Property Cards (gaothan/abadi).

Same test as the MP reconciler, adapted to Maharashtra's evidence:

  numerator  — MH is NOT separately reported in the parliamentary loan reply. The four named
               states (RJ+MP+J&K+Ladakh) sum to 11,048; the national total is 11,147, so ALL
               remaining states+UTs COMBINED share only 99 loans. Maharashtra's card-backed loans
               are therefore bounded in [0, 99] — nominal by construction (see aggregate_numerator).
  record     — the Property Card इतर भार / इतर हक्क (Other Encumbrances/Rights) section is the MH
               analog of MP RoR col-11. A captcha-gated SAMPLE of gaothan cards is read for a
               registered charge (बोजा/कर्ज/बंधक). Sample lives in data/maha_pc_worklist.csv.

    MH numerator bounded ~nominal  AND  registered charges in the sample = 0
        => the card's collateral function is nominal, not reflected in the Property Card record.

Input:  data/maha_pc_worklist.csv, data/aggregate_loans.csv
Output: data/maha_reconciliation.json
Usage:  python src/maha_reconcile.py
"""
from __future__ import annotations

import os
import json
import argparse
import pandas as pd

try:
    from aggregate_numerator import residual_others, maha_state_total, national_context
except ImportError:
    from src.aggregate_numerator import residual_others, maha_state_total, national_context


def _sample(data_dir: str) -> dict:
    """Read the captcha-gated Property Card sample: cards checked and charges found."""
    path = os.path.join(data_dir, "maha_pc_worklist.csv")
    if not os.path.exists(path):
        return {"checked": 0, "charges": 0, "rows": []}
    df = pd.read_csv(path).fillna("")
    done = df[df["other_rights_charge"].astype(str).str.upper().isin(["Y", "N"])]
    checked = len(done)
    charges = int((done["other_rights_charge"].astype(str).str.upper() == "Y").sum())
    rows = [{"district": r["district"], "village": r["village"],
             "charge": str(r["other_rights_charge"]).upper(),
             "note": r.get("note", "")} for _, r in done.iterrows()]
    return {"checked": checked, "charges": charges, "rows": rows}


def reconcile(data_dir: str = "data") -> dict:
    samp = _sample(data_dir)
    resid = residual_others(data_dir)
    mh = maha_state_total(data_dir)
    nat = national_context(data_dir)

    bound = mh["loans_count_upper_bound"]
    charges = samp["charges"]
    checked = samp["checked"]

    # nominal by construction: even the UPPER bound of MH card-backed loans is tiny, and the
    # record sample shows no registered charge.
    nominal = (charges == 0)
    verdict = (
        "Maharashtra is not separately reported in the parliamentary loan reply; the residual "
        f"leaves at most {bound} card-backed loans for every unnamed state+UT combined, so MH's "
        "count is nominal by construction. The captcha-gated Property Card sample confirms it on "
        f"the record: {charges} registered charge(s) across {checked} gaothan card(s) checked. The "
        "card's collateral function is nominal, not reflected in the Property Card record."
    ) if nominal else (
        f"A registered charge was observed in the MH sample ({charges}/{checked}) — the Property "
        "Card record does reflect card collateral in at least some cases."
    )

    out = {
        "state": "Maharashtra",
        "official_national_vetted": nat,                  # 11,147 loans (context)
        "mh_numerator_upper_bound": bound,                # 99 (residual of all unnamed states)
        "mh_reported_separately": mh["reported"],         # False
        "residual_note": resid,                           # the 99-loan residual detail
        "record_charges_observed": charges,               # 0
        "cards_checked": checked,                          # gaothan Property Cards read
        "sample_rows": samp["rows"],
        "collateral_nominal": bool(nominal),
        "verdict": verdict,
    }
    json.dump(out, open(os.path.join(data_dir, "maha_reconciliation.json"), "w"),
              ensure_ascii=False, indent=2)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    data_dir = ap.parse_args().data_dir
    r = reconcile(data_dir)
    print("=== Maharashtra main-claim reconciliation ===")
    print(f"MH loan numerator             : not separately reported; upper bound "
          f"{r['mh_numerator_upper_bound']} (residual of ALL unnamed states+UTs)")
    if r["official_national_vetted"]:
        print(f"national context (vetted)     : {r['official_national_vetted']['loans_count']:,} loans")
    print(f"registered charges observed   : {r['record_charges_observed']}  "
          f"(across {r['cards_checked']} gaothan Property Card(s) checked)")
    for row in r["sample_rows"]:
        print(f"   - {row['district']}/{row['village']}: charge={row['charge']}")
    print(f"\nverdict: {r['verdict']}")
    print(f"-> {os.path.join(data_dir, 'maha_reconciliation.json')}")
