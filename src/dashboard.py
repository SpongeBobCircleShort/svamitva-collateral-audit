"""
SVAMITVA Collateral-Vetting Dashboard — Madhya Pradesh.

Vetting question: the government says SVAMITVA property cards give rural owners usable
collateral. Do the loans actually exist? This triangulates:
  L1 cards issued (census, svamitva.nic.in)          -> the exposure / denominator
  L2 loans against cards (official, Lok Sabha/MoPR)   -> the headline numerator
  L3 RoR encumbrance sample (396-village holdout)     -> ground-truth rate + CI
  L4 stratified estimate (extrapolated, cross-checked against L2)

Run:  streamlit run src/dashboard.py
"""
from __future__ import annotations

import os
import json
import math
import pandas as pd
import streamlit as st

DATA = os.environ.get("VETTING_DATA_DIR", "data")
st.set_page_config(page_title="SVAMITVA Collateral Vetting — MP", layout="wide")


@st.cache_data
def load():
    sp = os.path.join(DATA, "state_summary.json")
    if not os.path.exists(sp):
        return None, None, None
    summary = json.load(open(sp))
    dist = pd.read_parquet(os.path.join(DATA, "district_vetting.parquet"))
    vil = pd.read_parquet(os.path.join(DATA, "mp_vetting.parquet"))
    return summary, dist, vil


def wilson(pos: int, n: int, z: float = 1.96):
    """Wilson score interval for a proportion; returns (rate, lo, hi)."""
    if n == 0:
        return None, None, None
    p = pos / n
    d = 1 + z**2 / n
    c = p + z**2 / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return p, (c - m) / d, (c + m) / d


s, dist, vil = load()
st.title("SVAMITVA Collateral Vetting — Madhya Pradesh")
st.caption("Government claim: property cards are usable loan collateral. "
           "This measures whether the loans actually exist.")

if s is None:
    st.error("No dataset. Run: `python src/svamitva_scraper.py` → "
             "`python src/aggregate_numerator.py` → `python src/build_dataset.py`")
    st.stop()

# ---------------------------------------------------------------- headline verdict
k = st.columns(5)
k[0].metric("Cards issued", f"{s['cards_total']:,}")
k[1].metric("Loans against cards", f"{s['official_loans']:,}",
            help=f"Official (Lok Sabha / MoPR), as on {s['official_as_of']}")
k[2].metric("Uptake rate", f"{s['uptake_rate_pct']}%")
k[3].metric("Cards per loan", f"{s['cards_per_loan']:,}")
k[4].metric("Loan value", f"₹{s['official_amount_cr']:.0f} cr")

rate = s["uptake_rate_pct"]
verdict = ("**collateral claim largely unrealised**" if rate is not None and rate < 1
           else "**partial uptake**")
st.warning(
    f"Of **{s['cards_total']:,}** SVAMITVA cards issued in MP, only **{s['official_loans']:,}** "
    f"loans are recorded against them (₹{s['official_amount_cr']:.0f} cr) — about **1 loan per "
    f"{s['cards_per_loan']:,} cards** ({rate}%). On the official numerator, the {verdict}.")

st.divider()

# ---------------------------------------------------------------- ground-truth sample
st.subheader("Ground-truth sample (RoR encumbrance)")
done, target = s["sample_villages_done"], s["sample_villages_target"]
checked, withloan = s["sample_plots_checked"], s["sample_plots_with_loan"]
c1, c2 = st.columns([1, 2])
with c1:
    st.progress(done / target if target else 0.0,
                text=f"{done}/{target} holdout villages sampled")
with c2:
    if checked:
        p, lo, hi = wilson(withloan, checked)
        st.metric("Sampled encumbrance rate",
                  f"{p*100:.2f}%", help="parcels with a loan on the RoR (col 11) ÷ parcels checked")
        st.caption(f"95% CI: {lo*100:.2f}% – {hi*100:.2f}%  ({withloan:,}/{checked:,} plots)")
    else:
        st.info("Sample not collected yet. Run `python src/ror_sampler.py` (fills the 396-village "
                "holdout from RoR column 11: बंधक / दृष्टिबंधक / भू-ऋण). Until then this stays "
                "**unknown**, never zero.")

