from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple
from .ids import SessionId, SenderId

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

@dataclass(frozen=True)
class BlockPlan:
    block_id: int
    start_byte: int
    end_byte: int

@dataclass(frozen=True)
class ShardAssignment:
    sender_id: SenderId
    assigned_blocks: List[int]
    target_port: int