from dataclasses import dataclass
from pathlib import Path

from file_monitor.domain.ids import BlockId, SenderId


@dataclass(frozen=True)
class SourceFile:
    path: Path
    size_bytes: int
    file_hash: str


@dataclass(frozen=True)
class FecParams:
    k: int
    n: int
    symbol_bytes: int

    @property
    def block_size(self) -> int:
        return self.k * self.symbol_bytes


@dataclass(frozen=True)
class BlockPlan:
    block_id: BlockId
    start_byte: int
    end_byte: int


@dataclass(frozen=True)
class ShardAssignment:
    # shard_modulus/shard_residue are the values the sender must use to derive
    # its own blocks on the wire: block_id % shard_modulus == shard_residue.
    # This is positional (assigned by file_monitor), not the sender's own
    # process id — sender_id must never be substituted for shard_residue.
    sender_id: SenderId
    shard_modulus: int
    shard_residue: int
    assigned_blocks: list[BlockId]
    target_port: int
