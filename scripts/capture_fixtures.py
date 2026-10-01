"""capture_fixtures.py — maintainer-run, networked, NEVER run in CI.

Records the live fixtures once, sanitizes them, and writes them under tests/fixtures/
(spec slice 0, issue #2; obligation #13: recorded fixtures are sanitized before commit).
The RSS capture is a plain polite GET; the Jev capture needs ARJEV_JEV_KEY; the Slack
capture needs ARJEV_SLACK_TOKEN and is optional (synthetic fixtures ship as the default).

Usage:
  python scripts/capture_fixtures.py --rss
  python scripts/capture_fixtures.py --rss --jev --arxiv-id 2608.05686
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from arjev.sanitize import ensure_sanitized, sanitize  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
UA = "arjev-fixture-capture/0.1 (harmoniqs/arjev; research tool; contact via github)"


def capture_rss(feed: str = "quant-ph") -> None:
    with httpx.Client(timeout=30, headers={"user-agent": UA}) as client:
        xml = client.get(f"https://export.arxiv.org/rss/{feed}").text
    items = xml.count("<item>")
    ET.fromstring(xml)  # malformed feed aborts the capture
    (FIXTURES / f"rss-{feed}.xml").write_text(xml)
    print(f"rss-{feed}.xml: {items} items")


def capture_jev(arxiv_id: str) -> None:
    import os

    key = os.environ.get("ARJEV_JEV_KEY")
    if not key:
        sys.exit("ARJEV_JEV_KEY not set — skipping Jev capture")
    state = {
        "researcher_taste": {"terms": {"cat qubit": 1.0, "bias field": 0.8}},
        "recent_titles": ["synthetic recent title"],
    }
    questions = {
        "relevant": {
            "type": "noul",
            "instructions": "Is this paper relevant to the researcher's taste digest?",
            "criteria": {"true": "matches the taste digest", "false": "no overlap"},
        }
    }
    # The contract of record (live-verified 2026-09-20): /v1/systemone, model in body,
    # questions as a map; response is sanitized before landing.
    with httpx.Client(timeout=60) as client:
        r = client.post(
            "https://api.typesafe.ai/v1/systemone",
            headers={"authorization": f"Bearer {key}"},
            json={"model": "jev-latest", "state": state, "questions": questions},
        )
        r.raise_for_status()
        payload = r.json()
    ensure_sanitized(sanitize(payload))
    (FIXTURES / "jev-responses.json").write_text(json.dumps(sanitize(payload), indent=2) + "\n")
    print("jev-responses.json: sanitized")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--rss", action="store_true")
    p.add_argument("--jev", action="store_true")
    p.add_argument("--arxiv-id", default="2608.05686")
    a = p.parse_args()
    if a.rss:
        capture_rss()
    if a.jev:
        capture_jev(a.arxiv_id)
    if not (a.rss or a.jev):
        print(__doc__)
