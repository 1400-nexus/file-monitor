"""Cross-service proto_hash contract.

Both the Python file-monitor and the C++ sender/receiver must compute a
byte-identical hash of the shared .proto contract, so that a SenderHello
carrying a stale hash is refused before any data flows. The algorithm, in
enough detail to implement independently in any language:

1. List every file matching `*.proto` directly in the contract directory
   (no recursion).
2. Sort those filenames lexicographically (plain byte-wise ASCII sort).
3. Read each file's raw bytes — no decoding, no comment stripping, no
   whitespace normalization, no transformation of any kind.
4. Feed the raw bytes of each file, in that sorted order, into a single
   BLAKE3-256 hash, with no separator between files.
5. The digest is the standard 32-byte BLAKE3 output.

Trade-off: because the hash covers raw bytes, a comment-only edit to a
.proto file changes the hash and forces every process to rebuild against
the new contract. That is accepted deliberately — a reproducible check that
occasionally over-fires beats a "canonicalized" one that quietly diverges
between a Python and a C++ implementation and blocks all integration.
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
