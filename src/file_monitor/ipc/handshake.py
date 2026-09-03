"""The C++ side must reproduce this hash byte-for-byte from raw file bytes
(no canonicalization), so a comment-only .proto edit changes it on purpose —
a reproducible check that occasionally over-fires beats one that can
silently diverge between languages.
"""

from pathlib import Path

import blake3

from file_monitor.domain.ids import SenderId
from file_monitor.ipc.errors import ProtoHashMismatchError


def compute_proto_hash(proto_dir: Path) -> bytes:
    hasher = blake3.blake3()
    for path in sorted(proto_dir.glob("*.proto")):
        hasher.update(path.read_bytes())
    return hasher.digest()


def verify_proto_hash(sender_id: SenderId, reported_hash: bytes, expected_hash: bytes) -> None:
    if reported_hash != expected_hash:
        raise ProtoHashMismatchError(sender_id, reported_hash, expected_hash)
