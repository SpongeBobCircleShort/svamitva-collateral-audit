# SVAMITVA Collateral-Vetting System — Madhya Pradesh

Vets the claim that SVAMITVA property cards give rural owners **usable loan collateral**, by
triangulating three evidence layers and showing the result in an interactive dashboard.

## The verdict (current)

- **4,324,175** cards issued (52 districts, 35,899 villages) — scraped in full.
- **2,202** loans recorded against them (₹177.77 cr), Lok Sabha / Min. of Panchayati Raj, as on 2026-08-05.
- **Uptake ≈ 0.051% — one loan per ~1,963 cards.** On the official numerator, the collateral
  claim is largely unrealised. The sample layer refines this with a measured RoR encumbrance rate.

## Architecture

```
L1 DENOMINATOR  svamitva_scraper.py  -> cards per village (census)        [done]
L2 AGGREGATE    aggregate_numerator.py -> official loans (state)          [done]
L3 SAMPLE       ror_sampler.py       -> RoR col-11 for 396-village holdout [user-run]
L4 ESTIMATOR    estimator.py         -> extrapolated rate + CI, cross-check [done]
   build_dataset.py -> mp_vetting / district_vetting / state_summary
   dashboard.py     -> triangulated Streamlit UI
```

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
python src/build_dataset.py && streamlit run src/dashboard.py   # rebuild with sample+estimate
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
