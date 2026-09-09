"""
MP Bhulekh WebGIS 2.0 public API client (the NUMERATOR path).

The old mpbhulekh.gov.in (164.100.196.77) is dead; the live portal is
https://webgis2.mpbhulekh.gov.in (Quantela/Angular SPA). Its abadi Record-of-Rights
is a public REST API. Access needs NO password/API key — only:
  * header  no_token: true
  * header  qp-tc-request-id: <a session id the SPA mints on load>
  * body    {"tenant_id":"gov.in", ...}

The request-id is validated server-side (random values are rejected), so it is minted
the way the site does it: load the SPA once in headless Playwright and capture the
qp-tc-request-id it puts on its own XHRs. That value is reused for a batch and re-minted
when calls start returning 403. As a fallback you can supply one in src/.bhulekh_rid
(or a saved 'Copy as cURL' in src/.bhulekh_curl.txt).

CONFIRMED endpoints (POST, base = /certifiedcopy/ror/v1/public):
  /district  {tenant_id}                                   -> [{district_id, district_name(_ll), ror_district_id}]
  /tehsil    {tenant_id, district_id}                      -> [{tehsil_id, tehsil_name(_ll), ror_tehsil_id}]
  /village   {tenant_id, district_id, tehsil_id}           -> [{village_name(_ll), lgd_code, l6_id}]  <- join key
  /plot      {tenant_id, ror_district_id, ror_tehsil_id, lgd_code} -> [{property_id, clr_plot_no(_display)}]
  /ror-detail  (per parcel; carries the loan/encumbrance field) -- shape finalized by verify_ror.py
"""
from __future__ import annotations

import os
import re
import random
import string
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://webgis2.mpbhulekh.gov.in"
ROR = BASE + "/certifiedcopy/ror/v1/public"
APP_V = "1.1.137"


def mint_request_id(base: str = BASE, timeout_ms: int = 45000) -> str:
    """Load the SPA headless and capture the qp-tc-request-id it mints on its own XHRs.
    Requires: pip install playwright && python -m playwright install chromium."""
    from playwright.sync_api import sync_playwright
    found: dict[str, str] = {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(ignore_https_errors=True)
        pg = ctx.new_page()

        def on_req(req):
            v = req.headers.get("qp-tc-request-id")
            if v and "found" not in found:
                found["found"] = v
        pg.on("request", on_req)
        try:
            pg.goto(base + "/", timeout=timeout_ms, wait_until="networkidle")
        except Exception:
            pass
        b.close()
    if "found" not in found:
        raise RuntimeError("could not mint qp-tc-request-id from the SPA")
    return found["found"]


class BhulekhClient:
    def __init__(self, request_id: str | None = None, timeout: int = 30, auto_mint: bool = True):
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:155.0) "
                          "Gecko/20100101 Firefox/155.0",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "no_token": "true",
            "app_v": APP_V,
            "qp-language-code": "en",
            "Origin": BASE,
            "Referer": BASE + "/",
            "Sec-Fetch-Site": "same-origin",
        })
        self.rid = request_id or self._load_rid()
        if not self.rid and auto_mint:
            self.rid = mint_request_id()
        if not self.rid:
            raise SystemExit("no qp-tc-request-id (mint failed and none supplied)")

    @staticmethod
    def _load_rid() -> str | None:
        rid = os.environ.get("BHULEKH_RID")
        if rid:
            return rid.strip()
        here = os.path.dirname(__file__)
        for name in (".bhulekh_rid", ".bhulekh_curl.txt"):
            path = os.path.join(here, name)
            if os.path.exists(path):
                txt = open(path, encoding="utf-8").read()
                m = re.search(r"qp-tc-request-id:\s*'?([A-Za-z0-9-]+)", txt)
                if m:
                    return m.group(1)
                if name == ".bhulekh_rid":
                    return txt.strip()
        return None

    def _post(self, path: str, payload: dict) -> dict:
        r = self.s.post(ROR + path, json={"tenant_id": "gov.in", **payload},
                        headers={"qp-tc-request-id": self.rid},
                        timeout=self.timeout, verify=False)
        if r.status_code == 403 and self.rid:  # id likely expired -> re-mint once
            self.rid = mint_request_id()
            r = self.s.post(ROR + path, json={"tenant_id": "gov.in", **payload},
                            headers={"qp-tc-request-id": self.rid},
                            timeout=self.timeout, verify=False)
        if not r.ok:
            raise RuntimeError(f"{r.status_code} {path} -> {r.text[:400]}")
        return r.json()

    # ---- confirmed hierarchy ------------------------------------------------
    def districts(self) -> list[dict]:
        return self._post("/district", {}).get("data", [])

    def tehsils(self, district_id) -> list[dict]:
        return self._post("/tehsil", {"district_id": district_id}).get("data", [])

    def villages(self, district_id, tehsil_id) -> list[dict]:
        return self._post("/village", {"district_id": district_id,
                                        "tehsil_id": tehsil_id}).get("data", [])

    def plots(self, ror_district_id, ror_tehsil_id, lgd_code) -> list[dict]:
        return self._post("/plot", {"ror_district_id": str(ror_district_id),
                                     "ror_tehsil_id": str(ror_tehsil_id),
                                     "lgd_code": str(lgd_code)}).get("data", [])

    def ror_detail(self, ror_district_id, ror_tehsil_id, lgd_code, property_id,
                   extra: dict | None = None) -> dict:
        payload = {"ror_district_id": str(ror_district_id),
                   "ror_tehsil_id": str(ror_tehsil_id),
                   "lgd_code": str(lgd_code),
                   "property_id": str(property_id)}
        if extra:
            payload.update(extra)
        return self._post("/ror-detail", payload)


if __name__ == "__main__":
    c = BhulekhClient()
    print("request-id ok; districts:", len(c.districts()))
