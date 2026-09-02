import secrets

import common_pb2

from file_monitor.domain.models import FecParams, SourceFile
from file_monitor.domain.planning import calculate_block_count
from file_monitor.services.constants import SESSION_ID_RANDOM_BYTES, UNSET_SENDER_BPS_LIMIT


def generate_session_id() -> str:
    return secrets.token_hex(SESSION_ID_RANDOM_BYTES)


def encode_shard_key(sender_index: int) -> int:
    # The wire contract has no explicit block list: a sender derives its own
    # blocks as block_id % total_senders == Manifest.sender_id. This function
    # is the one place that maps a sender's position to that wire value, so
    # when an explicit shard oneof replaces the implicit modulo, only this
    # function's body and return type need to change.
    return sender_index


def build_manifest(
    source_file: SourceFile,
    fec_params: FecParams,
    session_id: str,
    sender_index: int,
    sender_bps_limit: int = UNSET_SENDER_BPS_LIMIT,
) -> common_pb2.Manifest:
    return common_pb2.Manifest(
        session_id=session_id,
        filepath=str(source_file.path),
        file_size=source_file.size_bytes,
        file_hash=bytes.fromhex(source_file.file_hash),
        k=fec_params.k,
        n=fec_params.n,
        # block_bytes is misnamed on the wire: it actually holds the per-symbol
        # size, not the block size. Pending a rename in nexus-proto.
        block_bytes=fec_params.symbol_bytes,
        total_blocks=calculate_block_count(source_file.size_bytes, fec_params),
        sender_id=encode_shard_key(sender_index),
        sender_bps_limit=sender_bps_limit,
    )
