# Chhattisgarh — Bhuiyan portal recon (Phase 0, 2026-09-29)

Portal: `https://revenue.cg.nic.in/bhuiyanuser/User/Selection_Report_For_KhasraDetail.aspx`
(ASP.NET WebForms + UpdatePanel; hierarchy IDs match `cg_scraper_v2.py`: `ddlDist`, `ddlTehsil`,
`ddlGram`, postbacks via `__doPostBack('<id>','')`, no `ctl00$` prefix).

## Access — open, no captcha
| step | mechanism |
|---|---|
| district → tehsil → village | UpdatePanel postbacks on `ddlDist` / `ddlTehsil` / `ddlGram` (village value = Bhuiyan village code, e.g. `6201017`; page also shows LGD code, e.g. 443166) |
| khasra lookup | JSON page method `POST Selection_Report_For_KhasraDetail.aspx/GetFruits` body `{"prefix": "<khasra prefix>", "gsrno": "<village code>"}` → `{"d": ["236/1", ...]}`. The text box only accepts an exact khasra from this list |
| khasra record | set `txtSearch` = exact khasra, press `btnSearch` (UpdatePanel) → record rendered in page |

No captcha, OTP or mobile gate anywhere on this path. Scriptable like MP.

## What the record contains
सामान्य जानकारी: khasra ID, khasra no + area, irrigated/unirrigated, **धारणाधिकार** (tenure),
owner, जोत का प्रकार (holding type). Side links per khasra:
- नक्शा → `bhunaksha.cg.nic.in/22/plotreportCG.jsp?state=22&giscode=...&plotno=...` (spatial)
- लॉग रिपोर्ट → `bhuiyanreport/User/KhasraLogReport_citizen.aspx?VillageID=..&KhasraNo=..` (change log)
- पूर्व के पंजीयन ब्योरे → `DeedDetailsKhasraWise.aspx` (registration deeds; session-scoped, open)
- **CERSAI ब्योरे → `cersai.org.in/CERSAI/asstsrch.prg?DO_SRCH_FLAG=Chattisgarh&SVN=<khasra>`** —
  external CERSAI asset search, not data on Bhuiyan
- डिजिटल हस्ताक्षरित खसरा-PII (खण्ड-1) — signed P-II; secondary sources say P-II carries a
  loan-outstanding field (not yet verified here)
- मुख्य मेनू: नामांतरण की वर्तमान स्थिति (mutation status) — not yet probed

## Findings on the SIPI ground truth
| SIPI row | khasra | Bhuiyan says |
|---|---|---|
| Balod / Balod / Khairtarai, 236 | 236/1, 3.41 ha | धारणाधिकार **आबादी भूमि**, owner "आबादी भूमि" — the **whole village abadi as one parcel** |
| Balod / Gurur / Sangli, 817 (joint=Y) | 817, 3.72 ha irrigated | धारणाधिकार **शासकीय भूमि** — government farmland, not abadi |

So SIPI CG "textual record = Y" means *a khasra record exists*, not *a household abadi record
exists*. In the abadi village checked, the abadi is a single un-subdivided government khasra
(GetFruits for `236` returns only `236/1`) — no per-household SVAMITVA parcels.

## Dhamtari check (top SVAMITVA अधिकार-अभिलेख district)
Probed Dhamtari / Dhamtari tehsil villages Arjuni (5901056), Achhota (5901132), Udena (5901031).
Heavily subdivided khasras exist (Arjuni 538 → 122 sub-plots `538/1..538/122`, house-sized
0.01–0.02 ha), but every one sampled (538/1, 538/40, 538/100, 632/5) reads:
> धारणाधिकार : **भूमिस्वामी - कृषि भूमि** (private, agricultural), जोत का प्रकार अकेला/संयुक्त.

These are ordinary bhumiswami agricultural khasras, not SVAMITVA abadi parcels. The signed
**Form P-II खण्ड-1** carries owner/holding columns only; **crop details and crop-loan (फसल ऋण)
go to P-II खण्ड-2** — that is agricultural credit, not property-card collateral. No abadi charge
field, no property-card lien field, anywhere on Bhuiyan.

## What Bhuiyan DOES expose per khasra (SIPI-relevant, non-personal)
- tenure class (आबादी / शासकीय / भूमिस्वामी-कृषि) — textual-record + land-type signal
- holding type अकेला (single) / संयुक्त (joint) — the joint-titling SIPI column
- mutation: **नामांतरण की वर्तमान स्थिति** + `DeedDetailsKhasraWise.aspx` (registration deeds) —
  mutation status IS retrievable per khasra (unlike MP)
- spatial: Bhunaksha map link (`bhunaksha.cg.nic.in/22/...`) — spatial-record signal
- external: CERSAI asset search link (off-portal), civil-court case link

## Go / no-go
- Access: **GO** (open, no captcha) — `src/cg_api.py` scrapes hierarchy + khasra records.
- Household SVAMITVA abadi records with a charge field: **NOT found** (1 abadi + 3 Dhamtari
  villages checked). CG abadi is a single govt parcel per village; no per-household cards online.
- Verdict: **CG cannot run MP's per-parcel collateral census** (no household abadi RoR to sweep).
  Applicable path = **verify the SIPI ground truth** (textual/spatial/joint/mutation via `cg_api`)
  + **denominator** (`svamitva_scraper --state 22`) + **residual-bound reconciliation** (CG not a
  named state in the loan reply). Deeper collateral question → Gujarat (72% textual) or RTI.

## Security note
A security issue on this portal was found during recon and is being reported privately through
responsible disclosure. Details are withheld from this repository until it is fixed.
