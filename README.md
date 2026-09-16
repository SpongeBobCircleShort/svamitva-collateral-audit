# SVAMITVA Collateral-Vetting System — Madhya Pradesh

Vets the claim that SVAMITVA property cards give rural owners **usable loan collateral**, by
triangulating three evidence layers and showing the result in an interactive dashboard.

## The verdict (current)

- **4,324,175** cards issued (52 districts, 35,899 villages) — scraped in full, vetted.
- **0 registered charges** across **2,667** abadi parcels checked (1,647 one-per-district frame +
  a 1,020-parcel full census of Handia). The encumbrance field exists only in the abadi RoR
  प्ररूप तीन col 11 (विल्लंगम/बंधक); the agricultural khatauni प्ररूप सात has no mortgage column;
  the `ror-detail` JSON has no charge field. The "specimen copy" watermark is a legal-admissibility
  disclaimer, not a data redaction — so this is a real zero.
- **Main-claim reconciliation (L5):** the government claims SVAMITVA loans exist (11,147 national,
  vetted; MP 2,202, its own unvetted claim) — yet **zero appear as charges on the record**,
  including a full census of Handia, where **Pawan's ₹2.90 lakh loan is documented** (PM interaction).
  A provably-existing loan absent from its whole village's records ⟹ **the card's collateral is
  nominal — not registered on the title.** The land record cannot confirm a single card is pledged.

## Architecture

```
L1 DENOMINATOR  svamitva_scraper.py  -> cards per village (census)        [done]
L2 AGGREGATE    aggregate_numerator.py -> official loans (state)          [done]
L3 SAMPLE       ror_sampler.py       -> RoR col-11 for 396-village holdout [user-run]
L4 ESTIMATOR    estimator.py         -> extrapolated rate + CI, cross-check [done]
L5 RECONCILE    reconcile.py         -> official numerator vs RoR ground truth [done]
   build_dataset.py -> mp_vetting / district_vetting / state_summary (+reconciliation)
   dashboard.py     -> triangulated Streamlit UI
```

**L5 reconciliation** is the main-claim test: it puts the government's own loan count beside the
RoR encumbrance ground truth (0). `official loans > 0 AND registered charges = 0 ⟹` the loans are
not secured by the card as a title lien ⟹ collateral is nominal. The decisive input is the
**known case** in `data/known_loans.csv` (a documented loan whose entire village was censused,
0 charges); the random sample alone is underpowered at the claimed uptake rate (see the Poisson
power note the module prints). `data/col11_audit.csv` (git-ignored) is the ad-hoc
positive-control sweep from `loan_hunter.py`.

## Setup
```bash
pip install -r requirements.txt
python -m playwright install chromium     # for the sampler / request-id mint
```

## Run
```bash
python src/svamitva_scraper.py        # L1 denominator (done; ~30 min if re-run)
python src/aggregate_numerator.py     # L2 seeds data/aggregate_loans.csv
python src/train_test_split.py        # 35,503 train / 396 test holdout
python src/build_dataset.py           # merge -> mp_vetting / district_vetting / state_summary
streamlit run src/dashboard.py        # the verdict dashboard
# L3 (fills the holdout, on your India network):
python src/ror_sampler.py             # captcha-assisted RoR sampling of the 396 test villages
python src/estimator.py               # L4 extrapolate + cross-check, writes estimates.parquet
python src/reconcile.py               # L5 main-claim reconciliation, writes reconciliation.json
python src/build_dataset.py && streamlit run src/dashboard.py   # rebuild with sample+estimate+reconcile
# positive-control search (on your India network) — hunt any charged parcel / a named beneficiary:
python src/loan_hunter.py --districts HARDA --village Handia --match पवन
```

## Files
| file | role |
|------|------|
| `src/dwr.py` | SVAMITVA DWR client + parser |
| `src/svamitva_scraper.py` | L1 cards per village |
| `src/aggregate_numerator.py` | L2 official loans (curated `data/aggregate_loans.csv`) |
| `src/bhulekh_api.py` | webgis2 client (district/tehsil/village/plot; request-id auto-mint) |
| `src/verify_ror.py` | one-shot RoR schema probe |
| `src/ror_sampler.py` | L3 captcha-assisted RoR encumbrance sampler (396 holdout) |
| `src/train_test_split.py` | stratified split + `vet_worklist.csv` |
| `src/estimator.py` | L4 stratified estimate + Wilson CIs + cross-check |
| `src/reconcile.py` | L5 main-claim reconciliation (official numerator vs RoR), `reconciliation.json` |
| `src/loan_hunter.py` | positive-control search: sweep parcels / match a named beneficiary, `col11_audit.csv` |
| `src/capture_ror.py` / `src/capture_khasra.py` | one-shot endpoint capture (abadi RoR / regular khasra) |
| `data/known_loans.csv` | documented loans + full-census charge counts (reconciliation input) |
| `src/build_dataset.py` | merge all layers |
| `src/dashboard.py` | Streamlit dashboard |

## Data model
- `data/mp_vetting.parquet` — village grain: cards, split, sampled plots.
- `data/district_vetting.parquet` — district grain: cards, official loans, sample, estimate.
- `data/state_summary.json` — headline verdict.
- `data/aggregate_loans.csv` — editable official-loan source of truth (add district rows as found).

## Honest limits
- Per-parcel RoR loan data is **captcha + replay-gated** → **sample, not census**; coverage shown.
- District-wise official loans are **not published** — only the state total exists.
- RoR encumbrance = **any** charge (upper bound); official loans = **card-backed** (precise) → the
  dashboard **brackets** the truth rather than forcing one number.
- "Specimen copy" RoR data is real but legally non-usable; used for statistics only. **No PII stored.**
```
