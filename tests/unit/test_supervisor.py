import asyncio
from collections.abc import Callable

from file_monitor.supervision.supervisor import ChildSpec, ProcessSupervisor
from tests.fakes.fake_clock import FakeClock
from tests.fakes.fake_spawner import FakeProcess, FakeSpawner

POLL_TIMEOUT_SECONDS = 1


async def _wait_until(predicate: Callable[[], bool]) -> None:
    while not predicate():
        await asyncio.sleep(0)


async def _wait_for(predicate: Callable[[], bool]) -> None:
    await asyncio.wait_for(_wait_until(predicate), timeout=POLL_TIMEOUT_SECONDS)


async def test_child_restarts_on_exact_backoff_schedule() -> None:
    spec = ChildSpec(name="worker", argv=["worker"])
    spawner = FakeSpawner()
    clock = FakeClock()
    supervisor = ProcessSupervisor([spec], spawner, clock, backoff_schedule=(1.0, 2.0, 4.0))

    run_task = asyncio.create_task(supervisor.run())
    try:
        await _wait_for(lambda: len(spawner.spawned) >= 1)
        spawner.exit(spawner.spawned[0], 1)
        await _wait_for(lambda: clock.now() == 1.0)

        await _wait_for(lambda: len(spawner.spawned) >= 2)
        spawner.exit(spawner.spawned[1], 1)
        await _wait_for(lambda: clock.now() == 1.0 + 2.0)

        await _wait_for(lambda: len(spawner.spawned) >= 3)
        spawner.exit(spawner.spawned[2], 1)
        await _wait_for(lambda: clock.now() == 1.0 + 2.0 + 4.0)

        await _wait_for(lambda: len(spawner.spawned) >= 4)
    finally:
        await supervisor.shutdown()
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def test_five_rapid_deaths_produce_degraded_and_stop_restarts() -> None:
    spec = ChildSpec(name="crashy", argv=["crashy"])
    spawner = FakeSpawner()
    clock = FakeClock()
    supervisor = ProcessSupervisor(
        [spec],
        spawner,
        clock,
        backoff_schedule=(0.01,),
        crash_loop_max_restarts=5,
        crash_loop_window_seconds=60.0,
    )

    run_task = asyncio.create_task(supervisor.run())
    try:
        for death_index in range(5):
            await _wait_for(lambda: len(spawner.spawned) > death_index)
            spawner.exit(spawner.spawned[death_index], 1)

        await _wait_for(lambda: supervisor.is_degraded("crashy"))

        spawned_count_at_degraded = len(spawner.spawned)
        await asyncio.sleep(0.05)
        assert len(spawner.spawned) == spawned_count_at_degraded
    finally:
        await supervisor.shutdown()
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def test_other_children_keep_running_while_one_is_degraded() -> None:
    crashy = ChildSpec(name="crashy", argv=["crashy"])
    stable = ChildSpec(name="stable", argv=["stable"])
    spawner = FakeSpawner()
    clock = FakeClock()
    supervisor = ProcessSupervisor(
        [crashy, stable],
        spawner,
        clock,
        backoff_schedule=(0.01,),
        crash_loop_max_restarts=5,
        crash_loop_window_seconds=60.0,
    )

    def crashy_processes() -> list[FakeProcess]:
        return [process for process in spawner.spawned if process.argv == crashy.argv]

    def stable_processes() -> list[FakeProcess]:
        return [process for process in spawner.spawned if process.argv == stable.argv]

    run_task = asyncio.create_task(supervisor.run())
    try:
        await _wait_for(lambda: len(stable_processes()) >= 1)

        for death_index in range(5):
            await _wait_for(lambda: len(crashy_processes()) > death_index)
            spawner.exit(crashy_processes()[death_index], 1)

        await _wait_for(lambda: supervisor.is_degraded("crashy"))

        assert not supervisor.is_degraded("stable")
        assert len(stable_processes()) >= 1
        assert not stable_processes()[-1].exit_code.done()
    finally:
        await supervisor.shutdown()
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def test_shutdown_leaves_nothing_alive() -> None:
    spec_a = ChildSpec(name="a", argv=["a"])
    spec_b = ChildSpec(name="b", argv=["b"])
    spawner = FakeSpawner()
    clock = FakeClock()
    supervisor = ProcessSupervisor([spec_a, spec_b], spawner, clock)

    run_task = asyncio.create_task(supervisor.run())
    try:
        await _wait_for(lambda: len(spawner.spawned) >= 2)

        await asyncio.wait_for(supervisor.shutdown(), timeout=POLL_TIMEOUT_SECONDS)

        assert len(spawner.spawned) == 2
        assert all(process.terminated for process in spawner.spawned)
        assert all(process.exit_code.done() for process in spawner.spawned)

        await asyncio.wait_for(run_task, timeout=POLL_TIMEOUT_SECONDS)
        assert run_task.done()
    finally:
        if not run_task.done():
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)


async def test_shutdown_is_idempotent() -> None:
    spec = ChildSpec(name="worker", argv=["worker"])
    spawner = FakeSpawner()
    clock = FakeClock()
    supervisor = ProcessSupervisor([spec], spawner, clock)

    run_task = asyncio.create_task(supervisor.run())
    try:
        await _wait_for(lambda: len(spawner.spawned) >= 1)

        await asyncio.wait_for(supervisor.shutdown(), timeout=POLL_TIMEOUT_SECONDS)
        await asyncio.wait_for(supervisor.shutdown(), timeout=POLL_TIMEOUT_SECONDS)

        assert len(spawner.spawned) == 1
    finally:
        if not run_task.done():
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)
