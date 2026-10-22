"""Run RouteFuel.postman_collection.json without Postman (standard library only).

    python docs/postman/run_collection.py [--base-url http://127.0.0.1:8000]

Sends every request in order and checks the status code its Postman test expects
(``pm.response.to.have.status(N)``). The JavaScript assertions only run in Postman/newman.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

COLLECTION = Path(__file__).with_name("RouteFuel.postman_collection.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    collection = json.loads(COLLECTION.read_text())
    failures = 0
    for index, item in enumerate(collection["item"]):
        # Keep successive demo requests below the public provider's 1 request/s limit.
        if index:
            time.sleep(1.1)
        request = item["request"]
        url = request["url"].replace("{{base_url}}", args.base_url.rstrip("/"))
        data = request.get("body", {}).get("raw")
        expected = int(
            re.search(r"have\.status\((\d+)\)", "\n".join(item["event"][0]["script"]["exec"]))[1]
        )
        if not url.startswith(("http://", "https://")):
            raise SystemExit(f"Refusing non-HTTP URL: {url}")
        req = urllib.request.Request(  # noqa: S310 — scheme checked above
            url,
            data=data.encode() if data else None,
            method=request["method"],
            headers={"Content-Type": "application/json"},
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=60) as response:  # noqa: S310 — local URL
                status, body = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, body = error.code, error.read()
        elapsed = (time.perf_counter() - started) * 1000
        summary = ""
        try:
            payload = json.loads(body)
            if "error" in payload:
                summary = payload["error"]["code"]
            elif "fuel_plan" in payload:
                s = payload["fuel_plan"]["summary"]
                summary = (
                    f"{payload['route']['distance_miles']} mi, {s['number_of_stops']} stops, "
                    f"${s['total_purchase_cost']}, cached={payload['meta']['cached']}"
                )
            elif "route" in payload:
                summary = (
                    f"{payload['route']['distance_miles']} mi, cached={payload['meta']['cached']}"
                )
        except (ValueError, KeyError):
            pass
        ok = status == expected
        failures += not ok
        verdict = "PASS" if ok else "FAIL"
        print(
            f"{verdict} {status} (expected {expected}) {elapsed:7.0f} ms  {item['name']}  {summary}"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
