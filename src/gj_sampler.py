"""
Gujarat VF-7 બોજો (boja / charge) sampler — ASSISTED / USER-RUN (the record view is captcha-gated).

For each village in a frame it cascades to the VF-7 survey (ungated), shows you the captcha, and on
your captcha fetches the record and reads the બોજો (encumbrance) field — the Gujarat collateral
signal (analog of MP RoR col-11 / MH इतर हक्क). This code never solves the captcha: it saves the
captcha image and you type the value. Bounded to one record per village; resumable.

Frame: data/gj/gj_worklist.csv with columns district,taluka,village,survey_no (+ blank
boja_charge,note the sampler fills). Build one from the SIPI sheet with --from-sheet:
  python src/gj_sampler.py --from-sheet "/path/SIPI ... .csv" --per-district
Then run the assisted sample:
  python src/gj_sampler.py

Geography (English sheet) is resolved to AnyRoR Gujarati codes via the CG-style transliterate+fuzzy
helpers in gj_verify_sipi. Aggregate-only: owner names are never stored.
"""
from __future__ import annotations

import os
import time
import argparse
import pandas as pd

try:
    from gj_api import AnyRoRClient, boja
    from gj_verify_sipi import GJ_DISTRICTS, _en, _best, _survey_key
except ImportError:
    from src.gj_api import AnyRoRClient, boja
    from src.gj_verify_sipi import GJ_DISTRICTS, _en, _best, _survey_key

from rapidfuzz import fuzz, process

WL_COLS = ["district", "taluka", "village", "survey_no", "boja_charge", "note"]
RECORD_MARKERS = ("ગા.ન", "સર્વે", "ખાતેદાર", "survey", "vf-7", "બોજો", "record")


def _resolve(c: AnyRoRClient, dist, tal, vil, dcache):
    tgt = _en(dist)
    cand = {code: _en(nm) for code, nm in GJ_DISTRICTS.items()}
    m = process.extractOne(tgt, cand, scorer=fuzz.WRatio, score_cutoff=70)
    dcode = m[2] if m else None
    if not dcode:
        return None, "district not matched"
    if dcode not in dcache:
        dcache[dcode] = {"tal": c.talukas(dcode), "vill": {}}
    tcode = _best(tal, dcache[dcode]["tal"])
    if not tcode:
        return None, "taluka not matched"
    if tcode not in dcache[dcode]["vill"]:
        dcache[dcode]["vill"][tcode] = c.villages(dcode, tcode)
    vcode = _best(vil, dcache[dcode]["vill"][tcode])
    if not vcode:
        return None, "village not matched"
    return (dcode, tcode, vcode), ""


def build_frame(sheet: str, data_dir: str, per_district: bool) -> str:
    df = pd.read_csv(sheet)
    cm = {}
    for col in df.columns:
        cl = str(col).strip().lower()
        if cl == "state": cm["state"] = col
        elif cl == "district": cm["district"] = col
        elif cl == "tehsil": cm["taluka"] = col
        elif cl == "village": cm["village"] = col
        elif cl.startswith("survey no"): cm["survey"] = col
    g = df[df[cm["state"]] == "Gujarat"].copy()
    rows = []
    seen = set()
    for _, r in g.iterrows():
        d = str(r[cm["district"]]).strip()
        if per_district and d in seen:
            continue
        sv = _survey_key(str(r.get(cm.get("survey"), "")).strip())
        if not sv:                                   # need a survey no to fetch VF-7
            continue
        seen.add(d)
        rows.append({"district": d, "taluka": str(r.get(cm.get("taluka"), "")).strip(),
                     "village": str(r[cm["village"]]).strip(), "survey_no": sv,
                     "boja_charge": "", "note": ""})
    out = os.path.join(data_dir, "gj_worklist.csv")
    os.makedirs(data_dir, exist_ok=True)
    pd.DataFrame(rows, columns=WL_COLS).to_csv(out, index=False)
    print(f"frame: {len(rows)} villages -> {out}")
    return out


def run(data_dir: str, limit: int | None, delay: float):
    wl_path = os.path.join(data_dir, "gj_worklist.csv")
    wl = pd.read_csv(wl_path).fillna("")
    todo = wl[wl["boja_charge"].astype(str) == ""]
    if limit:
        todo = todo.head(limit)
    print(f"villages to sample: {len(todo)} (of {len(wl)})")

    c = AnyRoRClient()
    dcache: dict = {}
    cap_path = os.path.join(data_dir, "gj_captcha.png")
    rec_dir = os.path.join(data_dir, "gj_records"); os.makedirs(rec_dir, exist_ok=True)

    for pos, (i, row) in enumerate(todo.iterrows(), 1):
        html, note, charge = "", "", ""
        try:
            loc, why = _resolve(c, row["district"], row["taluka"], row["village"], dcache)
            if not loc:
                note = f"{why}"
            else:
                dcode, tcode, vcode = loc
                surveys = c.survey_numbers(dcode, tcode, vcode)   # sets c._sel, ungated
                svals = {v for v, _ in surveys}
                sv = str(row["survey_no"])
                if sv not in svals:
                    sv = next((v for v in svals if v.split("/")[0] == sv.split("/")[0]), sv)
                c.captcha_image(cap_path)
                cap = input(f"[{pos}/{len(todo)}] {row['village']} — open {cap_path}, "
                            f"type captcha (blank to skip): ").strip()
                if not cap:
                    note = "skipped (no captcha)"
                else:
                    html = c.fetch_record(sv, cap)
                    if any(m in html or m.lower() in html.lower() for m in RECORD_MARKERS):
                        has, hits = boja(html)
                        charge = "Y" if has else "N"
                        note = ",".join(hits)
                        open(os.path.join(rec_dir, f"{row['district']}_{vcode}.html"), "w",
                             encoding="utf-8").write(html)
                    else:
                        note = "no record / bad captcha"
        except Exception as e:  # noqa: BLE001
            note = f"err: {str(e)[:80]}"

        wl.loc[i, ["boja_charge", "note"]] = [charge, note]
        wl.to_csv(wl_path, index=False)
        print(f"[{pos}/{len(todo)}] {row['district']}/{row['village']}: boja={charge or '—'} {note}")
        time.sleep(delay)

    print(f"\ndone -> {wl_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/gj")
    ap.add_argument("--from-sheet", help="build the worklist frame from the SIPI CSV, then exit")
    ap.add_argument("--per-district", action="store_true", help="frame: one village per district")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--delay", type=float, default=1.5)
    a = ap.parse_args()
    if a.from_sheet:
        build_frame(a.from_sheet, a.data_dir, a.per_district)
    else:
        run(a.data_dir, a.limit, a.delay)
