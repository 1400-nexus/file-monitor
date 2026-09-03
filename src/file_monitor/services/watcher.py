import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from file_monitor.ports.protocols import Clock, FileEvents
from file_monitor.services.constants import DEBOUNCE_SECONDS


class DirectoryWatcher:
    def __init__(
        self,
        file_events: FileEvents,
        clock: Clock,
        debounce_seconds: float = DEBOUNCE_SECONDS,
    ) -> None:
        self._file_events: FileEvents = file_events
        self._clock: Clock = clock
        self._debounce_seconds: float = debounce_seconds
        self._pending: dict[Path, asyncio.Task[None]] = {}
        self._stable_paths: asyncio.Queue[Path] = asyncio.Queue()

    def listen(self) -> AsyncIterator[Path]:
        return self._listen()

    async def _listen(self) -> AsyncIterator[Path]:
        consumer_task = asyncio.create_task(self._consume_raw_events())
        try:
            while True:
                get_task: asyncio.Task[Path] = asyncio.create_task(self._stable_paths.get())
                done, _pending_futures = await asyncio.wait(
                    {get_task, consumer_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if consumer_task in done:
                    get_task.cancel()
                    error = consumer_task.exception()
                    if error is not None:
                        raise error
                    raise RuntimeError("file event consumer task ended unexpectedly")
                yield get_task.result()
        finally:
            consumer_task.cancel()
            for pending_task in self._pending.values():
                pending_task.cancel()
            # Unblocks the underlying adapter's blocking read (e.g. inotify's
            # asyncio.to_thread call) — cancelling this task alone cannot
            # interrupt a syscall already blocked in a background thread, and
            # that thread staying alive is what prevents the interpreter from
            # exiting.
            self._file_events.close()

    async def _consume_raw_events(self) -> None:
        async for path in self._file_events.listen():
            self._debounce(path)

    def _debounce(self, path: Path) -> None:
        pending_task = self._pending.get(path)
        if pending_task is not None:
            pending_task.cancel()
        self._pending[path] = asyncio.create_task(self._emit_when_stable(path))

    async def _emit_when_stable(self, path: Path) -> None:
        await self._clock.sleep(self._debounce_seconds)
        current_task = asyncio.current_task()
        if self._pending.get(path) is current_task:
            self._pending.pop(path, None)
        await self._stable_paths.put(path)
