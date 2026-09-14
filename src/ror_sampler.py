"""
L3 — RoR encumbrance sampler for the 396-village holdout. RUN ON YOUR MACHINE.

For each test village it lists plots and reads the RoR loan/encumbrance column (col 11:
बंधक / दृष्टिबंधक / भू-ऋण), aggregates plots_checked / plots_with_loan per village, and writes
back into data/vet_worklist.csv. NO owner PII is stored — only counts.

Prereq: run `python src/capture_ror.py` once, so data/ror_request.json (the exact ror-detail
request) and data/ror_schema.txt (the encumbrance field) are known. Two spots below are marked
FINALIZE-FROM-CAPTURE and are set from that output.

Captcha: assisted. A captcha is solved once per batch (OCR if pytesseract+tesseract present,
else you type it) and reused until the server rejects it, then re-solved. Small volume, polite
delay, resumable. This is a sample, not a census.

Usage:
  python src/ror_sampler.py --limit 5 --max-plots 10     # smoke test
  python src/ror_sampler.py --max-plots 20               # full holdout
"""
from __future__ import annotations

import os
import re
import time
import argparse
import pandas as pd

try:
    from bhulekh_api import BhulekhClient, _pick
except ImportError:
    from src.bhulekh_api import BhulekhClient, _pick

LOAN_KW = ["विल्लंगम", "बंधक", "दृष्टिबंधक", "भू-ऋण", "ऋण", "प्रभार",
           "vilangam", "bandhak", "rin", "loan", "mortgage", "encumbrance", "charge"]
EMPTY = {"", "-", "0", "null", "none", "na", "n/a", "शून्य", "निरंक", "nil"}


def _village_index(client: BhulekhClient, district_en: str, cache: dict) -> dict:
    """lgd_code -> (ror_district_id, ror_tehsil_id) for one district (cached)."""
    if district_en in cache:
        return cache[district_en]
    idx = {}
    d = next((x for x in client.districts()
              if x["district_name"].strip().upper() == district_en.strip().upper()), None)
    if d:
        for t in client.tehsils(d["district_id"]):
            for v in client.villages(d["district_id"], t["tehsil_id"]):
                idx[str(v["lgd_code"])] = (v["ror_district_id"], v["ror_tehsil_id"])
    cache[district_en] = idx
    return idx


def _solve_captcha(client: BhulekhClient) -> dict:
    """Return the captcha fields ror-detail needs. Assisted OCR/manual.
    FINALIZE-FROM-CAPTURE: exact generate/validate paths + field names come from ror_schema.txt.
    Returns {} if this deployment doesn't gate ror-detail with a captcha."""
    try:
        g = client.s.post("https://webgis2.mpbhulekh.gov.in/captcha/v1/public/generate",
                          json={"tenant_id": "gov.in"},
                          headers={"qp-tc-request-id": client.rid}, verify=False, timeout=30)
        data = g.json().get("data", g.json())
    except Exception:
        return {}
    img_b64 = data.get("image") or data.get("captcha") or ""
    cap_id = data.get("id") or data.get("captcha_id") or data.get("uuid")
    text = ""
    try:
        import base64, io
        from PIL import Image
        import pytesseract
        raw = base64.b64decode(re.sub(r"^data:image/\w+;base64,", "", img_b64))
        text = re.sub(r"\W", "", pytesseract.image_to_string(Image.open(io.BytesIO(raw))))[:6]
    except Exception:
        pass
    if not text:
        path = os.path.join("data", "captcha.png")
        try:
            import base64
            open(path, "wb").write(base64.b64decode(re.sub(r"^data:image/\w+;base64,", "", img_b64)))
            text = input(f"captcha saved to {path} — type the {len(img_b64) and 5}-char code: ").strip()
        except Exception:
            return {}
    return {"captcha": text, "captcha_id": cap_id}


def _count_encumbrance(resp) -> tuple[int, int, str]:
    """Given a ror-detail response, return (parcels_seen, parcels_with_loan, note).
    FINALIZE-FROM-CAPTURE: point this at the exact col-11 field once ror_schema.txt is known.
    Generic default: JSON rows -> loan-ish key non-empty; HTML -> encumbrance column cell."""
    # JSON case
    if isinstance(resp, (dict, list)):
        data = resp.get("data", resp) if isinstance(resp, dict) else resp
        rows = data if isinstance(data, list) else [data]
        seen = with_loan = 0
        for r in rows:
            if not isinstance(r, dict):
                continue
            seen += 1
            lk = next((k for k in r if any(w in k.lower() for w in
                       [x.lower() for x in LOAN_KW])), None)
            if lk and str(r[lk]).strip().lower() not in EMPTY:
                with_loan += 1
        return seen, with_loan, "json"
    # HTML case
    html = str(resp)
    has = any(w in html for w in LOAN_KW)
    # crude: encumbrance column non-empty if a loan keyword header exists and a value follows
    return (1, 1 if (has and re.search(r"(बंधक|ऋण|mortgage)", html)) else 0, "html")


def run(data_dir: str, limit: int | None, max_plots: int, delay: float):
    wl_path = os.path.join(data_dir, "vet_worklist.csv")
    wl = pd.read_csv(wl_path)
    keycol = "lgd_code" if "lgd_code" in wl.columns else "lgd_village_code"
    todo = wl[wl["plots_checked"].isna() | (wl["plots_checked"] == "")].copy()
    if limit:
        todo = todo.head(limit)
    print(f"holdout villages to sample: {len(todo)} (of {len(wl)})")

    client = BhulekhClient()
    cache: dict = {}
    captcha = _solve_captcha(client)

    for pos, (i, row) in enumerate(todo.iterrows(), 1):
        lgd = str(row[keycol])
        dname = str(row.get("district_en") or row.get("district") or "")
        vname = str(row.get("village_en") or row.get("village") or lgd)
        idx = _village_index(client, dname, cache)
        if lgd not in idx:
            wl.loc[i, ["plots_checked", "plots_with_loan", "encumbrance_notes"]] = [0, 0, "village not found on webgis2"]
            continue
        rdid, rtid = idx[lgd]
        try:
            plots = client.plots(rdid, rtid, lgd)[:max_plots]
        except Exception as e:  # noqa: BLE001
            wl.loc[i, "encumbrance_notes"] = f"plot err: {str(e)[:80]}"
            continue

        checked = withloan = 0
        for p in plots:
            pid = p["property_id"]
            try:
                yr = _pick(client.years(pid), "publish_year", "year")
                ver = _pick(client.versions(pid, yr), "version", "ror_version") if yr else None
                resp = client.ror_detail(pid, yr, ver, extra=captcha)
            except Exception as e:  # noqa: BLE001
                if "captcha" in str(e).lower():
                    captcha = _solve_captcha(client)   # refresh and retry this plot next pass
                continue
            s, w, _ = _count_encumbrance(resp)
            checked += s or 1
            withloan += w
            time.sleep(delay)

        wl.loc[i, ["plots_checked", "plots_with_loan", "encumbrance_notes"]] = [checked, withloan, ""]
        wl.to_csv(wl_path, index=False)   # checkpoint after each village
        print(f"[{pos}/{len(todo)}] {dname}/{vname}: {withloan}/{checked} plots w/ loan")

    print(f"\ndone. worklist updated -> {wl_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--max-plots", type=int, default=15)
    ap.add_argument("--delay", type=float, default=1.5)
    a = ap.parse_args()
    run(a.data_dir, a.limit, a.max_plots, a.delay)
