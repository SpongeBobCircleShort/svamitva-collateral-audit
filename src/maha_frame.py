"""
Maharashtra Property Card sampling frame — one gaothan/abadi village per district (the MH analog
of MP's 55-village frame). Ungated (hierarchy only), so it runs unattended.

For each district it finds the first City-Survey office that lists gaothan villages and picks one,
writing data/maha_pc_worklist.csv (district, office_code, office, village_code, village, +blank
columns the assisted sampler fills: pc_no, mobile_used, other_rights_charge, note).

Usage:  python src/maha_frame.py
"""
from __future__ import annotations

import os
import argparse
import pandas as pd

try:
    from maha_api import MahabhulekhClient, DISTRICTS, PFX
except ImportError:
    from src.maha_api import MahabhulekhClient, DISTRICTS, PFX

COLS = ["district", "office_code", "office", "village_code", "village",
        "pc_no", "other_rights_charge", "note"]
TAL_ID = "ContentPlaceHolder1_ddlTalForAll"
VILL_ID = "ContentPlaceHolder1_ddlVillForAll"


def build(data_dir: str = "data") -> pd.DataFrame:
    c = MahabhulekhClient()
    rows = []
    for dist, code in DISTRICTS.items():
        picked = None
        try:
            # set district ONCE per district, then postback each office (reuse state — fast)
            c._load()
            c._select_record_type("property_card")
            dh = c._postback(PFX + "ddlMainDist", {PFX + "ddlMainDist": code})
            offices = c._options(dh, TAL_ID)
        except Exception as e:  # noqa: BLE001
            print(f"{dist}: office err {str(e)[:50]}"); rows.append(_blank(dist)); continue
        for oc, oname in offices:
            try:
                vh = c._postback(PFX + "ddlTalForAll", {PFX + "ddlTalForAll": oc})
                vills = c._options(vh, VILL_ID)
            except Exception:  # noqa: BLE001
                continue
            if vills:
                vc, vn = vills[0]
                picked = {"district": dist, "office_code": oc, "office": oname,
                          "village_code": vc, "village": vn}
                break
        if picked:
            rows.append({**picked, "pc_no": "", "other_rights_charge": "", "note": ""})
            print(f"{dist}: {picked['village']} (office {picked['office'][:30]})")
        else:
            rows.append(_blank(dist))
            print(f"{dist}: no gaothan village found")

    df = pd.DataFrame(rows, columns=COLS)
    out = os.path.join(data_dir, "maha_pc_worklist.csv")
    df.to_csv(out, index=False)
    got = df["village"].astype(str).str.len().gt(0).sum()
    print(f"\nframe: {got}/{len(df)} districts with a gaothan village -> {out}")
    return df


def _blank(dist):
    return {"district": dist, "office_code": "", "office": "", "village_code": "",
            "village": "", "pc_no": "", "other_rights_charge": "", "note": "no gaothan village"}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    build(ap.parse_args().data_dir)
