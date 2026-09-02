from pathlib import Path

import blake3

from file_monitor.domain.ids import SenderId
from file_monitor.ipc.constants import (
    BLOCK_COMMENT_PATTERN,
    LINE_COMMENT_PATTERN,
    WHITESPACE_PATTERN,
)
from file_monitor.ipc.errors import ProtoHashMismatchError


def canonicalize_proto_text(text: str) -> str:
    without_block_comments = BLOCK_COMMENT_PATTERN.sub(" ", text)
    without_comments = LINE_COMMENT_PATTERN.sub(" ", without_block_comments)
    return WHITESPACE_PATTERN.sub(" ", without_comments).strip()


def compute_proto_hash(proto_dir: Path) -> bytes:
    proto_files = sorted(proto_dir.glob("*.proto"))
    canonical_text = "\n".join(
        canonicalize_proto_text(path.read_text(encoding="utf-8")) for path in proto_files
    )
    return blake3.blake3(canonical_text.encode("utf-8")).digest()


def verify_proto_hash(sender_id: SenderId, reported_hash: bytes, expected_hash: bytes) -> None:
    if reported_hash != expected_hash:
        raise ProtoHashMismatchError(sender_id, reported_hash, expected_hash)
