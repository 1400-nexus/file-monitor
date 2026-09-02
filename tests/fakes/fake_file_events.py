import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path


class FakeFileEvents:
    def __init__(self) -> None:
        self._events: asyncio.Queue[Path] = asyncio.Queue()

    def emit(self, path: Path) -> None:
        self._events.put_nowait(path)

    async def listen(self) -> AsyncGenerator[Path, None]:
        while True:
            yield await self._events.get()
