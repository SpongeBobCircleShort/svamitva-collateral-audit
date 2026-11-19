"""
Chhattisgarh Bhuiyan client — public khasra (RoR) records, no login/captcha.

Portal: https://revenue.cg.nic.in/bhuiyanuser/User/Selection_Report_For_KhasraDetail.aspx
ASP.NET WebForms. Flow (see docs/chhattisgarh_portal.md):
  district -> tehsil -> village   postbacks on ddlDist / ddlTehsil / ddlGram
  khasra list for a village       JSON page method  POST .../GetFruits  {"prefix","gsrno"}
  one khasra record               txtSearch = exact khasra + btnSearch postback

Reads only non-personal fields for the audit (tenure class, area, holding type single/joint,
mutation reference, spatial-map presence). Owner names are ignored, never stored.

Usage (smoke test):  python src/cg_api.py
"""
from __future__ import annotations

import re
import json
import time
import html as _html
import requests

BASE = "https://revenue.cg.nic.in/bhuiyanuser/User/"
PAGE = BASE + "Selection_Report_For_KhasraDetail.aspx"
GET_FRUITS = PAGE + "/GetFruits"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

PLACEHOLDERS = {"", "--चुने--", "--चुनें--", "-- चुने --"}
# ASP.NET postback state carried across the cascade
_STATE_FIELDS = ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")


def _field(page: str, name: str) -> str:
    m = re.search(rf'id="{name}"[^>]*value="([^"]*)"', page) or \
        re.search(rf'name="{name}"[^>]*value="([^"]*)"', page)
    return _html.unescape(m.group(1)) if m else ""


def _state(page: str) -> dict:
    return {k: _field(page, k) for k in _STATE_FIELDS}


