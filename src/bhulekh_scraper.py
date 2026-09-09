"""
MP Bhulekh encumbrance scraper (the NUMERATOR). RUN ON AN INDIA NETWORK.

Reads the target village list (only villages with SVAMITVA cards) from
svamitva_cards.parquet, fetches each village's abadi / B-1 record from MP Bhulekh,
counts how many parcels carry a loan/encumbrance (ऋण / बंधक), and writes a
join-ready table keyed by LGD village code.

Design notes:
  * The exact Bhulekh request/response shape is supplied via a --flow JSON
    (see bhulekh_flow.example.json), produced from bhulekh_discover.py. Two spots
    are flow-dependent and marked FINALIZE-AFTER-DISCOVERY: build_request() and
    parse_record().
  * Crawl order = "from tehsil city centers outward": within each district the
    largest settlements (highest card count, i.e. the tehsil towns) are fetched
    first, then smaller villages. Pass --hq-list to force specific LGD codes first.
  * Resumable: every fetched village is checkpointed in sqlite. Re-run to continue.
  * Polite: single-threaded, configurable delay. Never stores owner PII — only
    per-village aggregates.

Usage (after discovery + filling the flow json):
  python src/bhulekh_scraper.py --flow src/bhulekh_flow.json
  python src/bhulekh_scraper.py --flow src/bhulekh_flow.json --limit 50   # first batch
"""
from __future__ import annotations

import os
import io
import re
import json
import time
import random
import argparse
import sqlite3
import requests
import pandas as pd

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# --------------------------------------------------------------------------- db
def _db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS enc(
            lgd_village_code INTEGER PRIMARY KEY,
            abadi_parcels_total INTEGER,
            parcels_with_loan INTEGER,
            loan_amount_total REAL,
            status TEXT,            -- ok | empty | error | captcha_skipped
            note TEXT
        );
        """
    )
    return con


# --------------------------------------------------- FINALIZE-AFTER-DISCOVERY (1)
def build_request(flow: dict, village: dict) -> tuple[str, str, dict]:
    """Return (method, url, kwargs) for one village's record request.

    `village` has keys: lgd_village_code, district_en, block_en, village_en, ...
    Bhulekh code params (district_code/tehsil_code/village_code) usually differ from
    LGD; the discovery step reveals how to obtain them. If Bhulekh keys == LGD village
    code, the template can use {lgd_village_code} directly. Otherwise a lookup built
    during discovery (data/bhulekh_codes.json) maps LGD -> Bhulekh codes.
    """
    rr = flow["record_request"]
    subs = {
        "lgd_village_code": village["lgd_village_code"],
        "district_code": village.get("bh_district_code", ""),
        "tehsil_code": village.get("bh_tehsil_code", ""),
        "village_code": village.get("bh_village_code", village["lgd_village_code"]),
    }
    url = rr["url"].format(**subs)
    body = rr.get("body_template", "").format(**subs)
    kwargs: dict = {"verify": flow.get("verify_tls", False), "timeout": 45}
    if rr["method"].upper() == "POST":
        kwargs["data"] = body
        kwargs["headers"] = {"Content-Type": rr.get(
            "content_type", "application/x-www-form-urlencoded")}
    return rr["method"].upper(), url, kwargs


# --------------------------------------------------- FINALIZE-AFTER-DISCOVERY (2)
def parse_record(flow: dict, text: str) -> tuple[int, int, float, str]:
    """Parse one village record -> (abadi_total, with_loan, loan_amount, status).

    Generic HTML-table implementation: find a table with a loan/encumbrance column,
    optionally keep only abadi rows, count rows whose loan cell is non-empty. After
    discovery, tighten this to the exact table/column if the generic pass is noisy.
    """
    enc = flow["encumbrance"]
    kws = [k.lower() for k in enc["keywords"]]
    empties = {e.strip().lower() for e in enc["empty_values"]}
    amt_kws = [k.lower() for k in enc.get("amount_keywords", [])]
    af = flow.get("abadi_filter") or {}

    if flow.get("response_kind") == "json":
        return _parse_json(text, kws, empties, amt_kws)

    try:
        tables = pd.read_html(io.StringIO(text))
    except ValueError:
        return 0, 0, 0.0, "empty"

    best = None
    for t in tables:
        cols = [str(c).lower() for c in t.columns]
        if any(any(k in c for k in kws) for c in cols):
            best = t
            break
    if best is None:
        return 0, 0, 0.0, "empty"

    # optional abadi-only filter
    if af.get("column_keywords"):
        acol = _find_col(best, af["column_keywords"])
        if acol is not None:
            avals = [v.lower() for v in af.get("abadi_values", [])]
            best = best[best[acol].astype(str).str.lower().apply(
                lambda x: any(v in x for v in avals))]

    loan_col = _find_col(best, enc["keywords"])
    total = len(best)
    if loan_col is None or total == 0:
        return total, 0, 0.0, "ok"

    cells = best[loan_col].astype(str).str.strip()
    has_loan = cells.apply(lambda x: x.lower() not in empties)
    with_loan = int(has_loan.sum())

    amount = 0.0
    amt_col = _find_col(best, amt_kws) if amt_kws else None
    if amt_col is not None:
        amount = float(pd.to_numeric(
            best.loc[has_loan, amt_col].astype(str).str.replace(r"[^\d.]", "", regex=True),
            errors="coerce").fillna(0).sum())
    return total, with_loan, amount, "ok"


def _find_col(df: pd.DataFrame, keywords: list[str]):
    kws = [k.lower() for k in keywords]
    for c in df.columns:
        if any(k in str(c).lower() for k in kws):
            return c
    return None


def _parse_json(text: str, kws, empties, amt_kws):
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return 0, 0, 0.0, "empty"
    rows = data if isinstance(data, list) else next(
        (v for v in data.values() if isinstance(v, list)), [])
    total = len(rows)
    with_loan = 0
    amount = 0.0
    for r in rows:
        if not isinstance(r, dict):
            continue
        lk = next((k for k in r if any(w in k.lower() for w in kws)), None)
        if lk and str(r[lk]).strip().lower() not in empties:
            with_loan += 1
            ak = next((k for k in r if any(w in k.lower() for w in amt_kws)), None)
            if ak:
                m = re.sub(r"[^\d.]", "", str(r[ak]))
                amount += float(m) if m else 0.0
    return total, with_loan, amount, "ok"


# ------------------------------------------------------------------------- crawl
def order_targets(df: pd.DataFrame, hq_codes: set[int]) -> pd.DataFrame:
    """Tehsil-town-center-outward: HQ villages first, then by descending card count,
    grouped so each district's biggest settlements lead."""
    df = df.copy()
    df["_hq"] = df["lgd_village_code"].isin(hq_codes).astype(int)
    return df.sort_values(
        ["district_en", "_hq", "cards_distributed"],
        ascending=[True, False, False]).drop(columns="_hq")


