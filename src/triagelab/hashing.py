"""Stable content hashing.

Cache keys, config fingerprints and dataset hashes all need the same property: two
logically-equal objects must hash identically on every machine and Python run. Plain
`hash()` is salted per process, and `json.dumps` without `sort_keys` depends on dict
insertion order, so neither is safe on its own.
"""

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> str:
    """Serialize `obj` to one canonical JSON string (sorted keys, no whitespace).

    `ensure_ascii=False` keeps non-English issue text byte-identical instead of escaping it,
    and `allow_nan=False` rejects NaN, which has no canonical JSON form.
    """
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def stable_hash(obj: Any) -> str:
    """SHA-256 hex digest of the canonical JSON form of `obj`."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()
