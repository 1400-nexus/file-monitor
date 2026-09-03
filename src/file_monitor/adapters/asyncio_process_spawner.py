import asyncio
from collections.abc import Sequence
from typing import cast


class AsyncioProcessSpawner:
    async def spawn(
        self, argv: Sequence[str], env: dict[str, str] | None = None
    ) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(*argv, env=env)

    def terminate(self, process: object) -> None:
        cast(asyncio.subprocess.Process, process).terminate()

    def kill(self, process: object) -> None:
        cast(asyncio.subprocess.Process, process).kill()

    async def wait(self, process: object) -> int:
        return await cast(asyncio.subprocess.Process, process).wait()
