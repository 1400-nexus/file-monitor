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
        # Closing the fd doesn't reliably wake a thread blocked in poll() on
        # it; rm_watch() does, via a kernel-generated IN_IGNORED event.
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
