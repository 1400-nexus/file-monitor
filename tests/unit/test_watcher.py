import asyncio
from pathlib import Path

import pytest

from file_monitor.services.watcher import DirectoryWatcher
from tests.fakes.fake_clock import FakeClock
from tests.fakes.fake_file_events import FakeFileEvents

RAPID_EVENT_COUNT = 5
SHORT_TIMEOUT_SECONDS = 0.05
LONG_TIMEOUT_SECONDS = 1


def make_watcher() -> tuple[DirectoryWatcher, FakeFileEvents]:
    file_events = FakeFileEvents()
    return DirectoryWatcher(file_events, FakeClock()), file_events


async def test_five_rapid_events_on_one_path_yield_exactly_one_output() -> None:
    watcher, file_events = make_watcher()
    listener = watcher.listen()
    path = Path("/watch/example.bin")

    for _ in range(RAPID_EVENT_COUNT):
        file_events.emit(path)

    stable_path = await asyncio.wait_for(anext(listener), timeout=LONG_TIMEOUT_SECONDS)
    assert stable_path == path

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(listener), timeout=SHORT_TIMEOUT_SECONDS)


async def test_events_on_different_paths_both_emit() -> None:
    watcher, file_events = make_watcher()
    listener = watcher.listen()
    path_a = Path("/watch/a.bin")
    path_b = Path("/watch/b.bin")

    file_events.emit(path_a)
    file_events.emit(path_b)

    seen = {await asyncio.wait_for(anext(listener), timeout=LONG_TIMEOUT_SECONDS) for _ in range(2)}
    assert seen == {path_a, path_b}


async def test_events_after_settling_each_produce_their_own_output() -> None:
    watcher, file_events = make_watcher()
    listener = watcher.listen()
    path = Path("/watch/example.bin")

    file_events.emit(path)
    first = await asyncio.wait_for(anext(listener), timeout=LONG_TIMEOUT_SECONDS)
    assert first == path

    file_events.emit(path)
    second = await asyncio.wait_for(anext(listener), timeout=LONG_TIMEOUT_SECONDS)
    assert second == path
