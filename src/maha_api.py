"""
Maharashtra Mahabhulekh client (bhulekh.mahabhumi.gov.in) — the MP `bhulekh_api` analog.

Mahabhulekh is an ASP.NET WebForms app (VIEWSTATE + __doPostBack), not a REST/JSON API, and the
cascading dropdowns run in an UpdatePanel. They degrade to a FULL postback when __ASYNCPOST is
omitted, so this client does full postbacks and parses the returned HTML — simpler and steadier
than the AJAX delta format. See docs/maharashtra_portal.md.

Ungated (this client): district -> taluka -> village -> survey/gat list. That proves a record
EXISTS for a village and counts parcels. The record VIEW (7/12 or Property Card content, incl. the
"Other Rights"/इतर हक्क encumbrance column) is gated by a mobile number + captcha, so it is
assisted/user-run (like MP's ror_sampler) — see fetch_record().

Record types (rbtnSelectType): satbara=7/12, 8a, property_card=गाठाण/abadi (SVAMITVA), kprat.
For the SIPI rural-habitation question and the collateral question, use property_card.

Usage:
  from maha_api import MahabhulekhClient
  c = MahabhulekhClient()
  c.talukas("25")                 # Pune -> [(code, name), ...]
  c.villages("25", "9")           # Pune / Daund
  c.survey_numbers("25","9","<vill>", record_type="property_card")
"""
from __future__ import annotations

import re
import requests

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    raise SystemExit("maha_api needs beautifulsoup4 — pip install beautifulsoup4")

BASE = "https://bhulekh.mahabhumi.gov.in/"
PFX = "ctl00$ContentPlaceHolder1$"
PLACEHOLDERS = {"--निवडा--", "--Select Option--", "--Select--", ""}

def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


RECORD_TYPES = {"satbara": "SelectSatbara", "8a": "Select8A",
                "property_card": "SelectPC", "kprat": "SelectKPrat"}
# radio index within rbtnSelectType (for the __doPostBack target rbtnSelectType$<idx>)
RECORD_TYPE_INDEX = {"satbara": 0, "8a": 1, "property_card": 2, "kprat": 3}

# Static district list embedded in the page (native <select> ddlMainDist), name -> code.
DISTRICTS = {
    "Nandurbar": "1", "Dhule": "2", "Jalgaon": "3", "Buldhana": "4", "Akola": "5",
    "Washim": "6", "Amravati": "7", "Wardha": "8", "Nagpur": "9", "Bhandara": "10",
    "Gondia": "11", "Gadchiroli": "12", "Chandrapur": "13", "Yavatmal": "14", "Nanded": "15",
    "Hingoli": "16", "Parbhani": "17", "Jalna": "18", "Chhatrapati Sambhajinagar": "19",
    "Nashik": "20", "Thane": "21", "Mumbai Suburban": "22", "Raigad": "24", "Pune": "25",
    "Ahilyanagar": "26", "Beed": "27", "Latur": "28", "Dharashiv": "29", "Solapur": "30",
    "Satara": "31", "Ratnagiri": "32", "Sindhudurg": "33", "Kolhapur": "34", "Sangli": "35",
    "Palghar": "36",
}


