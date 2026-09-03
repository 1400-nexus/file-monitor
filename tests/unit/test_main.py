import asyncio

import pytest

# file_monitor.main imports inotify_simple, which needs select.poll --
# absent on Windows. exc_type=ImportError: the default only skips on
# ModuleNotFoundError, which wouldn't catch this.
main = pytest.importorskip("file_monitor.main", exc_type=ImportError)
_cancel_workers_on_shutdown = main._cancel_workers_on_shutdown

INFINITE_SLEEP_SECONDS = 100


async def _infinite_sleep() -> None:
    await asyncio.sleep(INFINITE_SLEEP_SECONDS)


async def test_setting_the_shutdown_event_cancels_workers_and_group_exits_normally() -> None:
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
