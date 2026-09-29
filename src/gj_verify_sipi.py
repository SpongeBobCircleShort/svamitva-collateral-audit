"""
Verify the manually-collected SIPI rows for Gujarat against the live AnyRoR portal.

Gujarat's VF-7 record VIEW is captcha-gated, so this verifier stays on the UNGATED cascade: it
resolves each SIPI village and checks whether a VF-7 textual record EXISTS — i.e. the village has
survey numbers, and whether the researcher's sampled survey no is among them. No captcha needed.

  textual_auto   = Y if the resolved village exposes VF-7 survey numbers (a textual RoR exists), else N
  survey_present = Y if the SIPI-sampled survey no is in that village's VF-7 survey list, else N
  spatial/joint/boja = NOT derivable here — they need the captcha-gated record view (see gj_sampler.py)

Geography on AnyRoR is Gujarati; the sheet is English → transliterate (indic-transliteration,
GUJARATI) + fuzzy match (rapidfuzz), same technique as the CG verifier.

Usage:
  python src/gj_verify_sipi.py --sheet "/path/to/SIPI ... Data collection sheet.csv"
  python src/gj_verify_sipi.py --sheet <csv> --limit 10
Output: data/gj/sipi_gj_verification.csv  (+ a summary printed)
"""
from __future__ import annotations

import os
import re
import time
import argparse
import pandas as pd
from rapidfuzz import fuzz, process
from indic_transliteration import sanscript

try:
    from gj_api import AnyRoRClient
except ImportError:
    from src.gj_api import AnyRoRClient

STATE = "Gujarat"

# AnyRoR district codes with English names (fixed list) — match the English sheet to English names
# directly (reliable), instead of transliterating Gujarati વ↔b etc.
GJ_DISTRICTS = {
    "01": "Kutch", "02": "Banaskantha", "03": "Patan", "04": "Mehsana", "05": "Sabarkantha",
    "06": "Gandhinagar", "07": "Ahmedabad", "08": "Surendranagar", "09": "Rajkot",
    "10": "Jamnagar", "11": "Porbandar", "12": "Junagadh", "13": "Amreli", "14": "Bhavnagar",
    "15": "Anand", "16": "Kheda", "17": "Panchmahal", "18": "Dahod", "19": "Vadodara",
    "20": "Narmada", "21": "Bharuch", "22": "Surat", "23": "Dang", "24": "Navsari",
    "25": "Valsad", "26": "Tapi", "27": "Devbhumi Dwarka", "28": "Morbi", "29": "Gir Somnath",
    "30": "Botad", "31": "Aravalli", "32": "Mahisagar", "33": "Chhota Udaipur", "34": "Vav-Tharad",
}

OUT_COLS = ["district", "taluka", "village", "survey_no",
            "manual_textual", "auto_textual", "textual_match",
            "survey_present", "manual_spatial", "manual_joint", "note"]

LABELS = {
    "district": "District", "taluka": "Taluka", "village": "Village", "survey_no": "Survey no.",
    "manual_textual": "Textual record — sheet", "auto_textual": "Textual record — portal",
    "textual_match": "Textual: match?", "survey_present": "Sampled survey on portal?",
    "manual_spatial": "Spatial record — sheet", "manual_joint": "Joint titling — sheet",
    "note": "Note",
}
LABELS_INV = {v: k for k, v in LABELS.items()}


def _canon(s: str) -> str:
    s = s.lower().replace("z", "j").replace("w", "v")
    s = re.sub(r"[^a-z]", "", s)
    s = s.replace("aa", "a").replace("ee", "i").replace("oo", "u").replace("au", "o").replace("ai", "e")
    s = s.replace("h", "")
    return re.sub(r"(.)\1+", r"\1", s)


def _lat(guj: str) -> str:
    g = str(guj or "").replace("ં", "ન").replace("ઁ", "ન")
    s = sanscript.transliterate(g, sanscript.GUJARATI, sanscript.HK)
    return _canon(s)


def _en(s) -> str:
    return _canon(str(s or ""))


def _yn(v) -> str:
    s = str(v or "").strip().upper()
    if not s or s == "NAN":
        return ""
    if s.startswith("NA"):
        return "NA"
    return s[0] if s[0] in ("Y", "N") else ""


def _cols(df: pd.DataFrame) -> dict:
    out = {}
    for c in df.columns:
        cl = re.sub(r"\s+", " ", str(c).strip().lower())
        if "existence of textual" in cl: out["textual"] = c
        elif "existence of spatial" in cl: out["spatial"] = c
        elif "joint-titling" in cl or "joint titling" in cl: out["joint"] = c
        elif cl.startswith("survey no"): out["survey"] = c
        elif cl == "state": out["state"] = c
        elif cl == "district": out["district"] = c
        elif cl == "tehsil": out["taluka"] = c
        elif cl == "village": out["village"] = c
    return out


