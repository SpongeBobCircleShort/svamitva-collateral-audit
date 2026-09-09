"""
DWR (Direct Web Remoting) plaincall client for the SVAMITVA portal.

The SVAMITVA dashboard (svamitva.nic.in) is backed by a Java DWR RPC endpoint.
Every dashboard table is fetched by POSTing a `plaincall` request and parsing a
JavaScript reply of the form:

    //#DWR-REPLY
    var s0={};var s1={};...
    s0.code=390;s0.name="ANUPPUR";s0['completed_village']=161;...
    s1.code=391;...
    dwr.engine._remoteHandleCallback('0','0',[s0,s1,...]);

No authentication, no session cookie, no CSRF token is required. This module
turns a method name + string params into a clean list[dict].
"""
from __future__ import annotations

import re
import time
import random
import requests
import urllib3

# svamitva.nic.in serves an incomplete TLS chain (missing intermediate CA), so
# stock clients fail cert verification while browsers/curl -k succeed. We pin the
# host and skip verification deliberately; suppress the resulting noise.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://svamitva.nic.in/svamitva_hindi"
ENDPOINT = BASE + "/DWR/call/plaincall/{script}.{method}.dwr"
DEFAULT_PAGE = "/svamitva_hindi/getPropertyCardDistributed.html"

# One assignment inside a DWR reply, e.g.
#   s0.code=390;         -> idx=0 key=code       value=390
#   s3['total_village']=602;  -> idx=3 key=total_village value=602
#   s2.name="BALAGHAT";  -> idx=2 key=name       value="BALAGHAT"
_ASSIGN = re.compile(
    r"""s(\d+)                      # object index
        (?:\.([A-Za-z_]\w*)         # .field
          |\['([^']+)'\])           # ['field']
        =
        ("(?:[^"\\]|\\.)*"          # a double-quoted string (escapes allowed)
          |[^;]*)                   # or a bare token up to ;
        ;""",
    re.VERBOSE,
)

_UNI = re.compile(r"\\u([0-9a-fA-F]{4})")


def _unescape(s: str) -> str:
    """Decode a DWR-encoded JS string literal (already stripped of quotes)."""
    s = _UNI.sub(lambda m: chr(int(m.group(1), 16)), s)
    s = s.replace('\\/', '/').replace('\\"', '"').replace("\\'", "'")
    s = s.replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\')
    return s


def _coerce(raw: str):
    raw = raw.strip()
    if raw == "null" or raw == "":
        return None
    if raw.startswith('"') and raw.endswith('"'):
        return _unescape(raw[1:-1])
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d*\.\d+", raw):
        return float(raw)
    if raw in ("true", "false"):
        return raw == "true"
    # references (s5) or anything unexpected -> keep as string
    return raw


def parse(reply: str) -> list[dict]:
    """Parse a DWR plaincall reply body into a list of row dicts ordered by index."""
    rows: dict[int, dict] = {}
    for m in _ASSIGN.finditer(reply):
        idx = int(m.group(1))
        key = m.group(2) or m.group(3)
        rows.setdefault(idx, {})[key] = _coerce(m.group(4))
    return [rows[i] for i in sorted(rows)]


class DwrClient:
    def __init__(self, script: str = "lgdService", delay: float = 0.4,
                 timeout: int = 45, retries: int = 3, page: str = DEFAULT_PAGE):
        self.script = script
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.page = page
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/131.0.0.0 Safari/537.36",
            "Content-Type": "text/plain",
            "Accept": "*/*",
        })

    def call(self, method: str, *params, page: str | None = None) -> list[dict]:
        url = ENDPOINT.format(script=self.script, method=method)
        lines = [
            "callCount=1",
            "windowName=",
            f"c0-scriptName={self.script}",
            f"c0-methodName={method}",
            "c0-id=0",
        ]
        for i, p in enumerate(params):
            lines.append(f"c0-param{i}=string:{p}")
        lines += [
            "batchId=0",
            "instanceId=0",
            f"page={requests.utils.quote(page or self.page)}",
            "scriptSessionId=" + "".join(random.choice("0123456789ABCDEF") for _ in range(16)),
        ]
        body = "\n".join(lines) + "\n"

        last = None
        for attempt in range(self.retries):
            try:
                r = self.s.post(url, data=body.encode("utf-8"),
                                timeout=self.timeout, verify=False)
                r.raise_for_status()
                time.sleep(self.delay + random.uniform(0, self.delay))
                return parse(r.text)
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"DWR call {method}{params} failed after {self.retries} tries: {last}")


if __name__ == "__main__":
    # Smoke test: MP districts (state code 23).
    c = DwrClient()
    d = c.call("getPropertyCardDistributedCount", 23)
    print(f"districts: {len(d)}")
    for row in d[:3]:
        print(row)
