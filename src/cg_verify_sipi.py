"""
Verify the manually-collected SIPI rows for Chhattisgarh against the live Bhuiyan portal.

CG analog of src/verify_sipi.py (MP). Bhuiyan is open (no login/captcha), so this can run
unattended. Geography on Bhuiyan is Devanagari while the SIPI sheet is in English, so district/
tehsil/village are matched by transliterating the portal's Hindi names to Latin (indic-
transliteration) and fuzzy-matching (rapidfuzz) against the sheet.

Per SIPI village it re-derives, objectively, what the khasra record can answer:
  - textual_auto = Y if Bhuiyan renders a real khasra record for the sampled survey no, else N
  - land_type    = abadi (आबादी) / govt (शासकीय) / private-agri (भूमिस्वामी-कृषि) — the tenure
                   class of the sampled record. CG "textual record" is a general khasra record,
                   NOT an abadi-specific one (see docs/chhattisgarh_portal.md), so this column is
                   what distinguishes a true abadi record from ordinary farmland.
  - spatial_auto = Y if the record links a Bhunaksha map (bhunaksha.cg.nic.in) for the khasra
  - joint_auto   = Y if holding is संयुक्त (joint), N if अकेला (single); NA for govt/abadi parcels
  - mutation     = 'Y' — unlike MP, Bhuiyan DOES expose per-khasra mutation status
                   (नामांतरण की वर्तमान स्थिति + registration-deed lookup)

Aggregate-only: owner NAMES are never written — only the Y/N verdicts and the land-type class.

Usage:
  python src/cg_verify_sipi.py --sheet "/path/to/SIPI ... Data collection sheet.csv"
  python src/cg_verify_sipi.py --sheet <csv> --limit 10
Output: data/cg/sipi_cg_verification.csv  (+ a summary printed)
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
    from cg_api import BhuiyanClient
except ImportError:
    from src.cg_api import BhuiyanClient

STATE = "Chhattisgarh"
OUT_COLS = ["district", "tehsil", "village", "survey_no",
            "manual_textual", "auto_textual", "textual_match", "land_type",
            "manual_spatial", "auto_spatial", "spatial_match",
            "auto_mutation",
            "manual_joint", "auto_joint", "joint_match", "note"]

LABELS = {
    "district": "District", "tehsil": "Tehsil", "village": "Village", "survey_no": "Survey no.",
    "manual_textual": "Textual record — sheet", "auto_textual": "Textual record — portal",
    "textual_match": "Textual: match?", "land_type": "Land type — portal",
    "manual_spatial": "Spatial record — sheet", "auto_spatial": "Spatial record — portal",
    "spatial_match": "Spatial: match?",
    "auto_mutation": "Mutation record — portal",
    "manual_joint": "Joint titling — sheet", "auto_joint": "Joint titling — portal",
    "joint_match": "Joint titling: match?", "note": "Note",
}
LABELS_INV = {v: k for k, v in LABELS.items()}


def _canon(s: str) -> str:
    """Fold transliteration variants so Hindi->Latin and English spellings converge:
    z/j, w/v, long->short vowels, anusvara->n, drop h, collapse repeats."""
    s = s.lower()
    s = s.replace("z", "j").replace("w", "v")
    s = re.sub(r"[^a-z]", "", s)
    s = s.replace("aa", "a").replace("ee", "i").replace("oo", "u").replace("au", "o").replace("ai", "e")
    s = s.replace("h", "")
    s = re.sub(r"(.)\1+", r"\1", s)          # collapse doubled letters
    return s


def _lat(dev: str) -> str:
    """Devanagari -> canonical Latin for fuzzy matching against the English sheet."""
    d = str(dev or "").replace("ं", "न").replace("ँ", "न")   # anusvara/chandrabindu -> n
    s = sanscript.transliterate(d, sanscript.DEVANAGARI, sanscript.HK)
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
        elif cl == "tehsil": out["tehsil"] = c
        elif cl == "village": out["village"] = c
    return out


def _best(name_en: str, options: list[tuple[str, str]], cutoff: int = 72):
    """options = [(code, devanagari_text)]; return code of best transliterated fuzzy match."""
    target = _en(name_en)
    if not target or not options:
        return None
    # portal village text is like 'खैरतराई (00005) - 6201017' -> keep the leading name only
    cand = {}
    for code, txt in options:
        base = re.split(r"[\(\-]", txt)[0]
        cand[code] = _lat(base)
    match = process.extractOne(target, cand, scorer=fuzz.WRatio, score_cutoff=cutoff)
    return match[2] if match else None  # (value, score, key) -> key = code


def _khasra_no(survey: str) -> str:
    """SIPI survey cell -> a khasra prefix Bhuiyan's GetFruits accepts (digits / n/1 form)."""
    s = str(survey or "").strip()
    m = re.match(r"\s*(\d+(?:/\d+)?)", s)
    return m.group(1) if m else s


