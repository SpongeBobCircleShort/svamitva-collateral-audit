"""
Capture the REGULAR (agricultural khasra) RoR request/response ONCE, on your machine.

Why: the abadi RoR col 11 (encumbrance) is blank on every parcel we've checked, and the
column is confirmed correct. The clincher is whether the SAME portal renders a charge for
ordinary farm khasra land, where KCC/crop-loan बंधक is common. If it does and abadi never
does, the gap is structural to the abadi record — proven, not a scraper bug.

Run:  python src/capture_khasra.py
A browser opens at webgis2. Navigate the REGULAR land-record / खसरा (bhu-abhilekh) RoR —
NOT the abadi/SVAMITVA one — and open the RoR for an agricultural khasra that is likely to
carry a bank loan (any KCC farmer parcel). View the full RoR (solve any captcha). Then press
Enter here.

It records every webgis2 request, flags which response contains a loan keyword
(बंधक/दृष्टिबंधक/ऋण/प्रभार), writes the endpoint template + field names, and — crucially —
saves any charge-bearing RoR HTML to data/khasra_loan_sample.html for inspection. NAMES and
the encumbrance HTML are saved; paste khasra_schema.txt back.
"""
from __future__ import annotations

import os
import json
import argparse

WEBGIS = "https://webgis2.mpbhulekh.gov.in/"
# broad: catch whatever module the khasra RoR uses, not just the abadi paths
HINTS = ("ror", "adhikar", "abhilekh", "certifiedcopy", "landrecords", "khasra",
         "khatauni", "bhu", "/html", "public")
LOAN_KW = ["vilangam", "villangam", "विल्लंगम", "बंधक", "bandhak", "दृष्टिबंधक", "ऋण", "rin",
           "loan", "mortgage", "encumbrance", "charge", "प्रभार", "अधिभार"]


def key_paths(obj, prefix="", out=None):
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            out.append(p); key_paths(v, p, out)
    elif isinstance(obj, list) and obj:
        key_paths(obj[0], prefix + "[]", out)
    return out


def main(data_dir: str):
    from playwright.sync_api import sync_playwright
    os.makedirs(data_dir, exist_ok=True)
    hits: list[dict] = []

    with sync_playwright() as p:
        b = p.chromium.launch(headless=False)
        ctx = b.new_context(ignore_https_errors=True)
        pg = ctx.new_page()

        def on_finished(req):
            if "webgis2.mpbhulekh" not in req.url.lower():
                return
            if not any(h in req.url.lower() for h in HINTS):
                return
            try:
                resp = req.response()
                body = ""
                try:
                    body = resp.text()[:20000] if resp else ""
                except Exception:
                    pass
                hits.append({"url": req.url, "method": req.method,
                             "post_data": req.post_data or "",
                             "req_headers": dict(req.headers),
                             "status": resp.status if resp else None,
                             "resp": body})
            except Exception:
                pass

        pg.on("requestfinished", on_finished)
        try:
            pg.goto(WEBGIS, timeout=60000)
        except Exception as e:  # noqa: BLE001
            print("load note:", e)

        print("\n" + "=" * 68)
        print("Open the REGULAR खसरा / bhu-abhilekh RoR (NOT abadi/SVAMITVA).")
        print("Pick an agricultural khasra likely to carry a KCC/bank loan and View it.")
        print("When the full RoR is shown, come back here and press Enter.")
        print("=" * 68)
        input()
        ctx.close(); b.close()

    ranked = sorted(hits, key=lambda h: (any(k in h["resp"].lower() for k in
                    [w.lower() for w in LOAN_KW]), len(h["resp"])), reverse=True)
    lines = [f"captured {len(hits)} webgis2 request(s)\n"]
    template = None
    loan_html_saved = None
    for h in ranked:
        lines.append(f"\n=== {h['method']} {h['url']}  [{h['status']}]")
        pd = h["post_data"]
        try:
            names = list(json.loads(pd).keys())
        except Exception:
            names = [kv.split("=")[0] for kv in pd.split("&") if "=" in kv]
        lines.append(f"request params: {names}")
        present = [w for w in LOAN_KW if w.lower() in h["resp"].lower()]
        try:
            resp = json.loads(h["resp"])
            keys = key_paths(resp)
            loan = [k for k in keys if any(w in k.lower() for w in [x.lower() for x in LOAN_KW])]
            lines.append(f"response fields: {keys[:60]}")
            lines.append(f"LOAN/ENCUMBRANCE-like fields: {loan or 'NONE (may be HTML table)'}")
        except Exception:
            lines.append(f"response is non-JSON (HTML?); loan keywords present: {present}")
            # save the first charge-bearing HTML for hand inspection
            if present and loan_html_saved is None and "<" in h["resp"]:
                loan_html_saved = os.path.join(data_dir, "khasra_loan_sample.html")
                open(loan_html_saved, "w", encoding="utf-8").write(h["resp"])
        if template is None and h["method"] == "POST":
            template = {"url": h["url"], "method": h["method"], "param_names": names}

    open(os.path.join(data_dir, "khasra_schema.txt"), "w", encoding="utf-8").write("\n".join(lines))
    if template:
        json.dump(template, open(os.path.join(data_dir, "khasra_request.json"), "w"), indent=2)

    print("\n".join(lines))
    print(f"\n-> {data_dir}/khasra_schema.txt   (paste this back)")
    if loan_html_saved:
        print(f"-> {loan_html_saved}   (charge-bearing RoR HTML — the positive control)")
    if template:
        print(f"-> {data_dir}/khasra_request.json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    main(ap.parse_args().data_dir)
