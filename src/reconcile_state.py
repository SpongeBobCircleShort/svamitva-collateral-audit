"""
L5 — residual-bound main-claim reconciliation for a state NOT separately named in the parliamentary
loan reply (Gujarat, Chhattisgarh, Maharashtra, ...). Generalises maha_reconcile.py.

  numerator  — the state is not broken out; the four named states (RJ+MP+J&K+Ladakh) sum to 11,048
               of the national 11,147, so ALL remaining states+UTs COMBINED share only 99 loans.
               This state's card-backed loans are therefore bounded in [0, 99] — nominal by
               construction (see aggregate_numerator.state_upper_bound / residual_others).
  record     — a captcha-/gated-sample of the state's on-record charge field (MH इतर हक्क, GJ બોજો).
               Read from a worklist CSV's charge column. May be empty if the sample is not yet run.

    numerator bounded ~nominal  AND  registered charges in the sample = 0
        => the card's collateral function is nominal, not reflected in the record.

Usage:
  python src/reconcile_state.py --state Gujarat --data-dir data/gj \
      --worklist data/gj/gj_worklist.csv --charge-col boja_charge
Output: <data-dir>/<state>_reconciliation.json
"""
from __future__ import annotations

import os
import json
import argparse
import pandas as pd

try:
    from aggregate_numerator import residual_others, state_upper_bound, national_context
except ImportError:
    from src.aggregate_numerator import residual_others, state_upper_bound, national_context


def _sample(worklist: str, charge_col: str) -> dict:
    if not worklist or not os.path.exists(worklist):
        return {"checked": 0, "charges": 0, "rows": []}
    df = pd.read_csv(worklist).fillna("")
    if charge_col not in df.columns:
        return {"checked": 0, "charges": 0, "rows": []}
    done = df[df[charge_col].astype(str).str.upper().isin(["Y", "N"])]
    rows = [{"district": r.get("district", ""), "village": r.get("village", ""),
             "charge": str(r[charge_col]).upper()} for _, r in done.iterrows()]
    return {"checked": len(done),
            "charges": int((done[charge_col].astype(str).str.upper() == "Y").sum()),
            "rows": rows}


def reconcile(state: str, data_dir: str, worklist: str, charge_col: str) -> dict:
    samp = _sample(worklist, charge_col)
    resid = residual_others("data")
    num = state_upper_bound(state, "data")
    nat = national_context("data")

    bound = num.get("loans_count_upper_bound")
    reported = num["reported"]
    charges, checked = samp["charges"], samp["checked"]

    nominal = (charges == 0) and (reported is False)
    if reported:
        verdict = (f"{state} is separately reported ({num.get('loans_count')} loans); use the "
                   "state-specific reconciler rather than the residual bound.")
    elif checked == 0:
        verdict = (f"{state} is not separately reported; the residual leaves at most {bound} "
                   "card-backed loans for every unnamed state+UT combined, so its count is nominal "
                   "by construction. The on-record charge sample is not yet collected (0 checked); "
                   "the numerator bound alone already shows the collateral function is nominal.")
    elif nominal:
        verdict = (f"{state} is not separately reported; the residual bound is at most {bound} "
                   f"loans (nominal). The gated record sample confirms it: {charges} registered "
                   f"charge(s) across {checked} card(s) checked. Collateral function nominal, not "
                   "reflected in the record.")
    else:
        verdict = (f"A registered charge was observed in the {state} sample ({charges}/{checked}) — "
                   "the record reflects card collateral in at least some cases.")

    out = {
        "state": state,
        "official_national_vetted": nat,
        "numerator_upper_bound": bound,
        "reported_separately": reported,
        "residual_note": resid,
        "record_charges_observed": charges,
        "cards_checked": checked,
        "sample_rows": samp["rows"],
        "collateral_nominal": bool(nominal),
        "verdict": verdict,
    }
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, f"{state.lower().replace(' ', '_')}_reconciliation.json")
    json.dump(out, open(path, "w"), ensure_ascii=False, indent=2)
    out["_path"] = path
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--worklist", default="")
    ap.add_argument("--charge-col", default="boja_charge")
    a = ap.parse_args()
    r = reconcile(a.state, a.data_dir, a.worklist, a.charge_col)
    print(f"=== {r['state']} residual-bound reconciliation ===")
    print(f"numerator: not separately reported; upper bound {r['numerator_upper_bound']} "
          f"(residual of all unnamed states+UTs)")
    if r["official_national_vetted"]:
        print(f"national context (vetted): {r['official_national_vetted']['loans_count']:,} loans")
    print(f"record charges observed: {r['record_charges_observed']} (across {r['cards_checked']} card(s) checked)")
    for row in r["sample_rows"]:
        print(f"   - {row['district']}/{row['village']}: charge={row['charge']}")
    print(f"\nverdict: {r['verdict']}")
    print(f"-> {r['_path']}")
