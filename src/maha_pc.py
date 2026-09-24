"""
Maharashtra Property Card (gaothan / abadi) record inventory — the SVAMITVA-equivalent layer,
the analog of MP's abadi village census. RUN ON YOUR MACHINE (hits Mahabhulekh).

For a district it walks every City-Survey / Land-Records office and lists the gaothan villages
that HAVE a Property Card record (ungated existence signal), writing one row per village to
data/maha_pc_villages_<district>.csv. The record CONTENT (owners + इतर हक्क / Other Rights
encumbrance) is mobile+captcha gated and collected assisted (see maha_api.fetch_record).

Usage:
  python src/maha_pc.py --district Pune
  python src/maha_pc.py --district Sindhudurg
"""
from __future__ import annotations

import os
import re
import argparse
import pandas as pd

try:
    from maha_api import MahabhulekhClient, DISTRICTS
except ImportError:
    from src.maha_api import MahabhulekhClient, DISTRICTS


def build(district: str, data_dir: str = "data") -> pd.DataFrame:
    if district not in DISTRICTS:
        raise SystemExit(f"unknown district '{district}'. Known: {', '.join(sorted(DISTRICTS))}")
    code = DISTRICTS[district]
    c = MahabhulekhClient()
    offices = c.pc_offices(code)
    print(f"{district}: {len(offices)} Property Card offices")
    rows = []
    for oc, oname in offices:
        try:
            vills = c.villages(code, oc, "property_card")
        except Exception as e:  # noqa: BLE001
            print(f"  office {oc} {oname[:40]}: err {str(e)[:50]}"); continue
        for vc, vn in vills:
            rows.append({"district": district, "office_code": oc, "office": oname,
                         "village_code": vc, "village": vn, "property_card_record": "Y"})
        print(f"  office {oc} {oname[:44]}: {len(vills)} gaothan villages")

    df = pd.DataFrame(rows, columns=["district", "office_code", "office",
                                     "village_code", "village", "property_card_record"])
    safe = re.sub(r"[^A-Za-z0-9]+", "_", district).strip("_")
    out = os.path.join(data_dir, f"maha_pc_villages_{safe}.csv")
    df.to_csv(out, index=False)
    print(f"\n{district}: {len(df)} gaothan villages with a Property Card record -> {out}")
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--district", default="Pune")
    ap.add_argument("--data-dir", default="data")
    build(ap.parse_args().district, ap.parse_args().data_dir)
