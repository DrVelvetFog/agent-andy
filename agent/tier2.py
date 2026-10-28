"""Tier 2 of the hybrid knowledge base: a sitemap-derived site index.

INDEX ONLY. Tier 2 never answers and never carries a verdict — it holds a list of
the site's location pages (built by scripts/build_site_index.py from the public
sitemap into data/site_index.json), each with a label and a state DERIVED FROM THE
URL PATH ALONE and marked unverified. For a staged question it can offer a
candidate SITE PAGE so a human can go check the primary source. A place not in the
index yields NO candidate, and a URL is never invented.

Tier 1 (the vetted fixture in data/detect_sample.toml) is the only thing that
answers. Tier 2 sits behind it and can only ever add a candidate to a STAGE.
"""

from __future__ import annotations

import json
from pathlib import Path

INDEX_FILE = Path(__file__).resolve().parent.parent / "data" / "site_index.json"

_cache: dict | None = None


def _norm(s) -> str:
    return " ".join(str(s).lower().split()).strip(" .,?!")


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        except Exception:
            _cache = {"entries": [], "source": None, "fetched": None, "url_count": 0}
    return _cache


def meta() -> dict:
    """What the index is, for honest display: source, fetch date, URL count."""
    d = _load()
    return {"source": d.get("source"), "fetched": d.get("fetched"),
            "url_count": d.get("url_count"), "entry_count": len(d.get("entries", []))}


def index_urls() -> frozenset:
    """The exact set of page URLs in the index. Verify-on-demand will only ever
    fetch a URL that is in here — the one bit of web Andy touches is the index it
    already holds; anything else is refused without a fetch."""
    return frozenset(e.get("url", "") for e in _load().get("entries", []))


def candidates(place: str, state: str | None = None, limit: int = 3) -> list[dict]:
    """Up to `limit` candidate site pages whose label matches `place` (normalized),
    optionally filtered to a state. Each is INDEX DATA ONLY — url, label, and a
    state derived from the URL path, explicitly unverified. No verdict is implied.
    An empty list means no candidate; a URL is never invented."""
    q = _norm(place)
    if not q:
        return []
    st = _norm(state) if state else None
    exact, partial = [], []
    for e in _load().get("entries", []):
        if st and _norm(e.get("state_from_path", "")) != st:
            continue
        label = _norm(e.get("label", ""))
        if label == q:
            exact.append(e)
        elif label and (q in label or label in q):
            partial.append(e)
    picked = (exact + partial)[:limit]
    return [{"url": e["url"], "label": e.get("label", ""),
             "state_from_path": e.get("state_from_path"),
             "source": "site-index", "verified": False} for e in picked]
