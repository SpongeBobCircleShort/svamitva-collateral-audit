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
  python src/svamitva_scraper.py                 # full MP
  python src/svamitva_scraper.py --district 396  # just Bhopal (svamitva code)
  python src/svamitva_scraper.py --limit 2       # first 2 districts (smoke test)
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

STATE = 23  # Madhya Pradesh (LGD / SVAMITVA state code)


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


def scrape(data_dir: str, only_district: int | None, limit: int | None, delay: float):
    os.makedirs(data_dir, exist_ok=True)
    dbpath = os.path.join(data_dir, "svamitva.sqlite")
    con = _db(dbpath)
    c = DwrClient(delay=delay)

    districts = c.call("getPropertyCardDistributedCount", STATE)
    print(f"[districts] {len(districts)} found for MP")
    for d in districts:
        con.execute(
            "INSERT OR REPLACE INTO districts VALUES (?,?,?,?,?,?,?,?)",
            (d["code"], d.get("name"), d.get("hindiName"), d.get("pcount"),
             d.get("allpcount"), d.get("total_village"), d.get("notify_village"),
             d.get("completed_village")),
        )
    con.commit()

    if only_district is not None:
        districts = [d for d in districts if d["code"] == only_district]
    if limit:
        districts = districts[:limit]

    done = {r[0] for r in con.execute("SELECT district_code FROM done_districts")}
    for di, d in enumerate(districts, 1):
        dcode, dname = d["code"], d.get("name")
        if dcode in done:
            print(f"[{di}/{len(districts)}] {dname} ({dcode}) — already done, skip")
            continue
        blocks = c.call("getBlockPropertyCardDistributedCount", STATE, dcode)
        nvill = 0
        for b in blocks:
            bcode = b["code"]
            villages = c.call("getVillagePropertyCardDistributedCount", STATE, dcode, bcode)
            for v in villages:
                con.execute(
                    "INSERT OR REPLACE INTO villages VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (v["code"], dcode, dname, bcode, b.get("name"), b.get("hindiName"),
                     v.get("name"), v.get("hindiName"), v.get("pcount"),
                     v.get("pcountall"), v.get("droneDate")),
                )
            nvill += len(villages)
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
    ap.add_argument("--district", type=int, default=None, help="single SVAMITVA district code")
    ap.add_argument("--limit", type=int, default=None, help="only first N districts")
    ap.add_argument("--delay", type=float, default=0.4, help="base politeness delay (s)")
    a = ap.parse_args()
    scrape(a.data_dir, a.district, a.limit, a.delay)
