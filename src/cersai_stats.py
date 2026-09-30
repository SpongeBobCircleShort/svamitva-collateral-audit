"""
CERSAI published aggregates — national scale context for the charge registry.

IMPORTANT: these are ALL-ASSET totals across every property type registered under SARFAESI. They
are NOT SVAMITVA-specific and must never be read as card-backed loan counts. They exist only to show
the registry's scale and to frame the RTI ask (docs/rti_cersai.md). The SVAMITVA-specific,
card-backed numerator remains the parliamentary figure (11,147, see aggregate_numerator) until a
CERSAI RTI returns a card-tagged breakdown.

Provenance is explicit and every row is flagged vetted=False (secondary / portal-counter snapshot),
mirroring aggregate_numerator's honesty rules.

Usage:  python src/cersai_stats.py     # seed + print
"""
from __future__ import annotations

import os
import argparse
import pandas as pd

COLUMNS = ["metric", "value", "scope", "as_of", "source", "url", "vetted", "note"]

_PORTAL = "https://www.cersai.org.in/"
_WIKI = "https://en.wikipedia.org/wiki/Central_Registry_of_Securitisation_Asset_Reconstruction_and_Security_Interest"

# All-asset registry counters as reported on the CERSAI portal / secondary summaries (2026-09).
# Recorded as context ONLY; unvetted; not SVAMITVA-specific.
SEED = [
    ["subsisting_registrations", 5552909, "all-asset (every property type, all India)", "2026-09",
     "CERSAI portal counters (as reported)", _PORTAL, False,
     "ALL-ASSET total under SARFAESI — NOT SVAMITVA/card-backed; scale context only"],
    ["registered_institutions", 292, "all-asset (banks/NBFC/HFC etc.)", "2026-09",
     "CERSAI portal counters (as reported)", _PORTAL, False, "lenders registered with CERSAI"],
    ["fee_based_transactions", 1861189, "all-asset", "2026-09",
     "CERSAI portal counters (as reported)", _PORTAL, False, "cumulative fee-based search/registration txns"],
    ["registry_basis", "SARFAESI Act 2002; operational 2011", "national", "2026-09",
     "CERSAI / Wikipedia", _WIKI, False, "legal basis + go-live"],
]


def seed_csv(path: str) -> pd.DataFrame:
    df = pd.DataFrame(SEED, columns=COLUMNS)
    df.to_csv(path, index=False)
    return df


def load(data_dir: str = "data") -> pd.DataFrame:
    path = os.path.join(data_dir, "cersai_stats.csv")
    if not os.path.exists(path):
        seed_csv(path)
    return pd.read_csv(path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    a = ap.parse_args()
    df = load(a.data_dir)
    print("CERSAI aggregates (ALL-ASSET, unvetted context — NOT SVAMITVA-specific):")
    print(df[["metric", "value", "scope", "as_of"]].to_string(index=False))
    print("\nSVAMITVA card-backed numerator stays the parliamentary figure (aggregate_numerator: "
          "national 11,147). CERSAI card-tagged breakdown needs the RTI (docs/rti_cersai.md).")
