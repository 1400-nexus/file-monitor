import asyncio
from collections.abc import Sequence
from typing import cast

KILL_EXIT_CODE = -9


class FakeProcess:
    def __init__(self, argv: Sequence[str], env: dict[str, str] | None) -> None:
        self.argv: Sequence[str] = argv
        self.env: dict[str, str] | None = env
        self.terminated: bool = False
        self.killed: bool = False
        self.exit_code: asyncio.Future[int] = asyncio.get_running_loop().create_future()


class FakeSpawner:
    def __init__(self) -> None:
        self.spawned: list[FakeProcess] = []

    async def spawn(self, argv: Sequence[str], env: dict[str, str] | None = None) -> FakeProcess:
        process = FakeProcess(argv, env)
        self.spawned.append(process)
        return process

    def terminate(self, process: object) -> None:
        cast(FakeProcess, process).terminated = True

    def kill(self, process: object) -> None:
        fake_process = cast(FakeProcess, process)
        fake_process.killed = True
        if not fake_process.exit_code.done():
            fake_process.exit_code.set_result(KILL_EXIT_CODE)

    async def wait(self, process: object) -> int:
        return await cast(FakeProcess, process).exit_code

    def exit(self, process: FakeProcess, code: int) -> None:
        if not process.exit_code.done():
            process.exit_code.set_result(code)
