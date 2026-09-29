# Maharashtra land-records portal — recon (for the scraper)

Portal: **Mahabhulekh v2.0** — https://bhulekh.mahabhumi.gov.in/ (Bhumi Abhilekh, Revenue Dept).

Unlike MP's webgis2 (clean REST + JSON), this is an **ASP.NET WebForms** app: state lives in
`__VIEWSTATE` / `__EVENTVALIDATION`, and the cascading dropdowns fire `__doPostBack`. Dropdowns
run inside an `UpdatePanel` (AJAX partial postback), but they **degrade to a full postback** if
`__ASYNCPOST` is omitted — so the scraper uses full postbacks and parses the returned HTML
(simpler and more robust than the AJAX delta format).

## Record types (radio `ctl00$ContentPlaceHolder1$rbtnSelectType`)
| value | record |
|-------|--------|
| `SelectSatbara` | 7/12 (satbara) — agricultural |
| `Select8A` | 8A holding extract |
| `SelectPC` | **मालमत्ता पत्रक / Property Card — gaothan/abadi (rural-habitation record; SVAMITVA)** |
| `SelectKPrat` | K-Prat |

The **Property Card (`SelectPC`)** is the rural-habitation record — the Maharashtra analog of
MP's Aabadi Adhikar Abhilekh, and the target for the SIPI habitation question.

## Cascade (all full-postback, `__EVENTTARGET` = the control unique id)
```
ddlMainDist (district)  -> fills ddlTalForAll (taluka)
ddlTalForAll (taluka)   -> fills ddlVillForAll (village)
ddlVillForAll (village) -> fills ddlsurveyno   (survey/gat list)   <- existence + count signal
```
District codes are **static in the page** (native <select> `ddlMainDist`, 35 districts). Taluka /
village / survey codes come back per postback.

Field names (all prefixed `ctl00$ContentPlaceHolder1$`): `ddlMainDist`, `ddlTalForAll`,
`ddlVillForAll`, `ddlSelectSearchType` (2=सर्वे नंबर, 8=अक्षरी), `ddlsurveyno`, `txtcsno`
(survey/gat text), `ddllangforAll` (language), plus record view: `txtmobile1` (**mobile, required**),
`txtcaptcha` (**captcha**). Hidden app fields: `hfoption, hfsaltstr, hfcaptchacheck, HiddenField1..9`.

## Gates
- **Captcha** on the record view (`Images/ZC9Y.gif`, refresh via `Images/captcha-refresh.png`).
- **Mobile number required** to view a 7/12 / Property Card (likely OTP) — heavier than MP.
- The **hierarchy + survey-list** steps appear **ungated** → we can confirm a Property-Card record
  *exists* for a village and count parcels without mobile/captcha. Owner + encumbrance content
  needs the gated view (assisted, like MP's ror_sampler).

## Collateral signal (encumbrance)
- 7/12 **"इतर हक्क / Other Rights"** column carries bank charges (बोजा / कर्ज); Property Card has an
  equivalent other-rights section. This is the encumbrance field (MP col-11 analog).
- The portal shows **CERSAI** and **e-hakk (e-mutation)** integration badges — Maharashtra posts
  charges to the central mortgage registry, so the collateral question is more answerable here than
  most states (but behind the mobile/captcha gate).

## Findings from the live client (src/maha_api.py, tested)
- Cascade **works** via AJAX partial postback (length-prefixed delta): e.g. Pune (25) 7/12 →
  14 talukas → Daund → **98 villages** (18-digit village codes).
- **Record type is an autopostback radio** — it must be selected via its own postback
  (`rbtnSelectType$<idx>`); merely setting the form value breaks the geography cascade.
- **Property Card geography is different**: its "talukas" are City-Survey / Land-Records offices
  (उप अधीक्षक भूमि अभिलेख), not revenue talukas — PC is CTS/gaothan-office based. Mapping
  office → CTS/village is the next step (7/12 taluka→village is the proven path today).
- **No free survey enumeration** (unlike MP's `/plot`): after village you pick a search-type
  radio (`rbtnSearchType` 17/18, `ddlSelectSearchType` 2=सर्वे,8=अक्षरी) and **type** the
  survey/gat number into `txtcsno` (maxlen 10). So there is no ungated per-village parcel list to
  count — existence is confirmed per *known* survey number, then the gated view.
- Placeholders seen: `--निवडा--` and `--Select Option--`.

## Scraper plan (mirrors the MP layers)
- `src/maha_api.py` — MahabhulekhClient: full-postback cascade → talukas/villages/survey_numbers
  (ungated). Record view stub is assisted (mobile+captcha), user-run.
- Denominator/existence: iterate survey lists per village (Property Card) → parcel counts.
- Collateral: assisted record fetch → parse Other Rights for बोजा/कर्ज (the col-11 analog).
