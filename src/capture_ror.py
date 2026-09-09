"""
Capture the RoR-detail request/response ONCE, on your machine (webgis2 reachable there).

Run:  python src/capture_ror.py
A browser opens. Do exactly one abadi RoR lookup and click View (solve the captcha), so the
page fires the record request. Then press Enter here. The script records every RoR-related
request and writes:
  data/ror_request.json   the request template (method, url, POST body param NAMES, headers)
  data/ror_schema.txt     the response field NAMES + which look like the encumbrance/loan column

It prints/saves NAMES only, not owner values. Paste ror_schema.txt back so the sampler's
encumbrance parse can be finalized.
"""
from __future__ import annotations

import os
import json
import argparse

WEBGIS = "https://webgis2.mpbhulekh.gov.in/"
ROR_HINTS = ("ror-detail", "/ror", "adhikar", "abhilekh", "certifiedcopy", "landrecords",
             "public/html")
LOAN_KW = ["vilangam", "villangam", "विल्लंगम", "बंधक", "bandhak", "दृष्टिबंधक", "ऋण", "rin",
           "loan", "mortgage", "encumbrance", "charge", "प्रभार"]


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
            if not any(h in req.url.lower() for h in ROR_HINTS):
                return
            try:
                resp = req.response()
                body = ""
                try:
                    body = resp.text()[:6000] if resp else ""
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
        print("Do ONE abadi RoR lookup + click View (solve the captcha).")
        print("When the record is shown, come back here and press Enter.")
        print("=" * 68)
        input()
        ctx.close(); b.close()

    # pick the most detail-ish RoR hit (largest response containing a loan keyword)
    ranked = sorted(hits, key=lambda h: (any(k in h["resp"].lower() for k in
                    [w.lower() for w in LOAN_KW]), len(h["resp"])), reverse=True)
    template = None
    schema_lines = [f"captured {len(hits)} RoR-related request(s)\n"]
    for h in ranked:
        schema_lines.append(f"\n=== {h['method']} {h['url']}  [{h['status']}]")
        # request body param NAMES only
        pd = h["post_data"]
        try:
            names = list(json.loads(pd).keys())
        except Exception:
            names = [kv.split("=")[0] for kv in pd.split("&") if "=" in kv]
        schema_lines.append(f"request params: {names}")
        # response field names
        try:
            resp = json.loads(h["resp"])
            keys = key_paths(resp)
            loan = [k for k in keys if any(w in k.lower() for w in [x.lower() for x in LOAN_KW])]
            schema_lines.append(f"response fields: {keys[:60]}")
            schema_lines.append(f"LOAN/ENCUMBRANCE-like fields: {loan or 'NONE (may be HTML table)'}")
        except Exception:
            has = [w for w in LOAN_KW if w.lower() in h["resp"].lower()]
            schema_lines.append(f"response is non-JSON (HTML?); loan keywords present: {has}")
        if template is None and h["method"] == "POST":
            template = {"url": h["url"], "method": h["method"], "param_names": names}

    with open(os.path.join(data_dir, "ror_schema.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(schema_lines))
    if template:
        json.dump(template, open(os.path.join(data_dir, "ror_request.json"), "w"), indent=2)

    print("\n".join(schema_lines))
    print(f"\n-> {data_dir}/ror_schema.txt   (paste this back)")
    if template:
        print(f"-> {data_dir}/ror_request.json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    main(ap.parse_args().data_dir)
