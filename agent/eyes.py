"""Eyes: SAM 3.1 via the Meta Model API (Day 1 placeholder).

Planned: segment the active-task scene (e.g. the packing box) and return
object masks with confidence, so Witness receipts can say "saw X, with this
evidence". A SAM miss is not a guess — it fails closed: the receipt records
unverified and the checklist does not tick.

Not implemented on Day 1; the interface exists so the loop and receipts are
shaped correctly from the start.
"""

from __future__ import annotations


def observe(image_path: str, targets: list[str]) -> dict:
    raise NotImplementedError("SAM 3.1 wiring is scheduled for the Oct 30 session")
