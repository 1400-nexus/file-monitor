"""ShardAssignment.shard_residue is positional (from enumerating active
senders), never the sender's own SenderId: a sender transmits
block_id % shard_modulus == shard_residue using the given values, not its
own identity.
"""

import math

from file_monitor.domain.ids import BlockId, SenderId
from file_monitor.domain.models import BlockPlan, FecParams, ShardAssignment


def calculate_block_count(file_size: int, fec_params: FecParams) -> int:
    return math.ceil(file_size / fec_params.block_size)


def compute_block_plans(file_size: int, fec_params: FecParams) -> list[BlockPlan]:
    block_count = calculate_block_count(file_size, fec_params)
    block_size = fec_params.block_size
    block_plans = []
    for i in range(block_count):
        start_byte = i * block_size
        end_byte = min(start_byte + block_size, file_size)
        block_plans.append(BlockPlan(block_id=BlockId(i), start_byte=start_byte, end_byte=end_byte))
    return block_plans


def blocks_for_shard(total_blocks: int, modulus: int, residue: int) -> list[BlockId]:
    return [BlockId(block_id) for block_id in range(total_blocks) if block_id % modulus == residue]


def derive_shard_assignments(
    total_blocks: int, active_senders: list[SenderId], base_port: int
) -> list[ShardAssignment]:
    if not active_senders:
        raise ValueError("active_senders must not be empty")

    seen: set[SenderId] = set()
    duplicate_sender_ids: set[SenderId] = set()
    for sender_id in active_senders:
        if sender_id in seen:
            duplicate_sender_ids.add(sender_id)
        seen.add(sender_id)
    if duplicate_sender_ids:
        raise ValueError(
            f"active_senders contains duplicate sender ids: {sorted(duplicate_sender_ids)}"
        )

    if total_blocks < 0:
        raise ValueError(f"total_blocks must be >= 0, got {total_blocks}")

    if base_port <= 0:
        raise ValueError(f"base_port must be > 0, got {base_port}")

    shard_modulus = len(active_senders)
    return [
        ShardAssignment(
            sender_id=sender_id,
            shard_modulus=shard_modulus,
            shard_residue=shard_residue,
            assigned_blocks=blocks_for_shard(total_blocks, shard_modulus, shard_residue),
            target_port=base_port + shard_residue,
        )
        for shard_residue, sender_id in enumerate(active_senders)
    ]
