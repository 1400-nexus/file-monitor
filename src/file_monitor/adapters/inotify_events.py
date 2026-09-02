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

    async def listen(self) -> AsyncGenerator[Path, None]:
        while True:
            events = await asyncio.to_thread(self.inotify.read)
            for event in events:
                if event.mask & inotify_simple.flags.Q_OVERFLOW:
                    for item in self.watch_path.iterdir():
                        yield item
                elif event.mask & (
                    inotify_simple.flags.CLOSE_WRITE | inotify_simple.flags.MOVED_TO
                ):
                    yield self.watch_path / event.name
