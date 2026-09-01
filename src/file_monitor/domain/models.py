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
    sender_id: SenderId
    assigned_blocks: list[BlockId]
    target_port: int
