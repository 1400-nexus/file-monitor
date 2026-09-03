import secrets
from pathlib import Path

import common_pb2
import ipc_pb2

from file_monitor.domain.ids import SessionId
from file_monitor.domain.models import FecParams, SourceFile
from file_monitor.domain.planning import calculate_block_count
from file_monitor.services.constants import (
    FILE_HASH_HEX_LENGTH,
    SESSION_ID_RANDOM_BYTES,
    UNSET_SENDER_BPS_LIMIT,
)


def generate_session_id() -> SessionId:
    # 16 lowercase hex chars (8 random bytes), not a UUID: this value rides on
    # every DataPacket on the wire (~978,000 packets per GB transferred), and
    # a 36-character UUID would leave only ~9 bytes of MTU headroom after the
    # rest of the packet header.
    return SessionId(secrets.token_hex(SESSION_ID_RANDOM_BYTES))


def apply_shard(manifest: common_pb2.Manifest, sender_index: int, shard_modulus: int) -> None:
    if shard_modulus < 1:
        raise ValueError(f"shard_modulus must be >= 1, got {shard_modulus}")
    if not 0 <= sender_index < shard_modulus:
        raise ValueError(
            "sender_index must satisfy 0 <= sender_index < shard_modulus "
            f"(shard_modulus={shard_modulus}), got sender_index={sender_index}"
        )
    manifest.sender_id = sender_index


def build_manifest(
    source_file: SourceFile,
    fec_params: FecParams,
    session_id: SessionId,
    sender_index: int,
    shard_modulus: int,
    watch_root: Path,
    sender_bps_limit: int = UNSET_SENDER_BPS_LIMIT,
) -> common_pb2.Manifest:
    if source_file.size_bytes < 0:
        raise ValueError(f"source_file.size_bytes must be >= 0, got {source_file.size_bytes}")

    if len(source_file.file_hash) != FILE_HASH_HEX_LENGTH:
        raise ValueError(
            f"source_file.file_hash must be {FILE_HASH_HEX_LENGTH} hex characters, "
            f"got {len(source_file.file_hash)}"
        )
    try:
        file_hash_bytes = bytes.fromhex(source_file.file_hash)
    except ValueError as error:
        raise ValueError(
            f"source_file.file_hash is not valid hex: {source_file.file_hash!r}"
        ) from error

    try:
        relative_path = source_file.path.relative_to(watch_root)
    except ValueError as error:
        raise ValueError(
            f"source_file.path {source_file.path} is not under watch_root {watch_root}"
        ) from error
    if ".." in relative_path.parts:
        raise ValueError(f"source_file.path {source_file.path} escapes watch_root via '..'")

    # RX joins this onto its own output directory, so it must never be
    # absolute and must never contain "..", or it could write outside that
    # directory or leak the TX machine's directory layout. Always POSIX
    # separators on the wire, regardless of the TX host's OS.
    filepath = relative_path.as_posix()

    manifest = common_pb2.Manifest(
        session_id=session_id,
        filepath=filepath,
        file_size=source_file.size_bytes,
        file_hash=file_hash_bytes,
        k=fec_params.k,
        n=fec_params.n,
        # block_bytes is misnamed on the wire: it actually holds the per-symbol
        # size, not the block size. Pending a rename in nexus-proto.
        block_bytes=fec_params.symbol_bytes,
        total_blocks=calculate_block_count(source_file.size_bytes, fec_params),
        sender_bps_limit=sender_bps_limit,
    )
    apply_shard(manifest, sender_index, shard_modulus)
    return manifest


def build_assign_session(
    manifest: common_pb2.Manifest,
    shard_modulus: int,
    target_host: str,
    target_port: int,
) -> ipc_pb2.AssignSession:
    return ipc_pb2.AssignSession(
        manifest=manifest,
        total_senders=shard_modulus,
        target_host=target_host,
        target_port=target_port,
    )
