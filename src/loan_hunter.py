"""
Loan hunter — a targeted search for at least ONE encumbered abadi parcel (a positive
control). RUN ON YOUR MACHINE (webgis2 reachable there; RoR fetch is PII-gated for the
assistant).

Why this and not more of the one-per-district frame: random rural abadi encumbrance is
~0, so brute force won't surface a charge. This instead sweeps where a mortgage is most
likely — the LARGEST abadi settlements first (most parcels, highest land value, oldest
title) — reads EVERY plot in each village (no per-village cap), and logs the raw col-11
(भूमि पर विल्लंगम तथा प्रभार) cell text of every parcel to data/col11_audit.csv. It stops
loudly on the first non-empty col-11 it sees — a charge, दृष्टिबंधक, प्रक्रियाधीन, a court
note, anything — which is the positive control proving the free RoR view does render col 11.

No owner PII is stored — only the encumbrance-column text and location keys.

Usage:
  python src/loan_hunter.py                       # top 80 largest villages statewide
  python src/loan_hunter.py --villages 300        # widen the net
  python src/loan_hunter.py --districts INDORE,BHOPAL,UJJAIN   # focus districts
  python src/loan_hunter.py --target-hits 3       # keep going past the first hit
"""
from __future__ import annotations

import os
import time
import argparse
import pandas as pd

try:
    from bhulekh_api import BhulekhClient
    from ror_sampler import _village_index, _norm, col11_values, _is_charge, SEARCH_TYPE
except ImportError:
    from src.bhulekh_api import BhulekhClient
    from src.ror_sampler import _village_index, _norm, col11_values, _is_charge, SEARCH_TYPE

AUDIT_COLS = ["district_en", "village_en", "lgd", "clr_plot_no", "parcel_serial",
              "col11_text", "has_charge"]


def _candidates(data_dir: str, districts: list[str] | None, n: int,
                village: str | None = None) -> pd.DataFrame:
    """Largest abadi settlements first (by cards issued). Optionally restricted to
    the named districts and/or a village-name substring. One row per census village."""
    cards = pd.read_parquet(os.path.join(data_dir, "svamitva_cards.parquet"))
    cards = cards.copy()
    cards["cards_distributed"] = pd.to_numeric(cards["cards_distributed"], errors="coerce").fillna(0)
    if districts:
        want = {_norm(d) for d in districts}
        cards = cards[cards["district_en"].map(lambda x: _norm(x) in want)]
    if village:
        vq = _norm(village)
        vcol = "village_en" if "village_en" in cards.columns else \
            next(c for c in cards.columns if "village" in c)
        cards = cards[cards[vcol].astype(str).map(lambda x: vq in _norm(x))]
    cards = cards.sort_values("cards_distributed", ascending=False)
    return cards.head(n)


def _owner_name(r0: dict) -> str:
    """First owner label present in a ror-detail row. Printed transiently for matching a
    known beneficiary; NEVER written to the audit file."""
    for k in ("owner_name", "owner_name_ll", "name", "name_ll", "khatedar_name", "owner"):
        v = r0.get(k)
        if v:
            return str(v)
    return ""


def _seen(audit_path: str) -> set:
    if not os.path.exists(audit_path):
        return set()
    a = pd.read_csv(audit_path)
    return set(zip(a["lgd"].astype(str), a["clr_plot_no"].astype(str)))


