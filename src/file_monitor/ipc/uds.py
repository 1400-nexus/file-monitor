import asyncio
import socket
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import structlog

from file_monitor.domain.ids import SenderId
from file_monitor.ipc import codec, handshake
from file_monitor.ipc.constants import (
    RECV_BUFFER_BYTES,
    SEND_QUEUE_MAXSIZE,
    SENDER_HELLO_FIELD_NAME,
)
from file_monitor.ipc.errors import HandshakeError, ProtoHashMismatchError, UnknownSenderError

logger = structlog.get_logger(__name__)


class UdsIpcServer:
    def __init__(self, socket_path: Path, expected_proto_hash: bytes) -> None:
        self._socket_path: Path = socket_path
        self._expected_proto_hash: bytes = expected_proto_hash
        self._peers: dict[SenderId, asyncio.Queue[bytes]] = {}
        self._peer_tasks: set[asyncio.Task[None]] = set()
        self._incoming: asyncio.Queue[tuple[SenderId, bytes]] = asyncio.Queue()

    async def serve(self) -> None:
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)
        self._socket_path.unlink(missing_ok=True)

        listen_socket = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        listen_socket.setblocking(False)
        listen_socket.bind(str(self._socket_path))
        listen_socket.listen()

        loop = asyncio.get_running_loop()
        try:
            while True:
                connection, _ = await loop.sock_accept(listen_socket)
                connection.setblocking(False)
                task = asyncio.create_task(self._handle_peer(connection))
                self._peer_tasks.add(task)
                task.add_done_callback(self._on_peer_task_done)
        finally:
            listen_socket.close()
            for task in self._peer_tasks:
                task.cancel()
            await asyncio.gather(*self._peer_tasks, return_exceptions=True)

    def _on_peer_task_done(self, task: asyncio.Task[None]) -> None:
        self._peer_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error("peer_task_failed", error=str(error))

    async def _handle_peer(self, connection: socket.socket) -> None:
        loop = asyncio.get_running_loop()
        sender_id: SenderId | None = None
        send_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=SEND_QUEUE_MAXSIZE)
        writer_task: asyncio.Task[None] | None = None
        try:
            while True:
                raw = await loop.sock_recv(connection, RECV_BUFFER_BYTES)
                if not raw:
                    break

                if sender_id is None:
                    sender_id, writer_task = self._complete_handshake(connection, send_queue, raw)

                await self._incoming.put((sender_id, raw))
        except HandshakeError as error:
            logger.warning("peer_handshake_failed", error=str(error))
        except ProtoHashMismatchError as error:
            logger.error("peer_proto_hash_mismatch", error=str(error))
        finally:
            if sender_id is not None:
                if self._peers.get(sender_id) is send_queue:
                    del self._peers[sender_id]
                logger.info("peer_disconnected", sender_id=sender_id)
            if writer_task is not None:
                writer_task.cancel()
            connection.close()

    def _complete_handshake(
        self, connection: socket.socket, send_queue: asyncio.Queue[bytes], raw: bytes
    ) -> tuple[SenderId, asyncio.Task[None]]:
        field_name, message = codec.decode(raw)
        if field_name != SENDER_HELLO_FIELD_NAME:
            raise HandshakeError(field_name)
        hello = cast(Any, message)
        sender_id = SenderId(hello.sender_id)
        handshake.verify_proto_hash(sender_id, hello.proto_hash, self._expected_proto_hash)
        self._peers[sender_id] = send_queue
        writer_task = asyncio.create_task(self._write_loop(connection, send_queue))
        logger.info("peer_connected", sender_id=sender_id)
        return sender_id, writer_task

    async def _write_loop(self, connection: socket.socket, queue: asyncio.Queue[bytes]) -> None:
        loop = asyncio.get_running_loop()
        while True:
            payload = await queue.get()
            await loop.sock_sendall(connection, payload)

    async def send(self, sender_id: SenderId, payload: bytes) -> None:
        queue = self._peers.get(sender_id)
        if queue is None:
            raise UnknownSenderError(sender_id)
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning("peer_send_queue_full_dropping_message", sender_id=sender_id)

    def incoming(self) -> AsyncIterator[tuple[SenderId, bytes]]:
        return self._iter_incoming()

    async def _iter_incoming(self) -> AsyncIterator[tuple[SenderId, bytes]]:
        while True:
            yield await self._incoming.get()