def run(data_dir: str, flow_path: str, limit: int | None, delay: float, hq_list: str | None):
    cards_path = os.path.join(data_dir, "svamitva_cards.parquet")
    if not os.path.exists(cards_path):
        raise SystemExit(f"missing {cards_path} — run svamitva_scraper.py first")
    with open(flow_path, encoding="utf-8") as f:
        flow = json.load(f)

    targets = pd.read_parquet(cards_path)
    targets = targets[targets["cards_distributed"].fillna(0) > 0]

    hq_codes: set[int] = set()
    if hq_list and os.path.exists(hq_list):
        hq_codes = {int(x) for x in open(hq_list).read().split()}
    targets = order_targets(targets, hq_codes)
    if limit:
        targets = targets.head(limit)

    con = _db(os.path.join(data_dir, "bhulekh.sqlite"))
    done = {r[0] for r in con.execute("SELECT lgd_village_code FROM enc WHERE status!='error'")}
    sess = requests.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0 (compatible; vetting-audit/1.0)"})

    todo = [v for v in targets.to_dict("records") if v["lgd_village_code"] not in done]
    print(f"targets={len(targets)}  already_done={len(done)}  to_fetch={len(todo)}")
    if flow.get("captcha", {}).get("present"):
        print("!! flow marks captcha present — expect manual solves; consider a headed run.")

    for i, v in enumerate(todo, 1):
        code = v["lgd_village_code"]
        try:
            method, url, kwargs = build_request(flow, v)
            r = sess.request(method, url, **kwargs)
            r.raise_for_status()
            total, wl, amt, status = parse_record(flow, r.text)
            con.execute("INSERT OR REPLACE INTO enc VALUES (?,?,?,?,?,?)",
                        (code, total, wl, amt, status, None))
        except Exception as e:  # noqa: BLE001
            con.execute("INSERT OR REPLACE INTO enc VALUES (?,?,?,?,?,?)",
                        (code, None, None, None, "error", str(e)[:200]))
        if i % 25 == 0:
            con.commit()
            print(f"  {i}/{len(todo)}  {v['district_en']}/{v['village_en']}")
        time.sleep(delay + random.uniform(0, delay))

    con.commit()
    out = pd.read_sql("SELECT * FROM enc", con)
    out.to_parquet(os.path.join(data_dir, "bhulekh_encumbrance.parquet"), index=False)
    con.close()
    ok = out[out.status == "ok"]
    print(f"\nDONE. rows={len(out)} ok={len(ok)} "
          f"parcels_with_loan(sum)={int(ok.parcels_with_loan.fillna(0).sum())}")
    print(f"  -> {os.path.join(data_dir, 'bhulekh_encumbrance.parquet')}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--flow", required=True, help="path to filled bhulekh_flow.json")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--delay", type=float, default=3.0, help="politeness delay (s)")
    ap.add_argument("--hq-list", default=None, help="file of LGD village codes to fetch first")
    a = ap.parse_args()
    run(a.data_dir, a.flow, a.limit, a.delay, a.hq_list)
