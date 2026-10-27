"""Witness: verified observation for a packing checklist.

Andy is asked to confirm a box is packed. For each item he looks at a real
photo (the Razr is the camera; the Mac runs SAM), and the item ticks ONLY when
SAM actually segments it. One checker rule governs the whole job: the checklist
is not marked shipped until every item is verified. Fail closed — a SAM miss,
a low-confidence result, or a failed call records the item as unverified, names
it, and the box is NOT marked shipped. An honest "unverified, check by hand"
beats a confident hallucination.

Every observation is a receipt in the same hash-chained log as everything else,
carrying the two fields that make it checkable: the photo's hash and the SAM
mask id.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from . import eyes

# Size floor for a real detection, used only when strict=True: the largest mask
# must cover at least this fraction of the frame. SAM returns masks, not
# probabilities, so by default verification is presence-based (>=1 real-sized
# mask, where "real-sized" already filters stray edge artifacts) and strict is off.
MIN_COVERAGE = 0.05


def _verify(seg: dict | None, min_coverage: float, strict: bool) -> tuple[bool, str, str | None, int, float]:
    """Decide verified/unverified from a SAM summary. Fail closed."""
    if seg is None:
        return False, "SAM call failed — unverified (fail closed)", None, 0, 0.0
    concept, n, cov = seg.get("concept"), seg.get("detections", 0), seg.get("top_area_frac", 0.0)
    if n < 1:
        return False, f"SAM found no real-sized '{concept}' — unverified", None, n, cov
    if strict and cov < min_coverage:
        return False, f"largest '{concept}' mask covers only {cov:.1%} of frame — unverified (fail closed)", None, n, cov
    mask_id = f"{str(concept).replace(' ', '_')}#0"
    return True, f"SAM segmented '{concept}' — {n} mask(s), largest covers {cov:.1%} of frame", mask_id, n, cov


def record(chain, item: str, concept: str, photo_hash: str, verified: bool,
           reason: str, detections: int = 0, top_score=None, mask_id=None,
           coverage: float = 0.0) -> dict:
    """Write one witness-observation receipt (same chain as every other action)."""
    receipt = chain.append({
        "type": "witness_observation",
        "summary": f"witness {item}: {'verified' if verified else 'UNVERIFIED'} ({concept})",
        "item": item,
        "concept": concept,
        "photo_hash": photo_hash,     # the required field: hash of the real photo
        "sam_mask_id": mask_id,       # the required field: SAM mask id (null when unverified)
        "sam_detections": detections,
        "sam_coverage": coverage,     # fraction of the frame the largest mask covers
        "sam_top_score": top_score,   # None: SAM returns masks, not probabilities
        "verified": verified,
        "reason": reason,
        "checked": time.strftime("%Y-%m-%d", time.gmtime()),
    })
    return {"item": item, "verified": verified, "reason": reason, "receipt": receipt}


def observe_and_verify(chain, item: str, concept: str, image_path: str,
                       min_coverage: float = MIN_COVERAGE, strict: bool = False) -> dict:
    """Segment a real photo for `concept` and receipt the verified/unverified result."""
    try:
        photo_hash = hashlib.sha256(Path(image_path).read_bytes()).hexdigest()
    except OSError as e:
        # No photo, or an unreadable one, is not a pass — fail closed, named.
        return record(chain, item, concept, "unavailable", False,
                      f"photo unreadable ({type(e).__name__}) — unverified (fail closed)")
    try:
        seg = eyes.segment(image_path, concept)
    except Exception as e:
        return record(chain, item, concept, photo_hash, False,
                      f"SAM call failed ({type(e).__name__}) — unverified (fail closed)")
    verified, reason, mask_id, detections, coverage = _verify(seg, min_coverage, strict)
    return record(chain, item, concept, photo_hash, verified, reason,
                  detections=detections, top_score=None, mask_id=mask_id, coverage=coverage)


def finalize(chain, results: list[dict]) -> dict:
    """The one checker rule: do not mark the checklist complete until EVERY item
    is verified. Fail closed, and name every item that is not."""
    missing = [r["item"] for r in results if not r["verified"]]
    ready = len(results) > 0 and not missing
    receipt = chain.append({
        "type": "checklist_result",
        "summary": f"packing checklist: {'READY TO SHIP' if ready else 'NOT shipped'}",
        "items": [r["item"] for r in results],
        "ready_to_ship": ready,
        "unverified_items": missing,
    })
    return {"ready_to_ship": ready, "unverified_items": missing, "receipt": receipt}
