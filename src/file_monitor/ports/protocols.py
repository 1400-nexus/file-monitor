from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Protocol

from file_monitor.domain.ids import SenderId


class Clock(Protocol):
    def now(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


class FileEvents(Protocol):
    def listen(self) -> AsyncIterator[Path]: ...


class Hasher(Protocol):
    async def compute_hash(self, path: Path) -> str: ...


class IpcServer(Protocol):
    async def serve(self) -> None: ...

    async def send(self, sender_id: SenderId, payload: bytes) -> None: ...

    def incoming(self) -> AsyncIterator[tuple[SenderId, bytes]]: ...


class ProcessSpawner(Protocol):
    async def spawn(self, argv: Sequence[str], env: dict[str, str] | None = None) -> object: ...

    def terminate(self, process: object) -> None: ...

    def kill(self, process: object) -> None: ...

    async def wait(self, process: object) -> int: ...
