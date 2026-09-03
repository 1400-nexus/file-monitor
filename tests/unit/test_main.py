import asyncio

import pytest

# file_monitor.main transitively imports the inotify adapter, which requires
# select.poll — unavailable on Windows. Skip this whole module there rather
# than crashing collection, matching the platform-skip pattern already used
# by tests/integration/test_uds.py for AF_UNIX.
main = pytest.importorskip("file_monitor.main", exc_type=ImportError)
_cancel_workers_on_shutdown = main._cancel_workers_on_shutdown

INFINITE_SLEEP_SECONDS = 100


async def _infinite_sleep() -> None:
    await asyncio.sleep(INFINITE_SLEEP_SECONDS)


async def test_setting_the_shutdown_event_cancels_workers_and_group_exits_normally() -> None:
    # Mirrors run()'s own TaskGroup shape: N worker tasks plus one task that
    # waits on the shutdown event and cancels the others. Setting the event
    # directly (no real signal) must let the `async with TaskGroup()` block
    # exit normally, with every worker cancelled — this is the exact
    # mechanism run() relies on to do its cleanup in a non-cancelled context.
    shutdown_event = asyncio.Event()
    reached_after_block = False

    async with asyncio.TaskGroup() as task_group:
        worker_tasks = [
            task_group.create_task(_infinite_sleep()),
            task_group.create_task(_infinite_sleep()),
            task_group.create_task(_infinite_sleep()),
        ]
        task_group.create_task(_cancel_workers_on_shutdown(shutdown_event, worker_tasks))
        shutdown_event.set()

    reached_after_block = True

    assert reached_after_block
    assert all(task.cancelled() for task in worker_tasks)


async def test_workers_keep_running_until_the_shutdown_event_is_set() -> None:
    shutdown_event = asyncio.Event()

    async with asyncio.TaskGroup() as task_group:
        worker_tasks = [task_group.create_task(_infinite_sleep())]
        task_group.create_task(_cancel_workers_on_shutdown(shutdown_event, worker_tasks))

        await asyncio.sleep(0)
        assert not worker_tasks[0].done()

        shutdown_event.set()

    assert worker_tasks[0].cancelled()
