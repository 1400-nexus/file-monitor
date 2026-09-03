import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

import inotify_simple


class INotifyEvents:
    def __init__(self, watch_path: Path) -> None:
        self._watch_path: Path = watch_path
        self._inotify: inotify_simple.INotify = inotify_simple.INotify()
        mask = inotify_simple.flags.CLOSE_WRITE | inotify_simple.flags.MOVED_TO
        self._watch_descriptor: int = self._inotify.add_watch(str(watch_path), mask)
        self._closed: bool = False

    def close(self) -> None:
        # self._inotify.close() alone won't wake a thread blocked in poll().
        self._closed = True
        try:
            self._inotify.rm_watch(self._watch_descriptor)
        except OSError:
            pass

    async def listen(self) -> AsyncGenerator[Path, None]:
        while not self._closed:
            events = await asyncio.to_thread(self._inotify.read)
            if self._closed:
                break
            for event in events:
                if event.mask & inotify_simple.flags.Q_OVERFLOW:
                    for item in self._watch_path.iterdir():
                        yield item
                elif event.mask & (
                    inotify_simple.flags.CLOSE_WRITE | inotify_simple.flags.MOVED_TO
                ):
                    yield self._watch_path / event.name
