"""Scenario-sub-range identifier allocation.

Phase 1's estate generator (`reference_data.generator`) mints IDs shaped
``SYN-<ENTITY>-<seq>`` (e.g. ``SYN-MBR-000001``, ``SYN-CLM-0000007``).
This phase's scenario generator must produce IDs that:

1. Follow the same overall "obviously synthetic" convention
   (`DATA_GOVERNANCE.md` Part A: never a format that could be mistaken for
   a real-world identifier), and
2. Are, in addition, distinguishable *from Phase 1 estate-native IDs
   specifically* -- so a reviewer (or downstream code) can tell "this
   Member was fabricated by a Phase 1 bulk estate generation run" from
   "this Member exists only because a scenario generator manufactured it
   to backstop a high-cost-claim fixture", without needing the
   `data_provenance` column at all (though that column is the primary,
   authoritative signal -- see `provenance.py`; the ID convention is a
   secondary, human-at-a-glance signal, and is not on its own sufficient
   because nothing prevents a future generator from choosing a colliding
   scheme by accident -- always check `data_provenance` programmatically).

The convention: insert a literal ``SCEN`` segment between the entity
prefix and the sequence number: ``SYN-<ENTITY>-SCEN-<seq>``. Phase 1 never
emits a ``SCEN`` segment, so there is no possibility of collision between
the two ID spaces by construction (not by convention alone).

Negative-test scenarios that need a reference to something that provably
does not exist anywhere (`invalid_claim_references`, `missing_provider`)
use a further-distinguished sentinel shape:
``SYN-<ENTITY>-SCEN-NX-<tag>-<seq>`` (``NX`` = "nonexistent"), analogous
to (but more legible than) Phase 1's own sentinel-offset technique
(`generator.py`'s ``n + 900000``-style orphan IDs).
"""

from __future__ import annotations


class ScenarioIdAllocator:
    """Mints unique, scenario-sub-range IDs for one generation run.

    One instance is shared across every scenario generator invoked in a
    single run, so IDs never collide across scenarios within that run
    (each entity prefix has its own independent counter).
    """

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    def _next(self, key: str) -> int:
        n = self._counters.get(key, 0) + 1
        self._counters[key] = n
        return n

    def next_id(self, entity_prefix: str, width: int = 6) -> str:
        """A real, allocated scenario ID: ``SYN-<entity_prefix>-SCEN-<seq>``."""

        n = self._next(entity_prefix)
        return f"SYN-{entity_prefix}-SCEN-{n:0{width}d}"

    def dangling_id(self, entity_prefix: str, tag: str, width: int = 6) -> str:
        """An ID guaranteed to reference nothing real -- for negative-test
        scenarios that need a dangling/invalid reference on purpose.

        ``tag`` documents *why* it's dangling (e.g. ``"MEMBER"``,
        ``"PROVIDER"``) so the resulting ID is self-describing, e.g.
        ``SYN-CLM-SCEN-NX-MEMBER-000001`` reads as "a claim-shaped
        scenario record deliberately referencing a nonexistent member."
        """

        key = f"{entity_prefix}:NX:{tag}"
        n = self._next(key)
        return f"SYN-{entity_prefix}-SCEN-NX-{tag}-{n:0{width}d}"


__all__ = ["ScenarioIdAllocator"]
