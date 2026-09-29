# Gujarat — AnyRoR portal recon (Phase 0, 2026-09-29)

Portal: `https://anyror.gujarat.gov.in/` (Revenue Dept, NIC Gujarat). ASP.NET WebForms.
Rural land record: `LandRecordRural.aspx`.

## Record types (rural)
`ContentPlaceHolder1_drpLandRecord` offers, among others:
- **VF-7 SURVEY NO DETAILS (ગા.ન. ૭)** value=1 — the 7/12 RoR (survey-no record). Carries owner +
  other-rights; Gujarat records **બોજો (boja = charge/encumbrance)** and mutation refs here.
- **VF-8A KHATA (ગા.ન. ૮અ)** value=2 — khata (holding) record.
- **VF-6 ENTRY DETAILS (હક્ક પત્રક ગા.ન. ૬)** value=3 — **mutation register** (retrievable, unlike MP).
- 135-D mutation notice, integrated survey details, revenue-case details, e-Chavdi, etc.
Also on the home menu: **digitally sealed Property Card** and **digitally signed gaam-namuna** —
the City-Survey / gamtal (abadi) records, separate from rural VF-7.

## Gating — MH-class (captcha on the record view)
| step | gating |
|---|---|
| record type → district → taluka → village → survey no | **ungated** ASP.NET postback cascade. Verified: district અમદાવાદ(07) → 16 talukas incl. દશક્રોઈ (Daskroi) |
| **Get Record Detail (btnGo)** | **CAPTCHA** — `txt_captcha_1` + image `i_captcha_1`. Required to render the VF-7/VF-6 record |

So the hierarchy (frame building) is scriptable, but the actual encumbrance read is behind a
per-fetch captcha — same class as Maharashtra Mahabhulekh, unlike MP/CG (which were open).

Geography is Gujarati script; the SIPI sheet is English → same transliterate + fuzzy match as CG
(sanscript GUJARATI + rapidfuzz). SIPI GJ survey nos are `SV###` (survey numbers) and `Pack`
notation; researchers used rural VF-7 by survey no.

## SIPI ground truth (from the sheet)
Gujarat: 131 rows, textual **91/126** Y (2nd highest after MP), spatial 0/131, joint 4/131.

## Go / no-go
- Access: hierarchy **GO** (ungated); record view **captcha-gated** (I cannot solve captchas).
- Encumbrance field: VF-7 is expected to carry **બોજો** — confirmation needs one captcha-solved
  record (user solves, MH-style).
- Verdict: **MH path**, not MP. Denominator (svamitva.nic.in DWR, `--state 24`, ungated) + AnyRoR
  cascade frame (ungated) are automatable; the boja read is a **captcha-assisted small sample**,
  and the headline numerator is the **residual bound** (GJ not separately named in the loan reply).
  Mutation (VF-6) is retrievable, a bonus over MP.

## Next steps
1. Denominator: `svamitva_scraper --state 24` → data/gj/.
2. Frame: AnyRoR cascade (ungated) → one gamtal/abadi + sample survey per district.
3. Sample: captcha-assisted VF-7 fetch (user solves captcha) → read બોજો; throwaway inputs where
   the portal does not verify them.
4. Reconcile: residual-bound numerator + sample, mirroring `maha_reconcile.py`.
