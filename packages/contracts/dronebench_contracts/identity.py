"""Identity, canonical JSON, and content hashing (architecture §5).

Two rules drive this module.

* Identity is assigned once and preserved. Names, mesh triangle counts, and file positions are not
  identifiers; ambiguous rematches are errors rather than silent identity swaps.
* A content hash covers immutable inputs in canonical sorted JSON. Display-only timestamps are
  excluded, and an artifact's own hash is never embedded in the bytes it hashes — checksums live
  in the enclosing manifest.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Final, Iterable

# --------------------------------------------------------------------------------------------
# Identifier shapes
# --------------------------------------------------------------------------------------------

DESIGN_ID_RE: Final = re.compile(r"^dsn_[a-z0-9][a-z0-9_-]{2,62}$")
REVISION_ID_RE: Final = re.compile(r"^rev_[0-9a-f]{16}$")
PART_ID_RE: Final = re.compile(r"^prt_[a-z0-9][a-z0-9_.-]{1,62}$")
DEFINITION_ID_RE: Final = re.compile(r"^def_[a-z0-9][a-z0-9_.-]{1,62}$")
EVIDENCE_ID_RE: Final = re.compile(r"^ev_[a-z0-9][a-z0-9_.-]{1,62}$")
PROPOSAL_ID_RE: Final = re.compile(r"^rec_[a-z0-9][a-z0-9_.-]{1,62}$")
JOB_ID_RE: Final = re.compile(r"^job_[a-z0-9][a-z0-9_.-]{1,62}$")
RUN_ID_RE: Final = re.compile(r"^run_[a-z0-9][a-z0-9_.-]{1,62}$")
ARTIFACT_ID_RE: Final = re.compile(r"^art_[0-9a-f]{16}$")

#: Keys stripped before hashing: they are display-only and must not perturb a content hash.
DISPLAY_ONLY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "created_at",
        "updated_at",
        "accessed_at",
        "elapsed_s",
        "display_name",
        "note",
        "_display",
    }
)


class IdentityError(ValueError):
    """Raised when an identifier is malformed or an identity rematch is ambiguous."""


def _check(pattern: re.Pattern[str], value: str, kind: str) -> str:
    if not pattern.match(value):
        raise IdentityError(f"{kind} {value!r} does not match {pattern.pattern}")
    return value


def check_design_id(value: str) -> str:
    return _check(DESIGN_ID_RE, value, "design_id")


def check_revision_id(value: str) -> str:
    return _check(REVISION_ID_RE, value, "revision_id")


def check_part_id(value: str) -> str:
    return _check(PART_ID_RE, value, "part_id")


def check_definition_id(value: str) -> str:
    return _check(DEFINITION_ID_RE, value, "definition_id")


def check_evidence_id(value: str) -> str:
    return _check(EVIDENCE_ID_RE, value, "evidence_id")


# --------------------------------------------------------------------------------------------
# Canonical JSON
# --------------------------------------------------------------------------------------------


class NonFiniteNumberError(ValueError):
    """JSON must not contain NaN or Infinity (architecture §13, contract checks)."""


def assert_finite(obj: Any, path: str = "$") -> None:
    """Recursively reject NaN/Infinity anywhere in a JSON-compatible structure."""
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise NonFiniteNumberError(f"non-finite float at {path}: {obj!r}")
    elif isinstance(obj, dict):
        for key, value in obj.items():
            assert_finite(value, f"{path}.{key}")
    elif isinstance(obj, (list, tuple)):
        for index, value in enumerate(obj):
            assert_finite(value, f"{path}[{index}]")


def strip_display_only(obj: Any) -> Any:
    """Drop display-only keys so they cannot perturb a content hash."""
    if isinstance(obj, dict):
        return {
            key: strip_display_only(value)
            for key, value in obj.items()
            if key not in DISPLAY_ONLY_KEYS
        }
    if isinstance(obj, list):
        return [strip_display_only(value) for value in obj]
    return obj


def canonical_json(obj: Any, *, for_hashing: bool = False) -> str:
    """Deterministic JSON: sorted keys, tight separators, no NaN/Infinity.

    ``for_hashing`` additionally removes display-only keys.
    """
    payload = strip_display_only(obj) if for_hashing else obj
    assert_finite(payload)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_bytes(obj: Any, *, for_hashing: bool = False) -> bytes:
    return canonical_json(obj, for_hashing=for_hashing).encode("utf-8")


# --------------------------------------------------------------------------------------------
# Hashing
# --------------------------------------------------------------------------------------------


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path, *, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def content_hash(obj: Any, *, extra_bytes: Iterable[bytes] = ()) -> str:
    """Content hash of a structure plus any immutable source bytes.

    Source bytes are folded in by their own digests so a large mesh never has to be held in memory
    twice, and so ordering is explicit rather than dependent on filesystem iteration.
    """
    digest = hashlib.sha256()
    digest.update(canonical_bytes(obj, for_hashing=True))
    for blob in extra_bytes:
        digest.update(b"\x00")
        digest.update(hashlib.sha256(blob).digest())
    return digest.hexdigest()


def revision_id_from_hash(hash_hex: str) -> str:
    """Derive a revision id from a content hash. Same content in the same lineage -> same id."""
    return f"rev_{hash_hex[:16]}"


def artifact_id_from_hash(hash_hex: str) -> str:
    return f"art_{hash_hex[:16]}"
