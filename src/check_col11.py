"""Sanity-check the col-11 parse on saved RoR HTML dumps (data/ror_html/).
Re-fetch dumps first (encoding fix): python3 src/ror_sampler.py --limit 1 --save-html
Prints per-parcel: (parcels, with_loan) and the raw col-11 cell values — no owner data."""
import glob, io, re, sys
import pandas as pd
try:
    from ror_sampler import col11_encumbered
except ImportError:
    from src.ror_sampler import col11_encumbered

files = sorted(glob.glob("data/ror_html/*.html"))
if not files:
    print("no dumps — run: python3 src/ror_sampler.py --limit 1 --save-html"); sys.exit(0)

tot_p = tot_l = 0
for fp in files:
    html = open(fp, encoding="utf-8").read()
    p, w, note = col11_encumbered(html)
    tot_p += p; tot_l += w
    # show the raw encumbrance cells for transparency
    vals = []
    try:
        for t in pd.read_html(io.StringIO(html)):
            if t.shape[1] < 12:
                continue
            rows = [[str(c).strip() for c in r.tolist()] for _, r in t.iterrows()]
            data = [c for c in rows if re.fullmatch(r"\d+", c[0])]
            if data:                       # the table that actually holds parcels
                vals = [c[10] for c in data]
                break
    except Exception:
        pass
    print(f"{fp.split('/')[-1]:40} parcels={p} loan={w} note={note} col11={vals}")

print(f"\nTOTAL parcels={tot_p}  with_loan={tot_l}")
