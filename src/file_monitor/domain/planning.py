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


def derive_shard_assignments(
    total_blocks: int, active_senders: list[SenderId], base_port: int
) -> list[ShardAssignment]:
    sender_count = len(active_senders)
    assigned_blocks_by_index: list[list[BlockId]] = [[] for _ in range(sender_count)]
    for block_id in range(total_blocks):
        assigned_blocks_by_index[block_id % sender_count].append(BlockId(block_id))

    return [
        ShardAssignment(
            sender_id=sender_id,
            assigned_blocks=assigned_blocks_by_index[i],
            target_port=base_port + i,
        )
        for i, sender_id in enumerate(active_senders)
    ]
