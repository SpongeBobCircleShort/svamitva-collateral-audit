"""
SVAMITVA card scraper (the DENOMINATOR).

Walks the SVAMITVA card-distribution hierarchy for Madhya Pradesh:

    state(23) -> district -> block(janpad) -> village

and records, per village, how many property cards were distributed. The village
`code` returned by the portal is the LGD village code, which is our join key to
the MP Bhulekh encumbrance data (the numerator).

Runs from anywhere (svamitva.nic.in is reachable). Resumable: each district is
checkpointed into a local sqlite db, so re-running skips finished districts.

Outputs (in --data-dir, default ./data):
  svamitva_districts.parquet  one row per district (rollup counts)
  svamitva_cards.parquet      one row per village (join-ready denominator)

Usage:
  python src/svamitva_scraper.py                              # full MP (default state 23)
  python src/svamitva_scraper.py --state 22                   # full Chhattisgarh
  python src/svamitva_scraper.py --district Bhopal            # one district by name (or code)
  python src/svamitva_scraper.py --district Dhar --tehsil Badnawar   # one tehsil
  python src/svamitva_scraper.py --district Dhar --village Handia    # one village
  python src/svamitva_scraper.py --limit 2                    # first 2 districts (smoke test)

--district / --tehsil / --village accept a code OR a case-insensitive (partial) name, so the
caller can target exactly the unit they want without looking up codes.
"""
from __future__ import annotations

import os
import argparse
import sqlite3
import pandas as pd

try:
    from .dwr import DwrClient
except ImportError:  # run as a script, not a module
    from dwr import DwrClient

STATE = 23  # default: Madhya Pradesh (LGD / SVAMITVA state code); pass --state to override
STATE_NAMES = {23: "Madhya Pradesh", 22: "Chhattisgarh", 24: "Gujarat"}


def _db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS districts(
            district_code INTEGER PRIMARY KEY, district_en TEXT, district_hi TEXT,
            cards_distributed INTEGER, properties_total INTEGER,
            total_village INTEGER, notify_village INTEGER, completed_village INTEGER
        );
        CREATE TABLE IF NOT EXISTS villages(
            lgd_village_code INTEGER PRIMARY KEY,
            district_code INTEGER, district_en TEXT,
            block_code INTEGER, block_en TEXT, block_hi TEXT,
            village_en TEXT, village_hi TEXT,
            cards_distributed INTEGER, properties_total INTEGER, drone_date TEXT
        );
        CREATE TABLE IF NOT EXISTS done_districts(district_code INTEGER PRIMARY KEY);
        """
    )
    return con


def _match(spec: str | None, *fields) -> bool:
    """True if spec is unset, equals a field's code exactly, or is a case-insensitive substring of
    any name field. Lets --district/--tehsil/--village take either a code or a (partial) name."""
    if not spec:
        return True
    s = str(spec).strip().lower()
    for f in fields:
        if f is None:
            continue
        fs = str(f).strip().lower()
        if s == fs or (not s.isdigit() and s in fs):
            return True
    return False


def scrape(data_dir: str, only_district=None, limit: int | None = None, delay: float = 0.4,
           state: int = STATE, only_tehsil: str | None = None, only_village: str | None = None):
    os.makedirs(data_dir, exist_ok=True)
    dbpath = os.path.join(data_dir, "svamitva.sqlite")
    con = _db(dbpath)
    c = DwrClient(delay=delay)

    sname = STATE_NAMES.get(state, f"state {state}")
    districts = c.call("getPropertyCardDistributedCount", state)
    print(f"[districts] {len(districts)} found for {sname}")
    for d in districts:
        con.execute(
            "INSERT OR REPLACE INTO districts VALUES (?,?,?,?,?,?,?,?)",
            (d["code"], d.get("name"), d.get("hindiName"), d.get("pcount"),
             d.get("allpcount"), d.get("total_village"), d.get("notify_village"),
             d.get("completed_village")),
        )
    con.commit()

    if only_district is not None:
        districts = [d for d in districts
                     if _match(only_district, d["code"], d.get("name"), d.get("hindiName"))]
        if not districts:
            print(f"no district matched '{only_district}' in {sname}"); con.close(); return
    if limit:
        districts = districts[:limit]

    # a tehsil/village filter targets specific units; skip the per-district "done" short-circuit so
    # a re-run with a narrower filter still scrapes.
    targeted = bool(only_tehsil or only_village)
    done = {r[0] for r in con.execute("SELECT district_code FROM done_districts")}
    for di, d in enumerate(districts, 1):
        dcode, dname = d["code"], d.get("name")
        if dcode in done and not targeted:
            print(f"[{di}/{len(districts)}] {dname} ({dcode}) — already done, skip")
            continue
        blocks = c.call("getBlockPropertyCardDistributedCount", state, dcode)
        blocks = [b for b in blocks if _match(only_tehsil, b["code"], b.get("name"), b.get("hindiName"))]
        if only_tehsil and not blocks:
            print(f"[{di}/{len(districts)}] {dname}: no tehsil matched '{only_tehsil}'")
            continue
        nvill = 0
        for b in blocks:
            bcode = b["code"]
            villages = c.call("getVillagePropertyCardDistributedCount", state, dcode, bcode)
            villages = [v for v in villages
                        if _match(only_village, v["code"], v.get("name"), v.get("hindiName"))]
            for v in villages:
                con.execute(
                    "INSERT OR REPLACE INTO villages VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (v["code"], dcode, dname, bcode, b.get("name"), b.get("hindiName"),
                     v.get("name"), v.get("hindiName"), v.get("pcount"),
                     v.get("pcountall"), v.get("droneDate")),
                )
            nvill += len(villages)
        if not targeted:
            con.execute("INSERT OR REPLACE INTO done_districts VALUES (?)", (dcode,))
        con.commit()
        print(f"[{di}/{len(districts)}] {dname} ({dcode}) — {len(blocks)} blocks, {nvill} villages")

    # export parquet snapshots
    pd.read_sql("SELECT * FROM districts ORDER BY district_en", con).to_parquet(
        os.path.join(data_dir, "svamitva_districts.parquet"), index=False)
    vdf = pd.read_sql("SELECT * FROM villages", con)
    vdf.to_parquet(os.path.join(data_dir, "svamitva_cards.parquet"), index=False)
    con.close()

    print(f"\nDONE. villages={len(vdf)}  cards_distributed(sum)={int(vdf.cards_distributed.fillna(0).sum()):,}")
    print(f"  -> {os.path.join(data_dir, 'svamitva_cards.parquet')}")
    print(f"  -> {os.path.join(data_dir, 'svamitva_districts.parquet')}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--state", type=int, default=STATE, help="SVAMITVA/LGD state code (23=MP, 22=CG)")
    ap.add_argument("--district", default=None, help="district: code or (partial) name")
    ap.add_argument("--tehsil", default=None, help="tehsil/block: code or (partial) name")
    ap.add_argument("--village", default=None, help="village: code or (partial) name")
    ap.add_argument("--limit", type=int, default=None, help="only first N districts")
    ap.add_argument("--delay", type=float, default=0.4, help="base politeness delay (s)")
    a = ap.parse_args()
    scrape(a.data_dir, a.district, a.limit, a.delay, a.state, a.tehsil, a.village)
