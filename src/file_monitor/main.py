import asyncio
import os
import signal
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

import ipc_pb2
import structlog
from google.protobuf.message import Message

from file_monitor.adapters.asyncio_process_spawner import AsyncioProcessSpawner
from file_monitor.adapters.blake3_hasher import Blake3Hasher
from file_monitor.adapters.inotify_events import INotifyEvents
from file_monitor.adapters.system_clock import SystemClock
from file_monitor.config import AppConfig, load_config
from file_monitor.constants import (
    CONFIG_ERROR_EXIT_CODE,
    DEFAULT_CONFIG_PATH,
    DEFAULT_PROTO_CONTRACT_DIR,
    NEXUS_CONFIG_ENV_VAR,
    PROTO_CONTRACT_DIR_ENV_VAR,
)
from file_monitor.domain.ids import SenderId, SessionId
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

IncomingMessageHandler = Callable[[SenderRegistry, SessionDispatcher, SenderId, Message], None]


def _handle_sender_hello(
    registry: SenderRegistry, dispatcher: SessionDispatcher, sender_id: SenderId, message: Message
) -> None:
    registry.register(sender_id)


def _handle_heartbeat(
    registry: SenderRegistry, dispatcher: SessionDispatcher, sender_id: SenderId, message: Message
) -> None:
    registry.refresh(sender_id)


def _handle_session_complete(
    registry: SenderRegistry, dispatcher: SessionDispatcher, sender_id: SenderId, message: Message
) -> None:
    session_complete = cast(ipc_pb2.SessionComplete, message)
    session_id = SessionId(session_complete.session_id)
    dispatcher.complete_session(session_id)
    logger.info(SESSION_COMPLETE_FIELD_NAME, sender_id=sender_id, session_id=session_id)


def _make_log_and_ignore_handler(event_name: str) -> IncomingMessageHandler:
    def handler(
        registry: SenderRegistry,
        dispatcher: SessionDispatcher,
        sender_id: SenderId,
        message: Message,
    ) -> None:
        logger.info(event_name, sender_id=sender_id)

    return handler


INCOMING_MESSAGE_HANDLERS: dict[str, IncomingMessageHandler] = {
    SENDER_HELLO_FIELD_NAME: _handle_sender_hello,
    HEARTBEAT_FIELD_NAME: _handle_heartbeat,
    SENDER_PROGRESS_FIELD_NAME: _make_log_and_ignore_handler(SENDER_PROGRESS_FIELD_NAME),
    SESSION_COMPLETE_FIELD_NAME: _handle_session_complete,
    LOCAL_CONGESTION_FIELD_NAME: _make_log_and_ignore_handler(LOCAL_CONGESTION_FIELD_NAME),
}


async def _run_incoming_dispatch_loop(
    ipc: IpcServer, registry: SenderRegistry, dispatcher: SessionDispatcher
) -> None:
    async for sender_id, raw in ipc.incoming():
        field_name, message = codec.decode(raw)
        handler = INCOMING_MESSAGE_HANDLERS.get(field_name)
        if handler is None:
            logger.warning(
                "unknown_incoming_message_type", field_name=field_name, sender_id=sender_id
            )
            continue
        handler(registry, dispatcher, sender_id, message)


async def _run_detection_pipeline(watcher: DirectoryWatcher, dispatcher: SessionDispatcher) -> None:
    async for path in watcher.listen():
        try:
            await dispatcher.dispatch(path)
        except Exception as error:
            logger.error("dispatch_failed_for_path", path=str(path), error=str(error))


async def _cancel_workers_on_shutdown(
    shutdown_event: asyncio.Event, worker_tasks: list[asyncio.Task[None]]
) -> None:
    await shutdown_event.wait()
    logger.info("shutdown_in_progress")
    for task in worker_tasks:
        task.cancel()


def _build_sender_specs(config: AppConfig) -> list[ChildSpec]:
    return [
        ChildSpec(
            name=f"sender-{index}",
            argv=[config.senders.binary_path, "--sender-id", str(index)],
        )
        for index in range(config.senders.sender_count)
    ]


async def run(config: AppConfig) -> int:
    proto_dir = Path(os.environ.get(PROTO_CONTRACT_DIR_ENV_VAR, DEFAULT_PROTO_CONTRACT_DIR))
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
        clock=clock,
        fec_params=config.fec,
        watch_root=config.paths.watch_path,
        target_host=config.senders.target_host,
        base_port=config.senders.base_port,
    )
    supervisor = ProcessSupervisor(_build_sender_specs(config), spawner, clock)

    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def trigger_shutdown() -> None:
        logger.info("shutdown_signal_received")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, trigger_shutdown)

    exit_code = 0
    try:
        async with asyncio.TaskGroup() as task_group:
            worker_tasks = [
                task_group.create_task(ipc.serve()),
                task_group.create_task(supervisor.run()),
                task_group.create_task(_run_incoming_dispatch_loop(ipc, registry, dispatcher)),
                task_group.create_task(_run_detection_pipeline(watcher, dispatcher)),
            ]
            task_group.create_task(_cancel_workers_on_shutdown(shutdown_event, worker_tasks))
            await asyncio.sleep(0)
            logger.info(
                "file_monitor_listening",
                socket_path=str(config.paths.socket_path),
                watch_path=str(config.paths.watch_path),
            )
    except* asyncio.CancelledError:
        pass  # defensive: normal shutdown exits the block above without raising
    except* Exception as exception_group:
        for error in exception_group.exceptions:
            logger.error("task_failed", error=str(error))
        exit_code = 1

    await supervisor.shutdown()
    config.paths.socket_path.unlink(missing_ok=True)

    return exit_code


def main() -> int:
    config_path = Path(os.environ.get(NEXUS_CONFIG_ENV_VAR, DEFAULT_CONFIG_PATH))
    try:
        config = load_config(config_path)
    except (ValueError, OSError) as error:
        logger.error("invalid_config", config_path=str(config_path), error=str(error))
        return CONFIG_ERROR_EXIT_CODE
    return asyncio.run(run(config))


if __name__ == "__main__":
    sys.exit(main())
