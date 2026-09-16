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

# ---------------------------------------------------------------- headline
vetted = s.get("numerator_vetted", False)
k = st.columns(4)
k[0].metric("Cards issued", f"{s['cards_total']:,}", help="Scraped census — vetted")
k[1].metric("Villages", f"{s['villages_total']:,}")
if vetted:
    k[2].metric("Loans against cards", f"{s['official_loans']:,}",
                help=f"as on {s['official_as_of']}")
    k[3].metric("Uptake rate", f"{s['uptake_rate_pct']}%")
    st.warning(
        f"Of **{s['cards_total']:,}** cards issued, **{s['official_loans']:,}** loans are recorded "
        f"against them — about **1 loan per {s['cards_per_loan']:,} cards** ({s['uptake_rate_pct']}%).")
else:
    k[2].metric("Loans against cards (MP)", "not vetted")
    k[3].metric("Uptake rate", "—")
    st.info(
        "**MP loan figure removed as unverified.** The only state-wise loan number available "
        "traced to a single secondary report with an unresolved House attribution and no retrievable "
        "primary document, so it has been pulled from this dashboard. What remains below is **directly "
        "vetted**: the card census (scraped from svamitva.nic.in) and the sampling method. The loan "
        "numerator will return once it is confirmed against a primary source or the RoR sample.")
    nc = s.get("national_context")
    if nc:
        st.caption(
            f"National context only (not an MP figure): the Ministry of Panchayati Raj reported "
            f"**{nc['loans']:,} loans / ₹{nc['amount_cr']:.0f} cr** nationwide against SVAMITVA cards, "
            f"as on {nc['as_of']} ([wire report]({nc['url']})).")

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
        st.metric("Sampled encumbrance rate", f"{p*100:.2f}%",
                  help="parcels with a loan on the RoR (col 11) ÷ parcels checked")
        st.caption(f"**{withloan:,} of {checked:,} parcels** across "
                   f"{done} districts carried any loan/charge on record — 95% upper bound "
                   f"**{hi*100:.2f}%**.")
        if withloan == 0:
            st.caption("⚠️ Zero across the frame sample **and** a ~2,800-parcel positive-control "
                       "search (largest settlements + every parcel of a PM-showcased loan village). "
                       "The encumbrance field exists only in the abadi RoR प्ररूप तीन col 11 "
                       "(विल्लंगम/बंधक); the agricultural khatauni प्ररूप सात has no mortgage column, "
                       "and ror-detail JSON carries no charge field. **Limit:** the free RoR is a "
                       "'specimen copy' — col 11 may be populated only in the paid signed copy, so "
                       "this is 'no encumbrance visible in the public record', not a proven zero.")
    else:
        frame = s.get("sample_frame", "sample frame")
        st.info(f"Sample not collected yet. Run `python src/ror_sampler.py` to fill the **{target}-village "
                f"{frame}** from RoR column 11 (बंधक / दृष्टिबंधक / भू-ऋण). Until then this stays "
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
nc = s.get("national_context")
num_line = (f"- **Numerator (L2)** — {s['official_loans']:,} loans / ₹{s['official_amount_cr']:.2f} cr, "
            f"as on {s['official_as_of']} ([source]({s['official_source_url']}))."
            if vetted else
            "- **Numerator (L2)** — *removed as unverified.* No vetted MP loan figure exists; the "
            "only state-wise number came from a single secondary report and was pulled."
            + (f" National context (not MP): {nc['loans']:,} loans / ₹{nc['amount_cr']:.0f} cr, "
               f"as on {nc['as_of']} ([wire]({nc['url']}))." if nc else ""))
with st.expander("Method, sources & limits"):
    st.markdown(f"""
- **Denominator (L1)** — {s['cards_total']:,} cards across {s['villages_total']:,} villages,
  scraped from svamitva.nic.in (state 23), keyed by LGD village code. **Directly vetted.**
{num_line}
- **Sample (L3)** — RoR column 11 (बंधक/दृष्टिबंधक/भू-ऋण) for the **MP one-village-per-district
  frame** (55 districts, HQ-anchored); aggregate-only, **no owner PII stored**. Not yet collected.
- **What counts as vetted here** — only figures scraped directly or confirmed against a primary/
  wire source. Provisional secondary numbers are excluded from the headline, not shown as fact.
- **Limits** — per-parcel RoR is captcha/replay-gated → sample not census; district-wise official
  loans are unpublished; "specimen copy" data is real but legally non-usable.
""")