def run(sheet: str, data_dir: str, limit: int | None, delay: float):
    df = pd.read_csv(sheet)
    cmap = _cols(df)
    cg = df[df[cmap["state"]] == STATE].copy()
    if limit:
        cg = cg.head(limit)
    print(f"CG rows to verify: {len(cg)}")

    os.makedirs(data_dir, exist_ok=True)
    out_path = os.path.join(data_dir, "sipi_cg_verification.csv")
    done, results = set(), []
    if os.path.exists(out_path):
        prev = pd.read_csv(out_path).rename(columns=LABELS_INV)
        done = set(zip(prev["district"].astype(str), prev["village"].astype(str),
                       prev["tehsil"].astype(str)))
        results = prev.to_dict("records")

    c = BhuiyanClient(delay=delay)
    districts = c.districts()
    dist_cache: dict = {}

    def _resolve(dist, teh, vil):
        dcode = _best(dist, districts)
        if not dcode:
            return None, "district not matched"
        if dcode not in dist_cache:
            dist_cache[dcode] = {"tehsils": c.tehsils(dcode), "vill": {}}
        tcode = _best(teh, dist_cache[dcode]["tehsils"])
        if not tcode:
            return None, "tehsil not matched"
        vkey = (dcode, tcode)
        if vkey not in dist_cache[dcode]["vill"]:
            dist_cache[dcode]["vill"][vkey] = c.villages(dcode, tcode)
        vcode = _best(vil, dist_cache[dcode]["vill"][vkey])
        if not vcode:
            return None, "village not matched"
        return (dcode, tcode, vcode), ""

    for pos, (_, row) in enumerate(cg.iterrows(), 1):
        dist = str(row[cmap["district"]]).strip()
        teh = str(row.get(cmap.get("tehsil"), "")).strip()
        vil = str(row[cmap["village"]]).strip()
        if (dist, vil, teh) in done:
            continue
        m_text = _yn(row.get(cmap.get("textual")))
        m_spat = _yn(row.get(cmap.get("spatial")))
        m_joint = _yn(row.get(cmap.get("joint")))
        survey = str(row.get(cmap.get("survey"), "")).strip()

        rec = {k: "" for k in OUT_COLS}
        rec.update({"district": dist, "tehsil": teh, "village": vil, "survey_no": survey,
                    "manual_textual": m_text, "manual_spatial": m_spat, "manual_joint": m_joint})
        try:
            loc, why = _resolve(dist, teh, vil)
            if not loc:
                rec["note"] = f"{why} (uncomparable)"
            else:
                dcode, tcode, vcode = loc
                c.select_village(dcode, tcode, vcode)
                ks = c.khasra_list(vcode, _khasra_no(survey)) if survey else []
                if not ks:
                    rec.update({"auto_textual": "N", "note": "no khasra record for sampled survey no"})
                else:
                    r = c.record(ks[0])
                    lt = "abadi" if r["is_abadi"] else ("govt" if r["is_govt"] else "private-agri")
                    ht = r["holding_type"]
                    joint = "NA" if (r["is_govt"] or r["is_abadi"]) else \
                            ("Y" if "संयुक्त" in ht else ("N" if "अकेला" in ht else ""))
                    rec.update({
                        "auto_textual": "Y" if r["tenure"] else "N",
                        "land_type": lt,
                        "auto_spatial": "Y" if r["has_map"] else "N",
                        "auto_mutation": "Y" if r["has_mutation_link"] else "n/a",
                        "auto_joint": joint,
                        "note": "" if not (r["is_govt"] or r["is_abadi"]) else f"{lt}: joint NA",
                    })
        except Exception as e:  # noqa: BLE001
            rec["note"] = f"err (uncomparable): {str(e)[:70]}"

        at, aj, asp = rec["auto_textual"], rec["auto_joint"], rec["auto_spatial"]
        rec["textual_match"] = ("OK" if m_text == at else "MISMATCH") if (m_text in ("Y", "N") and at in ("Y", "N")) else ""
        rec["joint_match"] = ("OK" if m_joint == aj else "MISMATCH") if (m_joint in ("Y", "N") and aj in ("Y", "N")) else ""
        rec["spatial_match"] = ("OK" if m_spat == asp else "MISMATCH") if (m_spat in ("Y", "N") and asp in ("Y", "N")) else ""

        results.append(rec)
        pd.DataFrame(results, columns=OUT_COLS).rename(columns=LABELS).to_csv(out_path, index=False)
        print(f"[{pos}/{len(cg)}] {dist}/{vil}: textual {m_text}->{at or '-'} {rec['textual_match']} "
              f"| land={rec['land_type'] or '-'} | joint {m_joint}->{aj or '-'} {rec['joint_match']} "
              f"{('('+rec['note']+')') if rec['note'] else ''}")
        time.sleep(delay)

    res = pd.DataFrame(results, columns=OUT_COLS)
    tm, jm = res[res["textual_match"] != ""], res[res["joint_match"] != ""]
    unc = res[res["auto_textual"].isin(["", None]) | res["auto_textual"].isna()]
    print(f"\n=== SIPI CG verification ===")
    print(f"rows checked: {len(res)}  |  uncomparable (not matched / error): {len(unc)}")
    print(f"textual: {(tm['textual_match']=='OK').sum()} OK / {(tm['textual_match']=='MISMATCH').sum()} MISMATCH (of {len(tm)})")
    print(f"joint  : {(jm['joint_match']=='OK').sum()} OK / {(jm['joint_match']=='MISMATCH').sum()} MISMATCH (of {len(jm)})")
    lt = res[res["land_type"] != ""]["land_type"].value_counts()
    print(f"land type of sampled records: {lt.to_dict()}")
    print(f"mutation retrievable (portal): {(res['auto_mutation']=='Y').sum()} of {len(res)}")
    print(f"\n-> {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True, help="path to the SIPI data-collection CSV")
    ap.add_argument("--data-dir", default="data/cg")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--delay", type=float, default=1.2)
    a = ap.parse_args()
    run(a.sheet, a.data_dir, a.limit, a.delay)
