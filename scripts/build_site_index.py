#!/usr/bin/env python3
"""Build the Tier-2 site index from the public wheretodetect.org sitemap.

Tier 2 is INDEX-ONLY. This reads the sitemap (read-only; no page bodies are
fetched) and writes a list of the site's location pages, each with a label and a
state DERIVED FROM THE URL PATH ALONE — no verdict, no citation, no quote, nothing
scraped. The index records the sitemap URL, the fetch date, and the exact URL
count found. It is NOT a verified location count and NOT a claim about how many
locations the site covers; a human must check the primary source before any
verdict. Re-run to refresh.

    python3 scripts/build_site_index.py
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITEMAP = "https://wheretodetect.org/sitemap.xml"
OUT = ROOT / "data" / "site_index.json"

_LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
# Location pages only: /metal-detecting/<state>/<location>/
_PATH_RE = re.compile(r"^https?://[^/]+/metal-detecting/([^/]+)/([^/]+)/?$")


def _label(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.split("-") if w)


def main() -> int:
    req = urllib.request.Request(SITEMAP, headers={"User-Agent": "agent-andy-indexer"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        xml = resp.read().decode("utf-8", "replace")

    locs = _LOC_RE.findall(xml)
    entries = []
    for url in locs:
        m = _PATH_RE.match(url)
        if not m:
            continue  # law / club / guide / contact / home pages are not locations
        state_slug, loc_slug = m.group(1), m.group(2)
        entries.append({
            "url": url,
            "label": _label(loc_slug),            # from the URL path only — unverified
            "state_from_path": _label(state_slug),  # from the URL path only — unverified
        })

    index = {
        "source": SITEMAP,
        "fetched": time.strftime("%Y-%m-%d", time.gmtime()),
        "url_count": len(locs),  # exact number of URLs found in the sitemap
        "note": ("Derived from the public sitemap. A list of the site's location pages "
                 "(metal-detecting/<state>/<location>); the remaining sitemap URLs are "
                 "law / club / guide / contact pages. This is NOT a verified location "
                 "count and NOT a verdict or citation database. The label and state are "
                 "derived from the URL PATH ONLY and are UNVERIFIED — a human must check "
                 "the primary source before any verdict."),
        "entries": entries,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(locs)} sitemap URLs, "
          f"{len(entries)} location entries, fetched {index['fetched']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