class MahabhulekhClient:
    def __init__(self, timeout: int = 45):
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:155.0) "
                          "Gecko/20100101 Firefox/155.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Origin": BASE.rstrip("/"),
            "Referer": BASE,
        })
        self.form: dict[str, str] = {}
        self._load()

    # ---- ASP.NET form plumbing ---------------------------------------------
    def _load(self) -> None:
        r = self.s.get(BASE, timeout=self.timeout)
        r.raise_for_status()
        self.form = self._parse_form(r.text)

    @staticmethod
    def _parse_form(html: str) -> dict[str, str]:
        """Current values of every posted field (hidden + text + selected option + checked radio)."""
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
            if not name:
                continue
            opt = sel.find("option", selected=True) or sel.find("option")
            form[name] = (opt.get("value", "") if opt else "") or ""
        return form

    SCRIPTMANAGER = PFX + "ScriptManager1"
    UPDATEPANEL = PFX + "UpdatePanel1"

    @staticmethod
    def _parse_delta(raw: str) -> list[tuple[str, str, str]]:
        """Parse an ASP.NET AJAX partial-response: length-prefixed `len|type|id|content|` segments."""
        out, pos, n = [], 0, len(raw)
        while pos < n:
            a = raw.find("|", pos)
            if a < 0:
                break
            try:
                length = int(raw[pos:a])
            except ValueError:
                break
            b = raw.find("|", a + 1)
            c = raw.find("|", b + 1)
            if b < 0 or c < 0:
                break
            typ, idv = raw[a + 1:b], raw[b + 1:c]
            content = raw[c + 1:c + 1 + length]
            out.append((typ, idv, content))
            pos = c + 1 + length + 1
        return out

    def _postback(self, target: str, changes: dict[str, str]) -> str:
        """AJAX partial postback with __EVENTTARGET=target; refresh tokens + return the
        UpdatePanel HTML (which carries the cascaded <select> options)."""
        f = dict(self.form)
        f.update(changes)
        f[self.SCRIPTMANAGER] = f"{self.UPDATEPANEL}|{target}"
        f["__EVENTTARGET"] = target
        f["__EVENTARGUMENT"] = ""
        f["__LASTFOCUS"] = ""
        f["__ASYNCPOST"] = "true"
        f.pop(PFX + "btnSearch", None)
        r = self.s.post(BASE, data=f, timeout=self.timeout, headers={
            "X-MicrosoftAjax": "Delta=true",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        })
        r.raise_for_status()
        panel_html = ""
        for typ, idv, content in self._parse_delta(r.text):
            if typ == "hiddenField":
                f[idv] = content                       # __VIEWSTATE / __EVENTVALIDATION / etc.
            elif typ == "updatePanel":
                panel_html += content
        self.form = f                                  # keep changes + refreshed tokens
        return panel_html or r.text

    @staticmethod
    def _options(html: str, select_id: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        sel = soup.find("select", id=select_id)
        if not sel:
            return []
        out = []
        for o in sel.find_all("option"):
            v = (o.get("value") or "").strip()
            t = o.get_text(strip=True)
            if v not in PLACEHOLDERS and t not in PLACEHOLDERS:
                out.append((v, t))
        return out

    def _select_record_type(self, record_type: str) -> None:
        """Record type is an autopostback radio — select it via its own postback (setting the form
        value alone breaks the geography cascade)."""
        self.form[PFX + "rbtnULPIN"] = "Know-no"
        if record_type != "satbara":                 # 7/12 is the page default
            idx = RECORD_TYPE_INDEX[record_type]
            self._postback(f"{PFX}rbtnSelectType${idx}", {PFX + "rbtnSelectType": RECORD_TYPES[record_type]})

    # ---- ungated hierarchy --------------------------------------------------
    def districts(self) -> dict[str, str]:
        return dict(DISTRICTS)

    def talukas(self, dist_code: str, record_type: str = "property_card") -> list[tuple[str, str]]:
        self._load()
        self._select_record_type(record_type)
        html = self._postback(PFX + "ddlMainDist", {PFX + "ddlMainDist": str(dist_code)})
        return self._options(html, "ContentPlaceHolder1_ddlTalForAll")

    def villages(self, dist_code: str, tal_code: str,
                 record_type: str = "property_card") -> list[tuple[str, str]]:
        self.talukas(dist_code, record_type)            # sets district state
        html = self._postback(PFX + "ddlTalForAll", {PFX + "ddlTalForAll": str(tal_code)})
        return self._options(html, "ContentPlaceHolder1_ddlVillForAll")

    def survey_numbers(self, dist_code: str, tal_code: str, vill_code: str,
                       record_type: str = "property_card") -> list[tuple[str, str]]:
        """Attempt the survey/gat list for a village. NOTE: Mahabhulekh usually does NOT enumerate
        survey numbers — after the village you set a search-type radio and TYPE the number into
        txtcsno (maxlen 10). So this often returns [] by design; use it only to detect the rare
        case where the portal does expose a list. See docs/maharashtra_portal.md."""
        self.villages(dist_code, tal_code, record_type)  # sets district+taluka state
        html = self._postback(PFX + "ddlVillForAll", {PFX + "ddlVillForAll": str(vill_code)})
        return self._options(html, "ContentPlaceHolder1_ddlsurveyno")

    # ---- Property Card (gaothan / abadi — the SVAMITVA-equivalent record) ----
    def pc_offices(self, dist_code: str) -> list[tuple[str, str]]:
        """City-Survey / Land-Records offices (उप अधीक्षक भूमि अभिलेख) for a district — the Property
        Card hierarchy's top level (not revenue talukas)."""
        return self.talukas(dist_code, "property_card")

    def property_card_villages(self, dist_code: str) -> list[dict]:
        """Inventory of gaothan/abadi villages that HAVE a Property Card record in a district —
        the Maharashtra analog of MP's abadi village list (existence signal, ungated). Each row:
        {district_code, office_code, office, village_code, village}. City offices (urban CTS,
        e.g. Pune City) list no gaothan villages and are skipped."""
        out: list[dict] = []
        for oc, oname in self.pc_offices(dist_code):
            try:
                vills = self.villages(dist_code, oc, "property_card")
            except Exception:  # noqa: BLE001
                continue
            for vc, vn in vills:
                out.append({"district_code": str(dist_code), "office_code": oc, "office": oname,
                            "village_code": vc, "village": vn})
        return out

    def has_property_card(self, dist_code: str, village_name: str) -> bool:
        """True if a gaothan Property Card record exists for the named village in the district."""
        q = _norm(village_name)
        return any(_norm(r["village"]) == q for r in self.property_card_villages(dist_code))

    def _full_post(self, overrides: dict[str, str]) -> str:
        """A FULL (non-AJAX) postback — strips the UpdatePanel fields so btnsearchfind /
        btnmainsubmit render the whole page (an async submit returns '0|error|500||')."""
        f = {k: v for k, v in self.form.items()
             if k not in ("__ASYNCPOST", self.SCRIPTMANAGER)}
        f["__EVENTTARGET"] = ""
        f["__EVENTARGUMENT"] = ""
        f["__LASTFOCUS"] = ""
        f.update(overrides)
        r = self.s.post(BASE, data=f, timeout=self.timeout)
        r.raise_for_status()
        self.form = self._parse_form(r.text)
        return r.text

    # ---- gated record view (assisted / user-run) ---------------------------
    def fetch_record(self, dist_code: str, tal_code: str, vill_code: str, survey_no: str,
                     mobile: str, captcha: str, record_type: str = "property_card") -> str:
        """Fetch a Property Card / 7/12 record's CONTENT (owners + इतर हक्क / Other Rights).
        ASSISTED / USER-RUN: the view is gated by a mobile number + captcha, so YOU pass a mobile
        and a captcha value you have read from the page (this code does not solve the captcha).
        Steps: cascade to the village, set search type + type the survey/PC number, press Search,
        then Submit with mobile+captcha. Returns the record HTML. If the portal then demands an
        OTP, that step is manual (no OTP field is present in the base form). Parse the result with
        other_rights()."""
        self.villages(dist_code, tal_code, record_type)                 # sets district+taluka state
        self._postback(PFX + "ddlVillForAll", {PFX + "ddlVillForAll": str(vill_code)})
        # search type = survey number + typed number, then press Search (शोधा) — FULL postback
        self.form[PFX + "rbtnSearchType"] = "17"
        self.form[PFX + "ddlSelectSearchType"] = "2"
        self.form[PFX + "txtcsno"] = str(survey_no)
        self._full_post({PFX + "btnsearchfind": "Search",
                         PFX + "rbtnSearchType": "17",
                         PFX + "ddlSelectSearchType": "2",
                         PFX + "txtcsno": str(survey_no)})
        # final view: mobile + captcha + Submit — FULL postback (returns the record HTML)
        return self._full_post({PFX + "btnmainsubmit": "Submit",
                                PFX + "txtcsno": str(survey_no),
                                PFX + "txtmobile1": str(mobile),
                                PFX + "txtcaptcha": str(captcha)})


# charge / encumbrance keywords in the Maharashtra "इतर हक्क / Other Rights" section — the
# collateral signal (analog of MP RoR col 11). Free-text there, so keyword-matched.
CHARGE_KW = ["बोजा", "कर्ज", "बंधक", "बँधक", "दृष्टिबंधक", "गहाण", "तारण", "बँक", "बैंक",
             "mortgage", "hypothec", "loan", "charge", "lien", "bank", "cersai"]


def other_rights(html: str) -> tuple[bool, list[str]]:
    """(has_charge, matched_terms) from a Maharashtra 7/12 / Property Card record. Looks for a
    bank charge / boja / karj (बोजा/कर्ज/बंधक) in the Other Rights (इतर हक्क) text. Returns the
    matched keywords so a human can eyeball. VALIDATE against a real saved record (assisted) —
    the section is free-text, not a fixed column."""
    text = re.sub(r"<[^>]+>", " ", html)               # strip tags -> plain text
    text = re.sub(r"\s+", " ", text)
    low = text.lower()
    hits = []
    for kw in CHARGE_KW:
        k = kw.lower()
        if (k in low) if kw.isascii() else (kw in text):
            hits.append(kw)
    return (bool(hits), hits)


if __name__ == "__main__":
    c = MahabhulekhClient()
    print("districts loaded:", len(c.districts()))
    tals = c.talukas("25", "satbara")            # Pune, 7/12 (proven path)
    print(f"Pune 7/12 talukas: {len(tals)} e.g. {tals[:2]}")
    if tals:
        vills = c.villages("25", tals[0][0], "satbara")
        print(f"villages in {tals[0][1]}: {len(vills)} e.g. {vills[:2]}")
