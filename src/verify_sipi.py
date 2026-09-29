"""
Verify the manually-collected SIPI rows for Madhya Pradesh against the live webgis2 portal.
RUN ON YOUR MACHINE (RoR fetch is PII-gated for the assistant).

The SIPI sheet records, per village, three Y/N calls made by a human researcher:
  - textual rural-habitation record exists (col: "Existence of textual ...")
  - spatial rural-habitation record exists (col: "Existence of spatial ...")
  - joint-titling on the selected record (Y/N/NA)
plus the survey no selected and a govt-land remark.

This re-derives the two that the abadi RoR API can answer objectively and flags disagreements:
  - textual_auto  = Y if the abadi RoR (ror_html) renders a real record for a sampled plot, else N
  - joint_auto    = Y if the selected record has >1 distinct owner (co-titling); NA if govt land; else N
Spatial existence needs the map endpoint (not in the abadi RoR API) -> left blank, noted.

Selection mirrors the sheet's rule: prefer the plot whose khasra matches the recorded survey no;
otherwise the 50th plot in the series (or the last if fewer). One record fetched per village.
Aggregate-only: owner NAMES are never written — only a count and the Y/N verdicts.

Usage:
  python src/verify_sipi.py --sheet "/path/to/SIPI ... Data collection sheet.csv"
  python src/verify_sipi.py --sheet <csv> --limit 10     # smoke test
Output: data/sipi_mp_verification.csv  (+ a mismatch summary printed)
"""
from __future__ import annotations

import os
import re
import time
import argparse
import pandas as pd

try:
    from bhulekh_api import BhulekhClient
except ImportError:
    from src.bhulekh_api import BhulekhClient

STATE = "Madhya Pradesh"
OUT_COLS = ["district", "tehsil", "village", "survey_no",
            "manual_textual", "auto_textual", "textual_match",
            "manual_joint", "auto_joint", "joint_match",
            "manual_spatial", "owners_on_record", "govt_land", "note"]


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _yn(v) -> str:
    """Normalise a manual cell to Y / N / NA / '' ."""
    s = str(v or "").strip().upper()
    if not s or s == "NAN":
        return ""
    if s.startswith("NA"):
        return "NA"
    return s[0] if s[0] in ("Y", "N") else ""


def _cols(df: pd.DataFrame) -> dict:
    """Map the long SIPI header cells to short keys by substring."""
    out = {}
    for c in df.columns:
        cl = _norm(c)
        if "existence of textual" in cl: out["textual"] = c
        elif "existence of spatial" in cl: out["spatial"] = c
        elif "joint-titling" in cl or "joint titling" in cl: out["joint"] = c
        elif cl.startswith("survey no"): out["survey"] = c
        elif cl == "state": out["state"] = c
        elif cl == "district": out["district"] = c
        elif cl == "tehsil": out["tehsil"] = c
        elif cl == "village": out["village"] = c
    return out


def _district_index(client: BhulekhClient, district_en: str, cache: dict) -> dict:
    """{ (tehsil_norm, village_norm): v, village_norm: [v,...] } for one district."""
    if district_en in cache:
        return cache[district_en]
    dn = _norm(district_en).replace("-", " ")
    d = next((x for x in client.districts()
              if _norm(x["district_name"]).replace("-", " ") == dn), None)
    by_pair, by_vil = {}, {}
    if d:
        for t in client.tehsils(d["district_id"]):
            tn = _norm(t["tehsil_name"])
            for v in client.villages(d["district_id"], t["tehsil_id"]):
                rec = (v["ror_district_id"], v["ror_tehsil_id"], str(v["lgd_code"]))
                by_pair[(tn, _norm(v.get("village_name")))] = rec
                by_vil.setdefault(_norm(v.get("village_name")), []).append(rec)
    idx = {"pair": by_pair, "vil": by_vil, "found": bool(d)}
    cache[district_en] = idx
    return idx


