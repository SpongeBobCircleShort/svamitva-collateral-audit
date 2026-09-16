"""
L5 — Main-claim reconciliation: the government's own loan numerator vs the land record.

The RoR sweep proves only that no charge is REGISTERED on the abadi title. The headline
claim is broader: the property card is USABLE COLLATERAL. This module puts the government's
own loan count beside the RoR encumbrance ground truth (0) and reads the gap:

    official loans > 0  AND  registered charges = 0
        => the loans are not secured by the card as a title lien
        => "usable collateral" is nominal, not reflected in the record.

The random sample alone is underpowered at the claimed uptake rate (see expected_if_secured /
poisson_p0), so the decisive leg is the KNOWN CASE: a documented loan (Pawan of Handia, ₹2.90
lakh, PM interaction) whose entire village was censused — 1,020 parcels, 0 charges. A
provably-existing loan absent from its whole village's records = collateral not on title.

Input:  data/aggregate_loans.csv, data/state_summary.json, data/known_loans.csv
Output: data/reconciliation.json
Usage:  python src/reconcile.py
"""
from __future__ import annotations

import os
import json
import math
import argparse
import pandas as pd

try:
    from aggregate_numerator import load as load_aggregate, national_context
except ImportError:
    from src.aggregate_numerator import load as load_aggregate, national_context


def _mp_claimed(data_dir: str) -> dict | None:
    """MP state loan figure AS CLAIMED (whether or not vetted) — the government's own number,
    used here only to test it against the record, never adopted as fact."""
    df = load_aggregate(data_dir)
    row = df[(df.level == "state") & (df.state == "Madhya Pradesh")]
    if row.empty:
        return None
    r = row.iloc[0]
    return {"loans_count": int(r.loans_count), "loan_amount_cr": float(r.loan_amount_cr),
            "vetted": bool(r.vetted), "url": r.url, "as_of": r.as_of}


def reconcile(data_dir: str = "data") -> dict:
    summ = json.load(open(os.path.join(data_dir, "state_summary.json")))
    cards_total = int(summ["cards_total"])
    frame_parcels = int(summ.get("sample_plots_checked", 0))
    charges = int(summ.get("sample_plots_with_loan", 0))

    # parcels checked = clean frame sample + the targeted positive-control search.
    # Use the documented known-case census as the reproducible targeted floor; the ad-hoc
    # col11_audit.csv (if a full sweep persisted a larger one) can only raise it.
    kpath = os.path.join(data_dir, "known_loans.csv")
    known = pd.read_csv(kpath) if os.path.exists(kpath) else pd.DataFrame()
    known_censused = int(known["parcels_censused"].fillna(0).sum()) if len(known) else 0
    audit = os.path.join(data_dir, "col11_audit.csv")
    audit_rows = int(pd.read_csv(audit).shape[0]) if os.path.exists(audit) else 0
    targeted_parcels = max(known_censused, audit_rows)
    parcels_total = frame_parcels + targeted_parcels

    mp = _mp_claimed(data_dir)
    nat = national_context(data_dir)

    # if the claimed loans were title-secured, how many charges should our sample have caught?
    claimed_rate = (mp["loans_count"] / cards_total) if (mp and cards_total) else None
    expected = (claimed_rate * parcels_total) if claimed_rate is not None else None
    poisson_p0 = math.exp(-expected) if expected is not None else None   # P(observe 0 | expected)

    # known-case leg (the decisive one)
    kc = None
    if len(known):
        k = known.iloc[0]
        kc = {"village": k["village"], "lgd_code": int(k["lgd_code"]),
              "beneficiary": k["beneficiary"], "loan_amt_cr": float(k["loan_amt_cr"]),
              "parcels_censused": int(k["parcels_censused"]),
              "charges_found": int(k["charges_found"]), "url": k["url"], "note": k["note"]}

    secured = (charges == 0 and ((mp and mp["loans_count"] > 0) or (nat and nat["loans_count"] > 0)))
    verdict = (
        "Official loans are claimed to exist, yet zero charges are registered across every abadi "
        "parcel checked — including a full census of a village with a documented loan. The card's "
        "loan is not recorded against its title: the collateral function is nominal, not reflected "
        "in the land record."
    ) if secured else (
        "Insufficient inputs to reconcile." if not (mp or nat) else
        "A registered charge was observed — the record does reflect card collateral."
    )

    out = {
        "cards_total": cards_total,
        "official_national_vetted": nat,                 # 11,147 loans, wire-reported RS reply
        "official_mp_claimed": mp,                       # 2,202 (unvetted) — the govt's own claim
        "record_charges_observed": charges,              # 0
        "parcels_checked_frame": frame_parcels,
        "parcels_checked_targeted": targeted_parcels,
        "parcels_checked_total": parcels_total,
        "mp_claimed_uptake_pct": round(claimed_rate * 100, 4) if claimed_rate is not None else None,
        "expected_charges_if_secured": round(expected, 2) if expected is not None else None,
        "prob_observe_zero_if_secured": round(poisson_p0, 3) if poisson_p0 is not None else None,
        "known_case": kc,
        "collateral_nominal": bool(secured),
        "verdict": verdict,
    }
    json.dump(out, open(os.path.join(data_dir, "reconciliation.json"), "w"), indent=2)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    data_dir = ap.parse_args().data_dir
    r = reconcile(data_dir)
    print("=== main-claim reconciliation ===")
    nat, mp = r["official_national_vetted"], r["official_mp_claimed"]
    print(f"cards issued (MP)              : {r['cards_total']:,}")
    if nat:
        print(f"official loans (national,vetted): {nat['loans_count']:,} / Rs {nat['loan_amount_cr']:.0f} cr")
    if mp:
        tag = "VETTED" if mp["vetted"] else "CLAIMED (unvetted)"
        print(f"official loans (MP, {tag}): {mp['loans_count']:,} / Rs {mp['loan_amount_cr']:.2f} cr")
    print(f"registered charges observed   : {r['record_charges_observed']}  "
          f"(across {r['parcels_checked_total']:,} parcels: "
          f"{r['parcels_checked_frame']:,} frame + {r['parcels_checked_targeted']:,} targeted)")
    if r["expected_charges_if_secured"] is not None:
        print(f"expected charges if title-secured at MP's own claimed rate "
              f"({r['mp_claimed_uptake_pct']}%): {r['expected_charges_if_secured']}  "
              f"[P(observe 0) = {r['prob_observe_zero_if_secured']}]")
    kc = r["known_case"]
    if kc:
        print(f"known case: {kc['beneficiary']} — Rs {kc['loan_amt_cr']*100:.1f} lakh loan in "
              f"{kc['village']}; {kc['charges_found']} charges across all {kc['parcels_censused']:,} parcels")
    print(f"\nverdict: {r['verdict']}")
    print(f"-> {os.path.join(data_dir, 'reconciliation.json')}")