def _options(page: str, select_id: str) -> list[tuple[str, str]]:
    m = re.search(rf'<select[^>]+id="{select_id}"[^>]*>(.*?)</select>', page, re.S)
    if not m:
        return []
    out = []
    for v, t in re.findall(r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', m.group(1), re.S):
        text = _html.unescape(re.sub(r"<[^>]+>", "", t)).strip()
        if text not in PLACEHOLDERS and v not in PLACEHOLDERS:
            out.append((v, text))
    return out


def _to_text(page: str) -> str:
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    t = re.sub(r"<br\s*/?>|</tr>|</p>|</div>|</td>", "\n", t)
    t = re.sub(r"<[^>]+>", "\t", t)
    return _html.unescape(t)


def _row(text: str, label: str) -> str:
    m = re.search(rf"{re.escape(label)}\s*:?\s*\t+([^\n\t][^\n]*)", text)
    return m.group(1).strip() if m else ""


class BhuiyanClient:
    def __init__(self, delay: float = 1.5, timeout: int = 45):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.delay, self.timeout = delay, timeout
        self.page = ""
        self.st: dict = {}

    # ---- low level ----------------------------------------------------------
    def load(self):
        r = self.s.get(PAGE, timeout=self.timeout)
        r.raise_for_status()
        self.page, self.st = r.text, _state(r.text)
        return self

    def _postback(self, target: str, extra: dict, retries: int = 3) -> str:
        """Fire __doPostBack(target,'') with current dropdown selections in `extra`.
        The portal returns sporadic 500s under load, so retry with a fresh page state."""
        body = dict(self.st)
        body.update({"__EVENTTARGET": target, "__EVENTARGUMENT": "", "__LASTFOCUS": ""})
        body.update(extra)
        last = None
        for attempt in range(retries):
            try:
                r = self.s.post(PAGE, data=body, timeout=self.timeout,
                                headers={"Referer": PAGE})
                if r.status_code == 500 and attempt < retries - 1:
                    time.sleep(2 + attempt * 2); continue
                r.raise_for_status()
                self.page, self.st = r.text, _state(r.text)
                time.sleep(self.delay)
                return r.text
            except requests.RequestException as e:  # noqa: PERF203
                last = e
                time.sleep(2 + attempt * 2)
        raise last  # type: ignore[misc]

    # ---- hierarchy ----------------------------------------------------------
    def districts(self) -> list[tuple[str, str]]:
        if not self.page:
            self.load()
        return _options(self.page, "ddlDist")

    def tehsils(self, dist: str) -> list[tuple[str, str]]:
        self._postback("ddlDist", {"ddlDist": dist})
        self._sel = {"ddlDist": dist}
        return _options(self.page, "ddlTehsil")

    def villages(self, dist: str, tehsil: str) -> list[tuple[str, str]]:
        self.tehsils(dist)
        self._postback("ddlTehsil", {"ddlDist": dist, "ddlTehsil": tehsil})
        self._sel = {"ddlDist": dist, "ddlTehsil": tehsil}
        return _options(self.page, "ddlGram")

    def select_village(self, dist: str, tehsil: str, gram_code: str):
        """Cascade to a village so btnSearch will resolve khasras for it."""
        self.villages(dist, tehsil)
        self._postback("ddlGram", {"ddlDist": dist, "ddlTehsil": tehsil, "ddlGram": gram_code})
        self._sel = {"ddlDist": dist, "ddlTehsil": tehsil, "ddlGram": gram_code}
        return self

    # ---- khasra list + record ----------------------------------------------
    def khasra_list(self, gram_code: str, prefix: str) -> list[str]:
        """JSON page method: exact khasra numbers under `gram_code` matching `prefix`."""
        r = self.s.post(GET_FRUITS, timeout=self.timeout,
                        headers={"Content-Type": "application/json; charset=utf-8",
                                 "Referer": PAGE},
                        data=json.dumps({"prefix": str(prefix), "gsrno": str(gram_code)}))
        r.raise_for_status()
        return r.json().get("d", []) or []

    def all_khasras(self, gram_code: str) -> list[str]:
        """Sweep prefixes 1-9 to enumerate a village's khasras (dedup, order-stable)."""
        seen, out = set(), []
        for p in "123456789":
            for k in self.khasra_list(gram_code, p):
                if k not in seen:
                    seen.add(k); out.append(k)
            time.sleep(self.delay / 3)
        return out

    def record(self, khasra: str) -> dict:
        """Fetch one khasra record; return non-personal audit fields only."""
        sel = getattr(self, "_sel", {})
        body_extra = dict(sel)
        body_extra.update({"txtSearch": str(khasra),
                           "RadioButtonSelectSerachOption": "0", "RblReportType": "0"})
        html = self._postback("btnSearch", body_extra)
        text = _to_text(html)
        tenure = _row(text, "धारणाधिकार")
        holding = ""
        mh = re.search(r"जोत का प्रकार\s*-\s*([^\n\t]+)", text)
        if mh:
            holding = mh.group(1).strip()
        return {
            "khasra": _row(text, "बसरा क्रमांक") or khasra,
            "area_ha": (re.search(r"चयनित खसरा[\s\S]*?\(\s*([\d.]+)\s*हे", text) or ["", ""])[1],
            "tenure": tenure,                       # आबादी भूमि / शासकीय भूमि / भूमिस्वामी - कृषि भूमि
            "is_abadi": "आबादी" in tenure,
            "is_govt": "शासकीय" in tenure,
            "holding_type": holding,                # अकेला (single) / संयुक्त (joint)
            "has_map": "giscode=" in html,
            "has_mutation_link": "DeedDetailsKhasraWise" in html or "पंजीयन" in text,
        }


if __name__ == "__main__":
    c = BhuiyanClient()
    dl = c.districts()
    print(f"districts: {len(dl)}  e.g. {dl[:3]}")
    # Balod(11) -> Balod(55) -> Khairtarai(6201017), the abadi village from recon
    c.select_village("11", "55", "6201017")
    ks = c.khasra_list("6201017", "236")
    print(f"khasra match for 236: {ks}")
    if ks:
        print("record:", c.record(ks[0]))