def _pick_plot(plots: list, survey_no: str):
    """Mirror the sheet's selection rule. The recorded survey no is '<Nth>-<khasra>'
    (e.g. '50-208' = the 50th record in the series, khasra 208), so pick the Nth plot;
    fall back to the 50th, or the last if the series is shorter."""
    m = re.match(r"\s*(\d+)", str(survey_no or ""))
    n = int(m.group(1)) if m else 50
    return plots[min(n - 1, len(plots) - 1)]


def _joint_and_owners(rows: list) -> tuple[str, int, bool]:
    """(joint Y/N/NA, distinct owner count, govt?) from ror_detail owner_detail rows."""
    names = set()
    govt = False
    shares = set()
    for r in rows:
        nm = " ".join(str(r.get(k) or "") for k in
                      ("owner_first_name", "owner_middle_name", "owner_last_name")).strip()
        if nm:
            names.add(nm)
        if "government" in str(r.get("land_type_en") or "").lower() \
           or "shaskiya" in str(r.get("ownership_name_en") or "").lower() \
           or "शासन" in nm:
            govt = True
        shares.add(str(r.get("owner_share") or "").strip())
    if govt and not names - {"मध्य प्रदेश शासन"}:
        return "NA", len(names), True
    if len(names) > 1:
        return "Y", len(names), govt
    # single owner but a fractional share implies co-holders on the khata
    frac = any(s and s not in ("1/1", "1", "") for s in shares)
    return ("Y" if frac else "N"), len(names), govt