def hunt(data_dir: str, districts, villages: int, plots_per_village: int | None,
         delay: float, target_hits: int, village: str | None = None,
         show_owner: bool = False) -> None:
    audit_path = os.path.join(data_dir, "col11_audit.csv")
    cand = _candidates(data_dir, districts, villages, village)
    print(f"candidate villages (largest-first): {len(cand)}  "
          f"| audit -> {audit_path}  | target hits: {target_hits}")

    client = BhulekhClient()
    cache: dict = {}
    seen = _seen(audit_path)
    hits = checked = 0
    if not os.path.exists(audit_path):
        pd.DataFrame(columns=AUDIT_COLS).to_csv(audit_path, index=False)

    for pos, (_, v) in enumerate(cand.iterrows(), 1):
        dname = str(v["district_en"])
        vname = str(v.get("village_en") or v.get("village_hi") or "")
        idx = _village_index(client, dname, cache)
        val = idx["by_lgd"].get(str(v["lgd_village_code"])) or idx["by_name"].get(_norm(vname))
        if not val:
            print(f"[{pos}/{len(cand)}] {dname}/{vname}: not on webgis2"); continue
        rdid, rtid, lgd = val
        try:
            plots = client.plots(rdid, rtid, lgd)
        except Exception as e:  # noqa: BLE001
            print(f"[{pos}/{len(cand)}] {dname}/{vname}: plot err {str(e)[:80]}"); continue
        if plots_per_village:
            plots = plots[:plots_per_village]

        rows, vchecked, vcharge = [], 0, 0
        for p in plots:
            plot_no = p.get("clr_plot_no") or p.get("clr_plot_no_display")
            if (str(lgd), str(plot_no)) in seen:
                continue
            try:
                det = client.ror_detail(rdid, rtid, lgd, plot_no, p["property_id"], SEARCH_TYPE)
                d = det.get("data", {}) if isinstance(det, dict) else {}
                base = d.get("owner_detail") or d.get("land_detail") or []
                if not base:
                    continue
                r0 = base[0]
                html = client.ror_html(rdid, rtid, lgd, plot_no, p["property_id"],
                                        r0.get("khasra_no"), r0.get("owner_samagra_id"),
                                        r0.get("loc_id"), SEARCH_TYPE)
            except Exception:  # noqa: BLE001
                continue
            vals, _note = col11_values(html)
            if show_owner:
                oname = _owner_name(r0)
                print(f"      plot {plot_no}: owner={oname!r}  col11={vals}")
            for serial, cell in enumerate(vals, 1):
                charged = _is_charge(cell)
                rows.append([dname, vname, lgd, plot_no, serial, cell, int(charged)])
                vchecked += 1
                if charged:
                    vcharge += 1
                    print("\n*** CHARGE FOUND ***")
                    print(f"    district : {dname}")
                    print(f"    village  : {vname}  (lgd {lgd})")
                    print(f"    plot     : {plot_no}  parcel #{serial}")
                    print(f"    col-11   : {cell!r}\n")
            seen.add((str(lgd), str(plot_no)))
            time.sleep(delay)

        if rows:
            pd.DataFrame(rows, columns=AUDIT_COLS).to_csv(
                audit_path, mode="a", header=False, index=False)
        checked += vchecked
        hits += vcharge
        print(f"[{pos}/{len(cand)}] {dname}/{vname}: {vcharge} charge / {vchecked} parcels"
              f"  (running: {hits} charge / {checked} parcels)")
        if hits >= target_hits:
            print(f"\nreached {hits} charge(s) — stopping. audit -> {audit_path}")
            return

    # summary of what col 11 ever contained
    a = pd.read_csv(audit_path)
    nonblank = a[a["has_charge"] == 1]
    print(f"\nswept {len(a):,} parcels across {a['lgd'].nunique()} villages; "
          f"{len(nonblank)} with a non-blank col 11.")
    if nonblank.empty:
        distinct = sorted(set(a["col11_text"].dropna().astype(str)))
        print("col-11 was blank on EVERY parcel. Distinct raw values seen:", distinct[:10])
        print("If this holds at scale, the free RoR view likely does not render col 11 — "
              "the zero encumbrance rate is then a view limitation, not a proven absence.")
    else:
        print(nonblank[["district_en", "village_en", "clr_plot_no", "col11_text"]].to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--districts", default=None, help="comma-separated district_en names to focus")
    ap.add_argument("--villages", type=int, default=80, help="how many largest villages to sweep")
    ap.add_argument("--plots-per-village", type=int, default=None, help="cap plots/village (default: all)")
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--target-hits", type=int, default=1, help="stop after this many charged parcels")
    ap.add_argument("--village", default=None, help="focus a village-name substring (e.g. Handia)")
    ap.add_argument("--show-owner", action="store_true",
                    help="print owner name + col-11 per parcel to match a known beneficiary (not stored)")
    a = ap.parse_args()
    dists = [d.strip() for d in a.districts.split(",")] if a.districts else None
    hunt(a.data_dir, dists, a.villages, a.plots_per_village, a.delay, a.target_hits,
         a.village, a.show_owner)
