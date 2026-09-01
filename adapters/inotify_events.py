import inotify_simple
import asyncio
from pathlib import Path
from typing import AsyncGenerator
from ports.protocols import FileEvents

class INotifyEvents(FileEvents):
    def __init__(self, watch_path: Path):
        self.watch_path = watch_path
        self.inotify = inotify_simple.INotify()
        mask = inotify_simple.flags.CLOSE_WRITE | inotify_simple.flags.MOVED_TO
        self.watch_descriptor = self.inotify.add_watch(str(watch_path), mask)

    async def listen(self) -> AsyncGenerator[Path, None]:
        while True:
            events = await asyncio.to_thread(self.inotify.read)
            for event in events:
                if event.mask & inotify_simple.flags.Q_OVERFLOW:
                    for item in self.watch_path.iterdir():
                        yield item
                elif event.mask & (inotify_simple.flags.CLOSE_WRITE | inotify_simple.flags.MOVED_TO):
                    yield self.watch_path / event.name