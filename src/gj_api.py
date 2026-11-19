"""
Gujarat AnyRoR client (anyror.gujarat.gov.in) — the MP `bhulekh_api` / MH `maha_api` analog.

AnyRoR is an ASP.NET WebForms app (VIEWSTATE + __doPostBack) with an UpdatePanel; the cascading
dropdowns degrade to a FULL postback, so this client does full postbacks and parses the HTML.
See docs/gujarat_portal.md.

Ungated (this client): record type -> district -> taluka -> village -> survey no list. That proves
a record EXISTS for a village and enumerates survey numbers. The record VIEW (VF-7 7/12 content,
incl. the બોજો / boja encumbrance and VF-6 mutation entries) is CAPTCHA-gated, so it is
assisted/user-run (captcha solved by a human) — see fetch_record().

Rural record types (drpLandRecord): 1=VF-7 (7/12 RoR), 2=VF-8A khata, 3=VF-6 mutation entries.

Usage:
  from gj_api import AnyRoRClient
  c = AnyRoRClient()
  c.talukas("07")                       # Ahmedabad -> [(code, name), ...]
  c.villages("07", "06")                # Ahmedabad / Daskroi
  c.survey_numbers("07","06","<vcode>") # VF-7 survey numbers in a village
"""
from __future__ import annotations

import re
import base64
import requests

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    raise SystemExit("gj_api needs beautifulsoup4 — pip install beautifulsoup4")

BASE = "https://anyror.gujarat.gov.in/"
PAGE = BASE + "LandRecordRural.aspx"
PFX = "ctl00$ContentPlaceHolder1$"
PLACEHOLDERS = {"પસંદ કરો", "Select (પસંદ કરો)", "Select", ""}

RECORD_TYPES = {"vf7": "1", "vf8a": "2", "vf6": "3"}   # VF-7 RoR, 8A khata, VF-6 mutation

# boja/charge keywords in a VF-7 record — the collateral signal (analog of MP col-11 / MH इतर हक्क)
CHARGE_KW = ["બોજો", "બોજ", "boja", "ગીરો", "ગિરો", "તારણ", "mortgage", "hypothec",
             "charge", "lien", "બેંક", "બેન્ક", "bank", "loan", "કરજ", "cersai"]


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


