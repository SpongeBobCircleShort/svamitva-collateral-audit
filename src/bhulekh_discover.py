"""
MP Bhulekh discovery pass — RUN THIS ON AN INDIA NETWORK (portal is geo/host blocked
elsewhere). One-shot tool: it opens a real browser, records every network request while
YOU manually walk to a single village's abadi / B-1 (भू-अधिकार / ऋण-पुस्तिका) record,
then dumps everything the scraper needs to know.

Why manual-in-the-loop: the exact request flow (ASP.NET __VIEWSTATE, cascading
district->tehsil->village dropdowns, and any captcha) can't be seen from the build
machine. You drive it once; this captures the shape so bhulekh_scraper.py can automate it.

What it saves (into --out-dir, default ./data/bhulekh_discovery):
  har.har              full network capture (import into any tool)
  requests.json        concise list of XHR/doc POSTs: url, method, post body, resp snippet
  page_final.html      the DOM of whatever record page you ended on (find the loan column here)
  screenshot.png       what you were looking at when you finished

Run:
  python src/bhulekh_discover.py
  # a browser opens; navigate the FREE services -> Khasra/B-1 for one village,
  # open the record that shows the loan/encumbrance (ऋण / बंधक) column,
  # then return to this terminal and press Enter.
"""
from __future__ import annotations

import os
import json
import argparse

START_URL = "https://mpbhulekh.gov.in/"

CAPTURE_JS_HINT = """
LOOK FOR, in page_final.html / requests.json:
  * the POST endpoint that returns a village's holder list / B-1
  * the parameter names carrying district / tehsil / village codes
  * a column whose header contains  ऋण  (loan) or  बंधक  (mortgage) or 'Encumbrance'
  * whether a captcha image + text field gate the record view
"""


def main(out_dir: str):
    from playwright.sync_api import sync_playwright  # imported lazily so the file
    # is importable even where playwright isn't installed yet.

    os.makedirs(out_dir, exist_ok=True)
    records: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(record_har_path=os.path.join(out_dir, "har.har"),
                                   ignore_https_errors=True)
        page = ctx.new_page()

        def on_request_finished(req):
            try:
                if req.method != "POST" and req.resource_type not in ("xhr", "fetch", "document"):
                    return
                resp = req.response()
                body_snip = ""
                try:
                    if resp is not None:
                        body_snip = resp.text()[:1500]
                except Exception:
                    pass
                records.append({
                    "url": req.url,
                    "method": req.method,
                    "resource_type": req.resource_type,
                    "post_data": (req.post_data or "")[:3000],
                    "status": resp.status if resp else None,
                    "resp_snippet": body_snip,
                })
            except Exception:
                pass

        page.on("requestfinished", on_request_finished)

        print("Opening", START_URL)
        try:
            page.goto(START_URL, timeout=60000)
        except Exception as e:  # noqa: BLE001
            print("Initial load issue (continue manually):", e)

        print("\n" + "=" * 70)
        print("Walk to ONE village's B-1 / abadi record showing the loan column.")
        print(CAPTURE_JS_HINT)
        print("When the record is on screen, come back here and press Enter.")
        print("=" * 70)
        input()

        try:
            html = page.content()
            with open(os.path.join(out_dir, "page_final.html"), "w", encoding="utf-8") as f:
                f.write(html)
            page.screenshot(path=os.path.join(out_dir, "screenshot.png"), full_page=True)
        except Exception as e:  # noqa: BLE001
            print("Could not dump final page:", e)

        ctx.close()   # flush HAR
        browser.close()

    with open(os.path.join(out_dir, "requests.json"), "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(records)} requests -> {out_dir}/requests.json")
    print(f"HAR -> {out_dir}/har.har   DOM -> {out_dir}/page_final.html")
    print("Send these back so bhulekh_scraper.py selectors/endpoints can be finalized.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="data/bhulekh_discovery")
    main(ap.parse_args().out_dir)
