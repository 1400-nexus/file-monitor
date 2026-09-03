import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

import inotify_simple


class INotifyEvents:
    def __init__(self, watch_path: Path) -> None:
        self.watch_path: Path = watch_path
        self.inotify: inotify_simple.INotify = inotify_simple.INotify()
        mask = inotify_simple.flags.CLOSE_WRITE | inotify_simple.flags.MOVED_TO
        self.watch_descriptor: int = self.inotify.add_watch(str(watch_path), mask)
        self._closed: bool = False

    def close(self) -> None:
        # asyncio.to_thread's worker thread is blocked in poll() on this fd;
        # cancelling the asyncio task awaiting it does not touch that thread,
        # and closing the fd out from under a thread blocked in poll() is not
        # reliable on Linux. Removing the watch makes the kernel enqueue an
        # IN_IGNORED event, which reliably wakes the blocked read().
        self._closed = True
        try:
            self.inotify.rm_watch(self.watch_descriptor)
        except OSError:
            pass

    async def listen(self) -> AsyncGenerator[Path, None]:
        while not self._closed:
            events = await asyncio.to_thread(self.inotify.read)
            if self._closed:
                break
            for event in events:
                if event.mask & inotify_simple.flags.Q_OVERFLOW:
                    for item in self.watch_path.iterdir():
                        yield item
                elif event.mask & (
                    inotify_simple.flags.CLOSE_WRITE | inotify_simple.flags.MOVED_TO
                ):
                    yield self.watch_path / event.name
