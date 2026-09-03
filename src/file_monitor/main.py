import asyncio
import os
import signal
import sys
from collections.abc import Callable
from pathlib import Path

import structlog
from google.protobuf.message import Message

from file_monitor.adapters.asyncio_process_spawner import AsyncioProcessSpawner
from file_monitor.adapters.blake3_hasher import Blake3Hasher
from file_monitor.adapters.inotify_events import INotifyEvents
from file_monitor.adapters.system_clock import SystemClock
from file_monitor.config import AppConfig, load_config
from file_monitor.constants import (
    DEFAULT_BASE_PORT,
    DEFAULT_CONFIG_PATH,
    DEFAULT_TARGET_HOST,
    NEXUS_CONFIG_ENV_VAR,
    PROTO_CONTRACT_DIR,
    SENDER_BINARY_PATH,
    SENDER_COUNT,
)
from file_monitor.domain.ids import SenderId
from file_monitor.ipc import codec, handshake
from file_monitor.ipc.constants import (
    HEARTBEAT_FIELD_NAME,
    LOCAL_CONGESTION_FIELD_NAME,
    SENDER_HELLO_FIELD_NAME,
    SENDER_PROGRESS_FIELD_NAME,
    SESSION_COMPLETE_FIELD_NAME,
)
from file_monitor.ipc.uds import UdsIpcServer
from file_monitor.ports.protocols import IpcServer
from file_monitor.services.constants import HEARTBEAT_INTERVAL_SECONDS
from file_monitor.services.dispatcher import SessionDispatcher
from file_monitor.services.registry import SenderRegistry
from file_monitor.services.watcher import DirectoryWatcher
from file_monitor.supervision.supervisor import ChildSpec, ProcessSupervisor

logger = structlog.get_logger(__name__)

IncomingMessageHandler = Callable[[SenderRegistry, SenderId, Message], None]


def _handle_sender_hello(registry: SenderRegistry, sender_id: SenderId, message: Message) -> None:
    registry.register(sender_id)


def _handle_heartbeat(registry: SenderRegistry, sender_id: SenderId, message: Message) -> None:
    registry.refresh(sender_id)


def _make_log_and_ignore_handler(event_name: str) -> IncomingMessageHandler:
    def handler(registry: SenderRegistry, sender_id: SenderId, message: Message) -> None:
        logger.info(event_name, sender_id=sender_id)

    return handler


INCOMING_MESSAGE_HANDLERS: dict[str, IncomingMessageHandler] = {
    SENDER_HELLO_FIELD_NAME: _handle_sender_hello,
    HEARTBEAT_FIELD_NAME: _handle_heartbeat,
    SENDER_PROGRESS_FIELD_NAME: _make_log_and_ignore_handler(SENDER_PROGRESS_FIELD_NAME),
    SESSION_COMPLETE_FIELD_NAME: _make_log_and_ignore_handler(SESSION_COMPLETE_FIELD_NAME),
    LOCAL_CONGESTION_FIELD_NAME: _make_log_and_ignore_handler(LOCAL_CONGESTION_FIELD_NAME),
}


async def _run_incoming_dispatch_loop(ipc: IpcServer, registry: SenderRegistry) -> None:
    async for sender_id, raw in ipc.incoming():
        field_name, message = codec.decode(raw)
        handler = INCOMING_MESSAGE_HANDLERS.get(field_name)
        if handler is None:
            logger.warning(
                "unknown_incoming_message_type", field_name=field_name, sender_id=sender_id
            )
            continue
        handler(registry, sender_id, message)


async def _run_detection_pipeline(watcher: DirectoryWatcher, dispatcher: SessionDispatcher) -> None:
    async for path in watcher.listen():
        try:
            await dispatcher.dispatch(path)
        except Exception as error:
            logger.error("dispatch_failed_for_path", path=str(path), error=str(error))


def _build_sender_specs() -> list[ChildSpec]:
    return [
        ChildSpec(name=f"sender-{index}", argv=[SENDER_BINARY_PATH, "--sender-id", str(index)])
        for index in range(SENDER_COUNT)
    ]


async def run(config: AppConfig) -> int:
    proto_dir = Path(PROTO_CONTRACT_DIR)
    if not proto_dir.is_dir():
        logger.error(
            "proto_contract_missing",
            proto_dir=str(proto_dir),
            hint="the nexus-proto submodule may not be initialised — "
            "run: git submodule update --init",
        )
        return 1
    expected_proto_hash = handshake.compute_proto_hash(proto_dir)

    clock = SystemClock()
    hasher = Blake3Hasher()
    file_events = INotifyEvents(config.paths.watch_path)
    ipc = UdsIpcServer(config.paths.socket_path, expected_proto_hash=expected_proto_hash)
    spawner = AsyncioProcessSpawner()

    registry = SenderRegistry(clock, heartbeat_interval_seconds=HEARTBEAT_INTERVAL_SECONDS)
    watcher = DirectoryWatcher(file_events, clock)
    dispatcher = SessionDispatcher(
        ipc=ipc,
        hasher=hasher,
        registry=registry,
        fec_params=config.fec,
        watch_root=config.paths.watch_path,
        target_host=DEFAULT_TARGET_HOST,
        base_port=DEFAULT_BASE_PORT,
    )
    supervisor = ProcessSupervisor(_build_sender_specs(), spawner, clock)

    loop = asyncio.get_running_loop()
    run_task = asyncio.current_task()
    assert run_task is not None

    def trigger_shutdown() -> None:
        logger.info("shutdown_signal_received")
        run_task.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, trigger_shutdown)

    exit_code = 0
    try:
        async with asyncio.TaskGroup() as task_group:
            task_group.create_task(ipc.serve())
            task_group.create_task(supervisor.run())
            task_group.create_task(_run_incoming_dispatch_loop(ipc, registry))
            task_group.create_task(_run_detection_pipeline(watcher, dispatcher))
            await asyncio.sleep(0)
            logger.info(
                "file_monitor_listening",
                socket_path=str(config.paths.socket_path),
                watch_path=str(config.paths.watch_path),
            )
    except* asyncio.CancelledError:
        logger.info("shutdown_in_progress")
    except* Exception as exception_group:
        for error in exception_group.exceptions:
            logger.error("task_failed", error=str(error))
        exit_code = 1
    finally:
        await supervisor.shutdown()
        config.paths.socket_path.unlink(missing_ok=True)

    return exit_code


def main() -> int:
    config = load_config(Path(os.environ.get(NEXUS_CONFIG_ENV_VAR, DEFAULT_CONFIG_PATH)))
    return asyncio.run(run(config))


if __name__ == "__main__":
    sys.exit(main())
