import asyncio
from pathlib import Path

import pytest

from file_monitor.services.watcher import DirectoryWatcher
from tests.fakes.fake_clock import FakeClock
from tests.fakes.fake_file_events import FakeFileEvents

RAPID_EVENT_COUNT = 5
SHORT_TIMEOUT_SECONDS = 0.05
LONG_TIMEOUT_SECONDS = 1


class SteppableClock:
    def __init__(self) -> None:
        self._waiters: list[asyncio.Future[None]] = []

    def now(self) -> float:
        return 0.0

    async def sleep(self, seconds: float) -> None:
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waiters.append(waiter)
        await waiter

    def release_oldest(self) -> None:
        self._waiters.pop(0).set_result(None)


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


async def test_cancelling_the_listener_closes_the_underlying_file_events() -> None:
    watcher, file_events = make_watcher()
    listener = watcher.listen()

    task = asyncio.ensure_future(anext(listener))
    await asyncio.sleep(0)
    assert not file_events.closed

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert file_events.closed


async def test_consumer_failure_propagates_instead_of_hanging() -> None:
    watcher, file_events = make_watcher()
    listener = watcher.listen()

    file_events.fail(RuntimeError("inotify watch removed"))

    with pytest.raises(RuntimeError, match="inotify watch removed"):
        await asyncio.wait_for(anext(listener), timeout=LONG_TIMEOUT_SECONDS)


async def test_stale_task_waking_up_late_does_not_delete_a_newer_registration() -> None:
    file_events = FakeFileEvents()
    clock = SteppableClock()
    watcher = DirectoryWatcher(file_events, clock)
    path = Path("/watch/example.bin")

    watcher._debounce(path)
    stale_task = watcher._pending[path]
    await asyncio.sleep(0)

    newer_task = asyncio.create_task(watcher._emit_when_stable(path))
    watcher._pending[path] = newer_task
    await asyncio.sleep(0)

    clock.release_oldest()
    await asyncio.wait_for(stale_task, timeout=LONG_TIMEOUT_SECONDS)

    assert watcher._pending.get(path) is newer_task

    newer_task.cancel()
