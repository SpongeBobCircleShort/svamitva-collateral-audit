"""
Merge the vetting layers into the datasets the dashboard reads.

  L1 svamitva_cards.parquet    (required)  cards per village (denominator)
  L2 aggregate_loans.csv       (seeded)    official loans against cards (state; district if added)
  L3 vet_worklist.csv          (optional)  sampled RoR encumbrance for the 396 test villages
  L4 estimates.parquet         (optional)  stratified encumbrance estimate + CI (from estimator.py)

Outputs:
  data/mp_svamitva.parquet     village grain (kept for train_test_split compatibility)
  data/mp_vetting.parquet      village grain + split + sample labels
  data/district_vetting.parquet district grain: cards, official loans, sample, estimate
  data/state_summary.json      the headline verdict numbers

Uncrawled/unsampled villages stay NaN -> the dashboard reads them as "unknown", never "no loan".
"""
from __future__ import annotations

import os
import json
import argparse
import pandas as pd

try:
    from aggregate_numerator import load as load_aggregate, mp_state_total, national_context
except ImportError:
    from src.aggregate_numerator import load as load_aggregate, mp_state_total, national_context


def _read_sample(data_dir: str) -> pd.DataFrame:
    """Sampled RoR labels from the worklist, if any rows have been filled."""
    path = os.path.join(data_dir, "vet_worklist.csv")
    cols = ["lgd_village_code", "plots_checked", "plots_with_loan"]
    if not os.path.exists(path):
        return pd.DataFrame(columns=cols)
    w = pd.read_csv(path)
    if "lgd_code" in w.columns:
        w = w.rename(columns={"lgd_code": "lgd_village_code"})
    for c in ("plots_checked", "plots_with_loan"):
        w[c] = pd.to_numeric(w.get(c), errors="coerce")
    w = w[w["plots_checked"].fillna(0) > 0]  # only filled rows
    return w[cols] if len(w) else pd.DataFrame(columns=cols)


def build(data_dir: str) -> None:
    cards = pd.read_parquet(os.path.join(data_dir, "svamitva_cards.parquet"))

    # ---- village grain (denominator + optional sample) ----------------------
    sample = _read_sample(data_dir)
    df = cards.merge(sample, on="lgd_village_code", how="left")
    df["sampled"] = df["plots_checked"].notna() if "plots_checked" in df else False
    df["village_enc_rate"] = (df["plots_with_loan"] / df["plots_checked"]).where(df["sampled"]) \
        if "plots_with_loan" in df else pd.NA

    # keep legacy output for train_test_split.py
    df.to_parquet(os.path.join(data_dir, "mp_svamitva.parquet"), index=False)

    # attach split if it exists (train_test_split.py already ran)
    split_path = os.path.join(data_dir, "test.parquet")
    if os.path.exists(split_path):
        test_codes = set(pd.read_parquet(split_path)["lgd_village_code"])
        df["split"] = df["lgd_village_code"].map(lambda c: "test" if c in test_codes else "train")
    df.to_parquet(os.path.join(data_dir, "mp_vetting.parquet"), index=False)

    # ---- district grain -----------------------------------------------------
    dist = df.groupby(["district_code", "district_en"], as_index=False).agg(
        villages=("lgd_village_code", "count"),
        cards=("cards_distributed", "sum"),
        sampled_villages=("sampled", "sum"),
        plots_checked=("plots_checked", "sum"),
        plots_with_loan=("plots_with_loan", "sum"),
    )
    dist["cards"] = dist["cards"].fillna(0).astype(int)
    _den = dist["plots_checked"].where(dist["plots_checked"].fillna(0) > 0)
    dist["sampled_rate"] = dist["plots_with_loan"] / _den

    # official district loans, only VETTED district rows (none published today)
    agg = load_aggregate(data_dir)
    dloans = agg[(agg["level"] == "district") & agg["vetted"]][
        ["district", "loans_count", "loan_amount_cr"]]
    if len(dloans):
        dist = dist.merge(dloans.rename(columns={"district": "district_en",
                                                 "loans_count": "official_loans",
                                                 "loan_amount_cr": "official_amount_cr"}),
                          on="district_en", how="left")
    else:
        dist["official_loans"] = pd.NA
        dist["official_amount_cr"] = pd.NA

    # stratified estimate, if estimator.py has run
    est_path = os.path.join(data_dir, "estimates.parquet")
    if os.path.exists(est_path):
        est = pd.read_parquet(est_path)  # district_en, est_encumbered, ci_low, ci_high
        dist = dist.merge(est, on="district_en", how="left")

    dist = dist.sort_values("cards", ascending=False)
    dist.to_parquet(os.path.join(data_dir, "district_vetting.parquet"), index=False)

    # ---- state summary --------------------------------------------------------
    # Only VETTED numbers drive the site. There is no vetted MP loan figure, so the
    # loan-side verdict is deliberately null; the vetted national total is carried
    # separately as clearly-labelled external context (not an MP verdict).
    mp = mp_state_total(data_dir)          # None -> MP numerator unvetted
    nat = national_context(data_dir)
    cards_total = int(df["cards_distributed"].fillna(0).sum())
    loans = mp["loans_count"] if mp else None
    summary = {
        "cards_total": cards_total,
        "villages_total": int(len(df)),
        "official_loans": loans,
        "official_amount_cr": (mp["loan_amount_cr"] if mp else None),
        "official_as_of": (mp["as_of"] if mp else None),
        "official_source_url": (mp["url"] if mp else None),
        "uptake_rate_pct": (round(loans / cards_total * 100, 4) if (loans and cards_total) else None),
        "cards_per_loan": (int(cards_total // loans) if loans else None),
        "numerator_vetted": bool(mp),
        "national_context": ({"loans": nat["loans_count"], "amount_cr": nat["loan_amount_cr"],
                              "as_of": nat["as_of"], "url": nat["url"]} if nat else None),
        "sample_villages_target": int((df.get("split") == "test").sum()) if "split" in df else 0,
        "sample_villages_done": int(df["sampled"].sum()),
        "sample_plots_checked": int(df["plots_checked"].fillna(0).sum()) if "plots_checked" in df else 0,
        "sample_plots_with_loan": int(df["plots_with_loan"].fillna(0).sum()) if "plots_with_loan" in df else 0,
    }
    with open(os.path.join(data_dir, "state_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    print(f"villages={summary['villages_total']:,}  cards={cards_total:,}")
    print("MP loan numerator: " + (f"{loans:,} (VETTED)" if mp else "UNVETTED — excluded from verdict"))
    if nat:
        print(f"national context (labelled, not a verdict): {nat['loans_count']:,} loans / Rs {nat['loan_amount_cr']:.0f} cr")
    print("-> mp_vetting.parquet, district_vetting.parquet, state_summary.json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    build(ap.parse_args().data_dir)
