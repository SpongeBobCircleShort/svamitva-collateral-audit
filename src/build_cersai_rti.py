"""
Generate a ready-to-file RTI application to CERSAI for the SVAMITVA card-backed security-interest
count (national, state-wise). One filing, national scope. Mirrors src/build_rti.py (MP kit).

Output: data/rti_filled/RTI_CERSAI.md   (fill applicant details, then file)
Usage:  python src/build_cersai_rti.py
"""
from __future__ import annotations

import os
import argparse

OUTDIR = "data/rti_filled"

BODY = """\
To,
The Central Public Information Officer (CPIO),
Central Registry of Securitisation Asset Reconstruction and Security Interest of India (CERSAI),
Department of Financial Services, Ministry of Finance, Government of India,
New Delhi.

Subject: Information under the Right to Information Act, 2005 — security interests registered
against SVAMITVA / rural abadi (property-card) property, State-wise and year-wise.

Respected Sir/Madam,

Under Section 6 of the Right to Information Act, 2005, I request the following information held by
CERSAI in its Central Registry of security interests (SARFAESI Act, 2002). For each point, kindly
provide figures year-wise from FY 2021-22 to the latest available year:

1. The total number of security interests registered with CERSAI where the underlying collateral is
   a property covered by the SVAMITVA scheme — i.e. rural abadi / gaothan / village-site residential
   property issued a property card, sannad, gharauni, adhikar abhilekh or equivalent SVAMITVA title.

2. The same count as in (1), broken down by State / Union Territory.

3. Of the count in (1), the number where the SVAMITVA property was registered as collateral for a
   loan or credit facility (a security interest for a financial facility), as distinct from any
   other registration type.

4. Whether CERSAI's registry records or can distinctly identify SVAMITVA / abadi property as a
   collateral category. If such collateral is not separately identifiable in the registry, kindly
   state so.

If any part of this information is held by another public authority, kindly transfer that part
under Section 6(3) and inform me. If the information is voluminous, kindly indicate the fee payable
under Section 7 before processing.

I have deposited the application fee of Rs. 10/- (or am exempt as a BPL applicant, proof enclosed).

Applicant details:
  Name:            [YOUR NAME]
  Address:         [YOUR POSTAL ADDRESS]
  Email / Phone:   [YOUR EMAIL] / [YOUR PHONE]
  Date & Place:    [DATE], [PLACE]

Signature: ____________________
"""

NOTE = """\
<!-- HOW TO FILE
- Public authority: CERSAI (Govt company under Dept of Financial Services, Ministry of Finance).
- Fee: Rs. 10 (IPO / DD / court-fee stamp; online via the DoFS/RTI Online portal if available).
  BPL applicants exempt. First 20 pages of copies free; Rs. 2/page thereafter.
- Scope: ONE national filing — CERSAI is the central registry, so no per-state filings are needed.
- If CERSAI replies it cannot separate SVAMITVA/abadi collateral, that answer is itself a finding:
  the card-backed charge is not distinctly recorded, consistent with "collateral nominal".
- See docs/cersai_recon.md and docs/rti_cersai.md for context.
-->
"""


def build(outdir: str = OUTDIR) -> str:
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "RTI_CERSAI.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("# RTI application — CERSAI: SVAMITVA card-backed security interests\n\n")
        f.write(NOTE + "\n")
        f.write(BODY)
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=OUTDIR)
    a = ap.parse_args()
    p = build(a.outdir)
    print(f"-> {p}")