def _best(name_en: str, options: list[tuple[str, str]], cutoff: int = 72):
    target = _en(name_en)
    if not target or not options:
        return None
    cand = {}
    for code, txt in options:
        base = re.split(r"[\(\-]", txt)[0]     # 'અસલાલી - 003' -> 'અસલાલી'
        cand[code] = _lat(base)
    m = process.extractOne(target, cand, scorer=fuzz.WRatio, score_cutoff=cutoff)
    return m[2] if m else None


def _survey_key(cell: str) -> str:
    """SIPI GJ survey cell ('SV350', '200150', 'NA19/1/1/Pack 4/50') -> a comparable survey token."""
    s = str(cell or "").strip()
    s = re.sub(r"(?i)^sv", "", s).strip()
    m = re.match(r"\s*(\d+(?:/\S+)?)", s)
    return m.group(1) if m else ""


def run(sheet: str, data_dir: str, limit: int | None, delay: float):
    df = pd.read_csv(sheet)
    cmap = _cols(df)
    gj = df[df[cmap["state"]] == STATE].copy()
    if limit:
        gj = gj.head(limit)
    print(f"GJ rows to verify: {len(gj)}")

    os.makedirs(data_dir, exist_ok=True)
    out_path = os.path.join(data_dir, "sipi_gj_verification.csv")
    done, results = set(), []
    if os.path.exists(out_path):
        prev = pd.read_csv(out_path).rename(columns=LABELS_INV)
        done = set(zip(prev["district"].astype(str), prev["village"].astype(str),
                       prev["taluka"].astype(str)))
        results = prev.to_dict("records")

    c = AnyRoRClient()
    districts = c.districts()
    dcache: dict = {}

    dist_en = list(GJ_DISTRICTS.items())   # [(code, english_name)]

    def _resolve(dist, tal, vil):
        # district: match English sheet name against the English district list (reliable)
        tgt = _en(dist)
        cand = {code: _en(nm) for code, nm in dist_en}
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

    for pos, (_, row) in enumerate(gj.iterrows(), 1):
        dist = str(row[cmap["district"]]).strip()
        tal = str(row.get(cmap.get("taluka"), "")).strip()
        vil = str(row[cmap["village"]]).strip()
        if (dist, vil, tal) in done:
            continue
        m_text = _yn(row.get(cmap.get("textual")))
        survey = str(row.get(cmap.get("survey"), "")).strip()

        rec = {k: "" for k in OUT_COLS}
        rec.update({"district": dist, "taluka": tal, "village": vil, "survey_no": survey,
                    "manual_textual": m_text,
                    "manual_spatial": _yn(row.get(cmap.get("spatial"))),
                    "manual_joint": _yn(row.get(cmap.get("joint")))})
        try:
            loc, why = _resolve(dist, tal, vil)
            if not loc:
                rec["note"] = f"{why} (uncomparable)"
            else:
                dcode, tcode, vcode = loc
                surveys = c.survey_numbers(dcode, tcode, vcode)
                svals = {v for v, _ in surveys}
                rec["auto_textual"] = "Y" if surveys else "N"
                key = _survey_key(survey)
                rec["survey_present"] = ("Y" if (key and key in svals) else "N") if surveys else ""
                if not surveys:
                    rec["note"] = "village resolved but no VF-7 survey numbers"
        except Exception as e:  # noqa: BLE001
            rec["note"] = f"err (uncomparable): {str(e)[:70]}"

        at = rec["auto_textual"]
        rec["textual_match"] = ("OK" if m_text == at else "MISMATCH") if (m_text in ("Y", "N") and at in ("Y", "N")) else ""
        results.append(rec)
        pd.DataFrame(results, columns=OUT_COLS).rename(columns=LABELS).to_csv(out_path, index=False)
        print(f"[{pos}/{len(gj)}] {dist}/{vil}: textual {m_text}->{at or '-'} {rec['textual_match']} "
              f"| sampled survey present={rec['survey_present'] or '-'} "
              f"{('('+rec['note']+')') if rec['note'] else ''}")
        time.sleep(delay)

    res = pd.DataFrame(results, columns=OUT_COLS)
    tm = res[res["textual_match"] != ""]
    unc = res[res["auto_textual"].isin(["", None]) | res["auto_textual"].isna()]
    print(f"\n=== SIPI GJ verification (ungated: textual existence) ===")
    print(f"rows checked: {len(res)}  |  uncomparable (not matched / error): {len(unc)}")
    print(f"textual: {(tm['textual_match']=='OK').sum()} OK / {(tm['textual_match']=='MISMATCH').sum()} MISMATCH (of {len(tm)})")
    sp = res[res["survey_present"] != ""]
    print(f"sampled survey present on portal: {(sp['survey_present']=='Y').sum()} / {len(sp)}")
    print(f"\n-> {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True, help="path to the SIPI data-collection CSV")
    ap.add_argument("--data-dir", default="data/gj")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--delay", type=float, default=1.0)
    a = ap.parse_args()
    run(a.sheet, a.data_dir, a.limit, a.delay)
