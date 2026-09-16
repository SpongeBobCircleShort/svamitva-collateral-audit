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
    """Owner label from a ror-detail row (owner_first/middle/last). Printed transiently for
    matching a known beneficiary; NEVER written to the audit file."""
    parts = [r0.get("owner_first_name"), r0.get("owner_middle_name"), r0.get("owner_last_name")]
    return " ".join(str(p) for p in parts if p).strip()


def _is_govt(r0: dict) -> bool:
    """True for state/institutional parcels (never mortgageable) — excluded from the
    private-abadi denominator."""
    lt = str(r0.get("land_type_en") or "").lower()
    ot = str(r0.get("ownership_name_en") or "").lower()
    name = str(r0.get("owner_first_name") or "")
    return ("government" in lt or "shaskiya" in ot or "शासन" in name
            or "शासकीय" in str(r0.get("ownership_name_ll") or ""))


def _seen(audit_path: str) -> set:
    if not os.path.exists(audit_path):
        return set()
    a = pd.read_csv(audit_path)
    return set(zip(a["lgd"].astype(str), a["clr_plot_no"].astype(str)))


def hunt(data_dir: str, districts, villages: int, plots_per_village: int | None,
         delay: float, target_hits: int, village: str | None = None,
         show_owner: bool = False, debug: bool = False) -> None:
    import json as _json
    dumped = {"done": False}
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
        if dname not in cache:
            print(f"  building {dname} village index...", flush=True)
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
        print(f"[{pos}/{len(cand)}] {dname}/{vname} (lgd {lgd}): sweeping {len(plots)} plots...",
              flush=True)

        rows, vchecked, vcharge = [], 0, 0
        for pi, p in enumerate(plots, 1):
            plot_no = p.get("clr_plot_no") or p.get("clr_plot_no_display")
            if (str(lgd), str(plot_no)) in seen and not (debug and not dumped["done"]):
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
            if debug and not dumped["done"]:
                dumped["done"] = True
                hp = os.path.join(data_dir, "ror_debug.html")
                open(hp, "w", encoding="utf-8").write(html)
                print("\n=== DEBUG: first parcel ===")
                print("ror-detail data keys:", list(d.keys()))
                print("owner_detail[0] keys:", list(base[0].keys()))
                print("owner_detail[0] json:", _json.dumps(base[0], ensure_ascii=False)[:1200])
                if d.get("land_detail"):
                    print("land_detail[0] json:", _json.dumps(d["land_detail"][0], ensure_ascii=False)[:1200])
                print("col11_values parsed:", vals, "note:", _note)
                print(f"raw HTML saved -> {hp}  (inspect col 11 by hand)")
                print("=== END DEBUG ===\n")
            govt = _is_govt(base[0])
            if show_owner:
                oname = _owner_name(base[0])
                tag = " [GOVT]" if govt else ""
                print(f"      plot {plot_no}: owner={oname!r}{tag}  col11={vals}")
            if govt:
                seen.add((str(lgd), str(plot_no)))
                continue                       # state/institutional land can't be mortgaged
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
            if vchecked and vchecked % 15 == 0:
                print(f"      ...{pi}/{len(plots)} plots, {vcharge} charge so far", flush=True)
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
        print("col-11 was blank on every parcel. NOTE: these are RANDOM parcels, so 0 is also "
              "exactly what a genuine near-zero encumbrance rate looks like — this run alone "
              "does NOT show the view suppresses col 11. Only a parcel independently KNOWN to be "
              "mortgaged can distinguish 'genuinely unencumbered' from 'view hides the charge'. "
              "Run:  python src/loan_hunter.py --districts HARDA --village Handia --show-owner")
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
    ap.add_argument("--debug", action="store_true",
                    help="on the first parcel, dump ror-detail JSON keys + save raw RoR HTML, then continue")
    a = ap.parse_args()
    dists = [d.strip() for d in a.districts.split(",")] if a.districts else None
    # breadth mode (no single village targeted): cap plots/village so the scan moves
    # village-to-village fast and any charge surfaces early. Depth (all plots) when a
    # specific --village is named (e.g. hunting one beneficiary's parcel).
    ppv = a.plots_per_village
    if ppv is None and not a.village:
        ppv = 30
    hunt(a.data_dir, dists, a.villages, ppv, a.delay, a.target_hits,
         a.village, a.show_owner, a.debug)