class AnyRoRClient:
    def __init__(self, timeout: int = 45):
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:155.0) "
                          "Gecko/20100101 Firefox/155.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Origin": BASE.rstrip("/"),
            "Referer": PAGE,
        })
        self.form: dict[str, str] = {}
        self._last = ""
        self._load()

    # ---- ASP.NET form plumbing ---------------------------------------------
    def _load(self) -> None:
        r = self.s.get(PAGE, timeout=self.timeout)
        r.raise_for_status()
        self._last = r.text
        self.form = self._parse_form(r.text)

    @staticmethod
    def _parse_form(html: str) -> dict[str, str]:
        soup = BeautifulSoup(html, "html.parser")
        form: dict[str, str] = {}
        for inp in soup.find_all("input"):
            name = inp.get("name")
            if not name:
                continue
            t = (inp.get("type") or "text").lower()
            if t in ("hidden", "text", "password"):
                form[name] = inp.get("value", "") or ""
            elif t in ("radio", "checkbox") and inp.has_attr("checked"):
                form[name] = inp.get("value", "") or ""
        for sel in soup.find_all("select"):
            name = sel.get("name")
            if not name or sel.has_attr("disabled"):
                continue
            opts = sel.find_all("option")
            if not opts:                 # empty downstream dropdown — browser omits it; posting an
                continue                 # empty value trips ASP.NET EventValidation (server 500)
            opt = sel.find("option", selected=True) or opts[0]
            form[name] = opt.get("value", "") or ""
        return form

    def _postback(self, target: str, changes: dict, retries: int = 3) -> str:
        """Full ASP.NET postback: set __EVENTTARGET + field changes, submit, re-parse."""
        last = None
        for attempt in range(retries):
            body = dict(self.form)
            body.update(changes)
            body["__EVENTTARGET"] = target
            body["__EVENTARGUMENT"] = ""
            body["__LASTFOCUS"] = ""
            body.pop("ctl00$ContentPlaceHolder1$btnGo", None)   # don't submit unless intended
            try:
                r = self.s.post(PAGE, data=body, timeout=self.timeout)
                if r.status_code == 500 and attempt < retries - 1:
                    continue
                r.raise_for_status()
                self._last = r.text
                self.form = self._parse_form(r.text)
                return r.text
            except requests.RequestException as e:  # noqa: PERF203
                last = e
        raise last  # type: ignore[misc]

    @staticmethod
    def _options(html: str, select_id: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        sel = soup.find("select", id=select_id)
        if not sel:
            return []
        out = []
        for o in sel.find_all("option"):
            txt = o.get_text(strip=True)
            val = o.get("value", "")
            if txt not in PLACEHOLDERS and val not in ("", "0"):
                out.append((val, txt))
        return out

    # ---- ungated cascade ----------------------------------------------------
    def set_record_type(self, record_type: str = "vf7") -> str:
        self.form[PFX + "drpLandRecord"] = RECORD_TYPES[record_type]
        return self._postback(PFX + "drpLandRecord", {PFX + "drpLandRecord": RECORD_TYPES[record_type]})

    def districts(self) -> list[tuple[str, str]]:
        return self._options(self._last, "ContentPlaceHolder1_ddlDistrict")

    def talukas(self, district: str, record_type: str = "vf7") -> list[tuple[str, str]]:
        self.set_record_type(record_type)
        self._postback(PFX + "ddlDistrict", {PFX + "ddlDistrict": district})
        return self._options(self._last, "ContentPlaceHolder1_ddlTaluka")

    def villages(self, district: str, taluka: str, record_type: str = "vf7") -> list[tuple[str, str]]:
        self.talukas(district, record_type)
        self._postback(PFX + "ddlTaluka", {PFX + "ddlDistrict": district, PFX + "ddlTaluka": taluka})
        return self._options(self._last, "ContentPlaceHolder1_ddlVillage")

    def survey_numbers(self, district: str, taluka: str, village: str,
                       record_type: str = "vf7") -> list[tuple[str, str]]:
        self.villages(district, taluka, record_type)
        self._postback(PFX + "ddlVillage",
                       {PFX + "ddlDistrict": district, PFX + "ddlTaluka": taluka,
                        PFX + "ddlVillage": village})
        self._sel = {PFX + "ddlDistrict": district, PFX + "ddlTaluka": taluka,
                     PFX + "ddlVillage": village}
        return self._options(self._last, "ContentPlaceHolder1_ddlSurveyNo")

    # ---- captcha-gated record view -----------------------------------------
    def captcha_image(self, path: str) -> str:
        """Save the current inline base64 captcha (id ..._i_captcha_1) for a human to read."""
        m = re.search(r'id="[^"]*i_captcha_1"\s+src="data:image/png;base64,([A-Za-z0-9+/=]+)"',
                      self._last) or \
            re.search(r'src="data:image/png;base64,([A-Za-z0-9+/=]+)"\s+id="[^"]*i_captcha_1"',
                      self._last)
        if not m:
            raise RuntimeError("captcha image not found on page")
        with open(path, "wb") as f:
            f.write(base64.b64decode(m.group(1)))
        return path

    def fetch_record(self, survey_no: str, captcha: str) -> str:
        """Submit the captcha + survey no and return the rendered record HTML. Human solves captcha."""
        changes = dict(getattr(self, "_sel", {}))
        changes[PFX + "ddlSurveyNo"] = str(survey_no)
        changes[PFX + "txt_captcha_1"] = str(captcha)
        body = dict(self.form)
        body.update(changes)
        body["__EVENTTARGET"] = ""
        body["__EVENTARGUMENT"] = ""
        body[PFX + "btnGo"] = "Get Record Detail"
        r = self.s.post(PAGE, data=body, timeout=self.timeout)
        r.raise_for_status()
        self._last = r.text
        return r.text


def boja(html: str) -> tuple[bool, list[str]]:
    """(has_charge, matched_terms) from a VF-7 record — the Gujarat collateral field (boja)."""
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    low = text.lower()
    hits = [k for k in CHARGE_KW if (k in text) or (k.lower() in low)]
    return (bool(hits), hits)


if __name__ == "__main__":
    c = AnyRoRClient()
    print("districts:", len(c.districts()))
    tl = c.talukas("07")                    # Ahmedabad
    print("Ahmedabad talukas:", len(tl), tl[:4])
    vg = c.villages("07", "06")             # Daskroi
    print("Daskroi villages:", len(vg), vg[:4])
    sv = c.survey_numbers("07", "06", vg[0][0]) if vg else []
    print("survey nos in", vg[0][1] if vg else "-", ":", len(sv), sv[:6])
