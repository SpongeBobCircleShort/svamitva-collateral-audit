"""
Maharashtra Property Card collateral sampler — ASSISTED / USER-RUN, EXPERIMENTAL (the record view
is mobile+captcha gated). For each gaothan village in the frame it fetches a Property Card and
reads the इतर हक्क (Other Rights) section for a charge (बोजा/कर्ज/बंधक) — the MH analog of MP col 11.

Throughput trick — session reuse: it FIRST tries each view on the existing session with no captcha.
Only if the portal demands one does it prompt you to read the captcha off data/maha_captcha.png.
If the portal keeps a session after one solve, you solve ~one captcha for the whole frame; if not,
you solve one per view. Either way it is bounded (one record per district).

You supply your mobile once (env MAHA_MOBILE or prompt). This code never solves the captcha — it
saves the captcha image and you type the value.

Usage:
  MAHA_MOBILE=98XXXXXXXX python src/maha_sampler.py            # whole frame
  MAHA_MOBILE=98XXXXXXXX python src/maha_sampler.py --limit 3  # smoke test
Reads/writes data/maha_pc_worklist.csv (from maha_frame.py). Resumable.
"""
from __future__ import annotations

import os
import time
import base64
import argparse
import pandas as pd

try:
    from maha_api import MahabhulekhClient, other_rights, DISTRICTS, PFX, BASE
except ImportError:
    from src.maha_api import MahabhulekhClient, other_rights, DISTRICTS, PFX, BASE

def _digits(v) -> str:
    """CSV numeric cells read back as floats ('102.0'); keep them as clean integer strings."""
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return "" if s in ("", "nan") else s


CAPTCHA_MARKERS = ("captcha", "कॅप्चा", "कैप्चा", "invalid captcha", "verification")
# markers seen on a real rendered Property Card (transliterated-English + Marathi)
RECORD_MARKERS = ("property card", "other encumbrances", "name of the holder", "मालमत्ता पत्रक",
                  "इतर बोजा", "encumbrances/rights", "भूमापन", "खातेदार")


def _needs_captcha(html: str) -> bool:
    low = html.lower()
    if any(m in html or m.lower() in low for m in RECORD_MARKERS):
        return False
    return any(m in low for m in CAPTCHA_MARKERS)


def _is_error(html: str) -> bool:
    """ASP.NET async error delta (e.g. '0|error|500||') or an empty/near-empty response."""
    return (not html) or len(html) < 60 or "|error|" in html[:40]


def run(data_dir: str, mobile: str, limit: int | None, pc_no: str, delay: float):
    wl_path = os.path.join(data_dir, "maha_pc_worklist.csv")
    wl = pd.read_csv(wl_path).fillna("")
    todo = wl[(wl["village"].astype(str) != "") & (wl["other_rights_charge"].astype(str) == "")]
    if limit:
        todo = todo.head(limit)
    print(f"villages to sample: {len(todo)} (of {len(wl)})")

    c = MahabhulekhClient()
    rec_dir = os.path.join(data_dir, "maha_records"); os.makedirs(rec_dir, exist_ok=True)
    cap_path = os.path.join(data_dir, "maha_captcha.png")
    for pos, (i, row) in enumerate(todo.iterrows(), 1):
        code = DISTRICTS.get(row["district"], "")
        office, vill = _digits(row["office_code"]), _digits(row["village_code"])
        number = _digits(row["pc_no"]) or str(pc_no)
        html, note = "", ""
        for attempt in range(3):
            try:
                c.prepare_record(code, office, vill, number, "property_card")
                c.captcha_image(cap_path)               # this session's captcha, for you to read
                cap = input(f"[{pos}/{len(todo)}] {row['village']} — open {cap_path}, "
                            f"type captcha (blank to skip): ").strip()
                if not cap:
                    note = "skipped (no captcha)"; break
                html = c.submit_record(number, mobile, cap)
            except Exception as e:  # noqa: BLE001
                note = f"err: {str(e)[:80]}"; continue
            if _is_error(html) or _needs_captcha(html):
                print("   -> error/invalid captcha, retrying…"); note = "error/invalid captcha"; continue
            note = ""; break                            # got a real record
        if html and not _is_error(html):
            open(os.path.join(rec_dir, f"{row['district']}_{vill}.html"), "w",
                 encoding="utf-8").write(html)
        has, hits = other_rights(html) if (html and not _is_error(html)) else (False, [])
        charge = ("Y" if has else "N") if (html and not _is_error(html)) else ""
        wl.loc[i, ["pc_no", "other_rights_charge", "note"]] = [number, charge, ",".join(hits) or note]
        wl.to_csv(wl_path, index=False)               # checkpoint
        print(f"[{pos}/{len(todo)}] {row['district']}/{row['village']}: charge={charge or '—'} {hits} {note}")
        time.sleep(delay)

    print(f"\ndone -> {wl_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--mobile", default=os.environ.get("MAHA_MOBILE", ""))
    ap.add_argument("--pc-no", default="1", help="gaothan PC/survey number to try (default 1)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--delay", type=float, default=2.0)
    a = ap.parse_args()
    if not a.mobile:
        a.mobile = input("your mobile number (for the portal gate): ").strip()
    run(a.data_dir, a.mobile, a.limit, a.pc_no, a.delay)