def run(sheet: str, data_dir: str, limit: int | None, delay: float):
    df = pd.read_csv(sheet)
    cmap = _cols(df)
    mp = df[df[cmap["state"]] == STATE].copy()
    if limit:
        mp = mp.head(limit)
    print(f"MP rows to verify: {len(mp)}")

    out_path = os.path.join(data_dir, "sipi_mp_verification.csv")
    done = set()
    if os.path.exists(out_path):
        prev = pd.read_csv(out_path)
        done = set(zip(prev["district"].astype(str), prev["village"].astype(str),
                       prev["tehsil"].astype(str)))
        results = prev.to_dict("records")
    else:
        results = []

    client = BhulekhClient(timeout=45)
    cache: dict = {}

    def _retry(fn, tries=3):
        last = None
        for i in range(tries):
            try:
                return fn()
            except Exception as e:  # noqa: BLE001
                last = e
                if "No record found" in str(e) or "120001" in str(e):
                    raise                       # definitive, don't retry
                time.sleep(1.5 * (i + 1))
        raise last

    for pos, (_, row) in enumerate(mp.iterrows(), 1):
        dist = str(row[cmap["district"]]).strip()
        teh = str(row.get(cmap.get("tehsil"), "")).strip()
        vil = str(row[cmap["village"]]).strip()
        if (dist, vil, teh) in done:
            continue
        m_text = _yn(row.get(cmap.get("textual")))
        m_spat = _yn(row.get(cmap.get("spatial")))
        m_joint = _yn(row.get(cmap.get("joint")))
        survey = str(row.get(cmap.get("survey"), "")).strip()

        rec = {c: "" for c in OUT_COLS}
        rec.update({"district": dist, "tehsil": teh, "village": vil, "survey_no": survey,
                    "manual_textual": m_text, "manual_joint": m_joint, "manual_spatial": m_spat})

        try:
            idx = _district_index(client, dist, cache)
            v = idx["pair"].get((_norm(teh), _norm(vil)))
            if not v:
                cands = idx["vil"].get(_norm(vil), [])
                v = cands[0] if cands else None
            if not v:
                # resolver failure — cannot verify; NOT a portal 'no record'
                rec["note"] = "village not resolved on webgis2 (uncomparable)"
            else:
                rdid, rtid, lgd = v
                plots = _retry(lambda: client.plots(rdid, rtid, lgd))
                if not plots:
                    rec.update({"auto_textual": "N", "note": "portal: no abadi plots for village"})
                else:
                    p = _pick_plot(plots, survey)
                    try:
                        det = _retry(lambda: client.ror_detail(
                            rdid, rtid, lgd, p.get("clr_plot_no"), p["property_id"], "PLOT"))
                    except Exception as e:  # noqa: BLE001
                        if "No record found" in str(e) or "120001" in str(e):
                            rec.update({"auto_textual": "N", "note": "portal: no record for sampled plot"})
                            det = None
                        else:
                            raise
                    if det is not None:
                        d = det.get("data", {}) if isinstance(det, dict) else {}
                        rows = d.get("owner_detail") or d.get("land_detail") or []
                        if not rows:
                            rec.update({"auto_textual": "N", "note": "portal: empty record"})
                        else:
                            r0 = rows[0]
                            html = _retry(lambda: client.ror_html(
                                rdid, rtid, lgd, p.get("clr_plot_no"), p["property_id"],
                                r0.get("khasra_no"), r0.get("owner_samagra_id"),
                                r0.get("loc_id"), "PLOT"))
                            textual = "Y" if ("विल्लंगम" in html or "प्ररूप" in html
                                              or "भूमिस्वामी" in html) else "N"
                            joint, nowners, govt = _joint_and_owners(rows)
                            rec.update({"auto_textual": textual, "auto_joint": joint,
                                        "owners_on_record": nowners,
                                        "govt_land": "Y" if govt else "N",
                                        "note": "govt plot — joint NA" if govt else ""})
        except Exception as e:  # noqa: BLE001
            rec["note"] = f"err (uncomparable): {str(e)[:70]}"

        # compare only definitive Y/N on both sides; NA / blank / errors are not mismatches
        at, aj = rec["auto_textual"], rec["auto_joint"]
        rec["textual_match"] = ("OK" if m_text == at else "MISMATCH") \
            if (m_text in ("Y", "N") and at in ("Y", "N")) else ""
        rec["joint_match"] = ("OK" if m_joint == aj else "MISMATCH") \
            if (m_joint in ("Y", "N") and aj in ("Y", "N")) else ""

        results.append(rec)
        pd.DataFrame(results, columns=OUT_COLS).to_csv(out_path, index=False)
        print(f"[{pos}/{len(mp)}] {dist}/{vil}: textual {m_text}->{rec['auto_textual']} "
              f"{rec['textual_match']} | joint {m_joint}->{rec['auto_joint']} {rec['joint_match']}"
              f"  {('('+rec['note']+')') if rec['note'] else ''}")
        time.sleep(delay)

    # summary
    res = pd.DataFrame(results, columns=OUT_COLS)
    tm = res[res["textual_match"] != ""]
    jm = res[res["joint_match"] != ""]
    uncomparable = res[res["auto_textual"].isin(["", None]) | res["auto_textual"].isna()]
    print(f"\n=== SIPI MP verification ===")
    print(f"rows checked: {len(res)}  |  uncomparable (not resolved / timeout / error): {len(uncomparable)}")
    print(f"textual: {(tm['textual_match']=='OK').sum()} OK / {(tm['textual_match']=='MISMATCH').sum()} MISMATCH "
          f"(of {len(tm)} comparable)")
    print(f"joint  : {(jm['joint_match']=='OK').sum()} OK / {(jm['joint_match']=='MISMATCH').sum()} MISMATCH "
          f"(of {len(jm)} comparable)")
    print(f"govt-land plots sampled (joint = NA): {(res['govt_land']=='Y').sum()}")
    mism = res[(res["textual_match"] == "MISMATCH") | (res["joint_match"] == "MISMATCH")]
    if len(mism):
        print(f"\nmismatches ({len(mism)}):")
        print(mism[["district", "village", "manual_textual", "auto_textual",
                    "manual_joint", "auto_joint"]].to_string(index=False))
    print(f"\n-> {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True, help="path to the SIPI data-collection CSV")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--delay", type=float, default=1.0)
    a = ap.parse_args()
    run(a.sheet, a.data_dir, a.limit, a.delay)