# cross-check panel (only once estimator has run)
if "est_encumbered" in dist.columns and dist["est_encumbered"].notna().any():
    est_total = int(dist["est_encumbered"].sum())
    st.subheader("Cross-check: sampled estimate vs official")
    cc = st.columns(3)
    cc[0].metric("Estimated encumbered (sample→all)", f"{est_total:,}")
    cc[1].metric("Official loans", f"{s['official_loans']:,}")
    ratio = est_total / s["official_loans"] if s["official_loans"] else float("nan")
    cc[2].metric("Estimate ÷ official", f"{ratio:.1f}×")
    st.caption("RoR encumbrance counts **any** charge (upper bound on card-collateral); official "
               "counts **card-backed** loans (precise). The truth is bracketed between them.")

st.divider()

# ---------------------------------------------------------------- district view
st.subheader("By district — card exposure")
show = dist.copy()
show["cards"] = show["cards"].astype(int)
cols = ["district_en", "villages", "cards", "sampled_villages"]
if show["sampled_rate"].notna().any():
    show["sampled_rate_%"] = (show["sampled_rate"] * 100).round(2)
    cols.append("sampled_rate_%")
if show["official_loans"].notna().any():
    cols.append("official_loans")
st.dataframe(show[cols], use_container_width=True, hide_index=True,
             column_config={"district_en": "District", "cards": "Cards issued",
                            "sampled_villages": "Villages sampled",
                            "sampled_rate_%": "Sampled encumb. %",
                            "official_loans": "Official loans"})
st.bar_chart(show.set_index("district_en")["cards"], height=340)
st.caption("District-wise **official** loan counts are not published by the state — only the "
           "state total exists. This view shows card exposure; loans are filled per-district only "
           "if added to `aggregate_loans.csv`.")

st.divider()

# ---------------------------------------------------------------- drilldown
st.subheader("Drill down")
d1, d2 = st.columns(2)
dsel = d1.selectbox("District", sorted(vil.district_en.unique()))
vd = vil[vil.district_en == dsel]
bsel = d2.selectbox("Block", ["(all)"] + sorted(vd.block_en.dropna().unique()))
if bsel != "(all)":
    vd = vd[vd.block_en == bsel]
vcols = ["block_en", "village_en", "village_hi", "cards_distributed", "properties_total"]
if "split" in vd.columns:
    vcols.append("split")
if "village_enc_rate" in vd.columns and vd["village_enc_rate"].notna().any():
    vd = vd.copy(); vd["enc_%"] = (vd["village_enc_rate"] * 100).round(1); vcols.append("enc_%")
vshow = vd[vcols].sort_values("cards_distributed", ascending=False)
st.dataframe(vshow, use_container_width=True, hide_index=True,
             column_config={"block_en": "Block", "village_en": "Village", "village_hi": "गाँव",
                            "cards_distributed": "Cards", "properties_total": "Properties",
                            "split": "Split", "enc_%": "Encumb. %"})
st.download_button("Download this view (CSV)", vshow.to_csv(index=False).encode(),
                   file_name=f"svamitva_{dsel}_{bsel}.csv", mime="text/csv")

# ---------------------------------------------------------------- method / limits
with st.expander("Method, sources & limits"):
    st.markdown(f"""
- **Denominator (L1)** — {s['cards_total']:,} cards across {s['villages_total']:,} villages,
  scraped from svamitva.nic.in (state 23), keyed by LGD village code.
- **Numerator (L2)** — {s['official_loans']:,} loans / ₹{s['official_amount_cr']:.2f} cr against
  SVAMITVA cards, Lok Sabha / Ministry of Panchayati Raj, as on {s['official_as_of']}
  ([source]({s['official_source_url']})).
- **Sample (L3)** — RoR column 11 (बंधक/दृष्टिबंधक/भू-ऋण) for a 396-village stratified holdout
  (95% CI, ±5%); aggregate-only, **no owner PII stored**.
- **Bracketing** — RoR encumbrance = *any* charge (upper bound); official loans = *card-backed*
  (precise). Report both; don't force one number.
- **Limits** — per-parcel RoR is captcha/replay-gated → sample not census; district-wise official
  loans are unpublished; "specimen copy" data is real but legally non-usable.
""")
