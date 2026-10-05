# CERSAI recon — the national charge registry (2026-09-30)

## Why CERSAI
Across the four states audited, only **Madhya Pradesh** records a charge/lien on the open land
record (RoR col-11). Maharashtra, Gujarat and Chhattisgarh all route encumbrance to **CERSAI**
(Central Registry of Securitisation Asset Reconstruction and Security Interest of India) — the
national registry of security interests under the SARFAESI Act, 2002 (operational 2011). Every
bank/NBFC/HFC charge on a property is meant to be registered here. So CERSAI, not any single state
portal, is where a SVAMITVA card-backed loan charge would actually appear — one national source
instead of 28 state portals.

## Access — gated, not a public census
`cersai.org.in` (`asstsrch.prg`, `home.prg`, `downloads.prg`):
| feature | state |
|---|---|
| Asset / Borrower / AOR based search | **login + registration required** |
| Login | **captcha-gated** |
| Search | **fee-based** (₹10+ per search), per-asset/per-borrower |
| Homepage / downloads | JavaScript (Vue) app; counters + notices, no bulk export |

So CERSAI's live search is **not** scrapeable for a per-parcel or per-state census — it needs an
account, a captcha and a per-search fee, and returns one asset/borrower at a time.

## Negative-census finding (this matters)
There is **no public per-parcel charge census** for the gated states — not on the state portal
(captcha/login) and not on CERSAI (login+captcha+fee). Where a property-card charge exists at all,
it is only verifiable behind a paywalled/gated registry. This strengthens the audit's core
conclusion: card-as-collateral is **nominal and not publicly on-record**. MP is the outlier that
put the charge on the open record; it does not generalise.

## Public aggregates (all-asset, context only)
CERSAI publishes national counters and annual reports. These are **all-asset totals, NOT
SVAMITVA-specific** — useful only as scale context (registry holds millions of subsisting
security interests across all property types). Captured (clearly labelled, unvetted) in
`data/cersai_stats.csv`. The SVAMITVA-specific card-backed count is **not** in any public
breakdown seen.

## The lever — RTI to CERSAI
CERSAI is a Government company (Dept of Financial Services, Ministry of Finance) → subject to the
RTI Act. One RTI can request the count of registered security interests whose underlying collateral
is **SVAMITVA property-card / rural abadi residential land**, broken down by **state and year** —
the card-backed charge numerator for the whole country in a single filing. See
`docs/rti_cersai.md` + `src/build_cersai_rti.py` → `data/rti_filled/RTI_CERSAI.md`.

## Cross-check already in hand
The parliamentary reply (national **11,147** SVAMITVA-backed loans, 2026-08-05) is effectively the
government's own count of the card-backed subset. Against ~2.42 crore cards issued, that is a
card-backed rate of ~**0.046%** (11,147 / 24,200,000) — the nominal-collateral verdict at the
national level, independent of any per-state census. A CERSAI RTI reply would corroborate/decompose
this by state.

## Honest limits
- Live CERSAI search: login+captcha+fee → no scraped census.
- Public aggregates are all-asset, not SVAMITVA-tagged → only the RTI narrows to card-backed.
- CERSAI counts *registered security interests*; a card used only as KYC for an unsecured
  MUDRA/KCC loan never appears — consistent with "collateral nominal / not on title".
- RTI latency is weeks; residual bounds (≤99/unnamed state) + the 11,147 figure stand meanwhile.
