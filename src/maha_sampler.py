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
RECORD_MARKERS = ("इतर हक्क", "other rights", "भूमापन", "मिळकत", "भूधारणा", "खातेदार")


def _needs_captcha(html: str) -> bool:
    low = html.lower()
    if any(m in html or m.lower() in low for m in RECORD_MARKERS):
        return False
    return any(m in low for m in CAPTCHA_MARKERS)


def _save_captcha(client: MahabhulekhClient, data_dir: str) -> str:
    """Save the current captcha image for the user to read. Returns the path or ''."""
    try:
        r = client.s.get(BASE + "Images/ZC9Y.gif", timeout=client.timeout)
        p = os.path.join(data_dir, "maha_captcha.png")
        open(p, "wb").write(r.content)
        return p
    except Exception:  # noqa: BLE001
        return ""


def run(data_dir: str, mobile: str, limit: int | None, pc_no: str, delay: float):
    wl_path = os.path.join(data_dir, "maha_pc_worklist.csv")
    wl = pd.read_csv(wl_path).fillna("")
    todo = wl[(wl["village"].astype(str) != "") & (wl["other_rights_charge"].astype(str) == "")]
    if limit:
        todo = todo.head(limit)
    print(f"villages to sample: {len(todo)} (of {len(wl)})")

    c = MahabhulekhClient()
    for pos, (i, row) in enumerate(todo.iterrows(), 1):
        dist, code = row["district"], DISTRICTS.get(row["district"], "")
        office, vill = _digits(row["office_code"]), _digits(row["village_code"])
        number = _digits(row["pc_no"]) or str(pc_no)
        captcha = ""
        html = ""
        for attempt in range(3):
            try:
                html = c.fetch_record(code, office, vill, number, mobile, captcha, "property_card")
            except Exception as e:  # noqa: BLE001
                wl.loc[i, "note"] = f"fetch err: {str(e)[:80]}"; break
            if not _needs_captcha(html):
                break                                   # success (session carried or captcha ok)
            path = _save_captcha(c, data_dir)           # portal wants a captcha
            captcha = input(f"[{pos}/{len(todo)}] {row['village']}: type captcha from {path}: ").strip()
        # dump the raw response so the result can be verified (real record vs error/captcha page)
        rec_dir = os.path.join(data_dir, "maha_records"); os.makedirs(rec_dir, exist_ok=True)
        if html:
            open(os.path.join(rec_dir, f"{row['district']}_{vill}.html"), "w",
                 encoding="utf-8").write(html)
        has, hits = other_rights(html)
        wl.loc[i, ["pc_no", "other_rights_charge", "note"]] = [
            number, ("Y" if has else "N"), (",".join(hits) if hits else "")]
        wl.to_csv(wl_path, index=False)               # checkpoint
        print(f"[{pos}/{len(todo)}] {row['district']}/{row['village']}: charge={'Y' if has else 'N'} {hits}")
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
