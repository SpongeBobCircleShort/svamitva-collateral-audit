"""
One-shot schema probe for /ror-detail — RUN THIS YOURSELF on your machine:

    python3 src/verify_ror.py

It mints a request-id via headless Playwright, walks district->tehsil->village->plot,
fetches ONE abadi Record-of-Rights, and prints ONLY:
  * the response's field NAMES (schema), never the values,
  * which field(s) look like the loan/encumbrance (ऋण/बंधक) column,
  * whether a captcha is required.
No owner names or personal values are printed or saved. Paste the output back so the
loan field can be targeted precisely for the aggregate crawl.
"""
from __future__ import annotations

import sys
import json

try:
    from bhulekh_api import BhulekhClient
except ImportError:
    from src.bhulekh_api import BhulekhClient

LOAN_KW = ["loan", "rin", "ऋण", "बंधक", "bandhak", "mortgage", "encumbrance",
           "bank", "charge", "karj", "rehan", "रेहन", "pustika", " धन"]
CAPTCHA_KW = ["captcha", "qpf", "challenge"]


def walk_keys(obj, prefix="", out=None):
    """Collect dotted key paths (names only) from nested dict/list."""
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            out.append(p)
            walk_keys(v, p, out)
    elif isinstance(obj, list) and obj:
        walk_keys(obj[0], prefix + "[]", out)
    return out


def main():
    c = BhulekhClient()
    print("request-id minted OK")

    ds = c.districts()
    target = next((d for d in ds if "BHOPAL" in d["district_name"].upper()), ds[0])
    print("district:", target["district_name"])
    ts = c.tehsils(target["district_id"])
    teh = ts[0]
    print("tehsil:", teh["tehsil_name"])
    vs = c.villages(target["district_id"], teh["tehsil_id"])
    vil = vs[0]
    print("village:", vil["village_name"], "lgd_code:", vil["lgd_code"])
    ps = c.plots(teh["ror_district_id"], teh["ror_tehsil_id"], vil["lgd_code"])
    if not ps:
        print("no plots; try another village"); return
    plot = ps[0]
    print("plot property_id:", plot["property_id"], "count_plots:", len(ps))

    try:
        resp = c.ror_detail(teh["ror_district_id"], teh["ror_tehsil_id"],
                            vil["lgd_code"], plot["property_id"])
    except Exception as e:  # noqa: BLE001
        print("ror-detail ERROR:", str(e)[:300])
        print(">> if this is a 400, paste this message; the API lists required fields.")
        return

    keys = walk_keys(resp)
    print("\n--- ror-detail SCHEMA (field names only) ---")
    for k in keys:
        print("  ", k)

    low = [k for k in keys if any(w in k.lower() for w in LOAN_KW)]
    cap = [k for k in keys if any(w in k.lower() for w in CAPTCHA_KW)]
    top = list(resp.keys()) if isinstance(resp, dict) else []
    print("\nLOAN-like fields:", low or "NONE FOUND (need to inspect row columns)")
    print("CAPTCHA-like fields:", cap or "none")
    print("top-level keys:", top)
    # surface a captcha requirement flagged in the message, without dumping data
    msg = json.dumps(resp)[:0]  # noop to avoid printing values
    if isinstance(resp, dict) and resp.get("status") is False:
        print("status=false; message:", str(resp.get("message"))[:120])


if __name__ == "__main__":
    sys.exit(main())
