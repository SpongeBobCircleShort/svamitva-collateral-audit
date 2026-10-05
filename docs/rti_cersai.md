# RTI — CERSAI, SVAMITVA card-backed security interests (national, state-wise)

CERSAI's live search is login+captcha+fee gated and per-asset, so the card-backed charge count
cannot be scraped (see `docs/cersai_recon.md`). CERSAI is a Government company (Dept of Financial
Services, Ministry of Finance) and is therefore a public authority under the RTI Act, 2005. A single
RTI can obtain the card-backed charge numerator for the entire country, decomposed by state and
year — the national analog of the MP mutation RTI kit.

## Where to file
- **PIO / CPIO, CERSAI (Central Registry of Securitisation Asset Reconstruction and Security
  Interest of India)**, Registered Office, New Delhi. File online via the DoFS / CERSAI RTI channel
  or by post with the ₹10 fee (IPO / DD / court-fee stamp; BPL exempt).
- If CERSAI holds the data only in aggregate, request it aggregate; if it declines on "no such
  compiled record" grounds, the fallback is the residual bound already in hand.

## What to ask (the four points the generator fills in)
1. Total number of security interests registered with CERSAI where the underlying collateral is a
   property covered by the **SVAMITVA scheme** (rural abadi / gaothan residential property /
   property card / sannad / gharauni), **year-wise** since 2021.
2. The same count **broken down by State/UT**.
3. The count where such SVAMITVA property was pledged for a **loan** (security interest for a
   financial facility), vs. any other registration type.
4. Whether CERSAI tags or can identify SVAMITVA/abadi collateral distinctly in its registry; if
   not, a statement to that effect (itself a finding — the charge is not separable).

## Reuse
Generator mirrors the MP RTI kit (`src/build_rti.py`, `docs/rti_mutation_mp.md` on branch
`sipi-mp-verification`): a template BODY + applicant placeholders → `data/rti_filled/RTI_CERSAI.md`.
One filing, national scope (contrast the MP kit's 55 district filings).
