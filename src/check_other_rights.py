"""
Scan saved Maharashtra record HTML (7/12 or Property Card) for an Other Rights (इतर हक्क) charge
— the collateral signal (बोजा/कर्ज/बंधक), analog of MP's col-11 check.

Assisted flow: view a record on bhulekh.mahabhumi.gov.in (you enter mobile + captcha), save the
page as HTML into data/maha_records/, then run this to tag each as charged / clear.

Usage:  python src/check_other_rights.py
"""
import glob
import os
import sys

try:
    from maha_api import other_rights
except ImportError:
    from src.maha_api import other_rights

files = sorted(glob.glob("data/maha_records/*.html"))
if not files:
    print("no records — save viewed Property Card / 7/12 pages into data/maha_records/*.html")
    sys.exit(0)

charged = 0
for fp in files:
    html = open(fp, encoding="utf-8", errors="replace").read()
    has, hits = other_rights(html)
    charged += has
    print(f"{os.path.basename(fp):45} charge={'Y' if has else 'N'}  {hits if hits else ''}")

print(f"\n{charged} of {len(files)} records show an Other Rights charge.")
