import asyncio
import socket
from collections.abc import Callable
from pathlib import Path

import ipc_pb2
import pytest

from file_monitor.domain.ids import SenderId
from file_monitor.ipc import codec
from file_monitor.ipc.constants import RECV_BUFFER_BYTES, SEND_QUEUE_MAXSIZE
from file_monitor.ipc.errors import SendQueueFullError, UnknownSenderError
from file_monitor.ipc.uds import UdsIpcServer

pytestmark = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"), reason="AF_UNIX sockets require a POSIX host"
)

EXPECTED_PROTO_HASH = b"expected-proto-hash"


async def connect_client(socket_path: Path) -> socket.socket:
    loop = asyncio.get_running_loop()
    while True:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        client.setblocking(False)
        try:
            await loop.sock_connect(client, str(socket_path))
            return client
        except (ConnectionRefusedError, FileNotFoundError):
            client.close()
            await asyncio.sleep(0.01)


async def send_hello(
    client: socket.socket, sender_id: int, proto_hash: bytes = EXPECTED_PROTO_HASH
) -> None:
    loop = asyncio.get_running_loop()
    hello = ipc_pb2.SenderHello(sender_id=sender_id, pid=1000 + sender_id, proto_hash=proto_hash)
    await loop.sock_sendall(client, codec.encode(hello))


async def test_serve_creates_missing_parent_directory(tmp_path: Path) -> None:
    socket_path = tmp_path / "nested" / "run" / "file-monitor.sock"
    server = UdsIpcServer(socket_path, expected_proto_hash=EXPECTED_PROTO_HASH)
    serve_task = asyncio.create_task(server.serve())
    try:
        await asyncio.wait_for(_wait_until(lambda: socket_path.exists()), timeout=1)
    finally:
        serve_task.cancel()
        await asyncio.gather(serve_task, return_exceptions=True)


async def test_serve_unlinks_a_stale_socket_file(tmp_path: Path) -> None:
    socket_path = tmp_path / "file-monitor.sock"
    socket_path.write_text("stale")
    server = UdsIpcServer(socket_path, expected_proto_hash=EXPECTED_PROTO_HASH)
    serve_task = asyncio.create_task(server.serve())
    try:
        client = await asyncio.wait_for(connect_client(socket_path), timeout=1)
        client.close()
    finally:
        serve_task.cancel()
        await asyncio.gather(serve_task, return_exceptions=True)


async def test_two_peers_exchange_messages_both_ways(tmp_path: Path) -> None:
    socket_path = tmp_path / "file-monitor.sock"
    server = UdsIpcServer(socket_path, expected_proto_hash=EXPECTED_PROTO_HASH)
    serve_task = asyncio.create_task(server.serve())
    loop = asyncio.get_running_loop()
    incoming = server.incoming()

    try:
        await asyncio.wait_for(_wait_until(lambda: socket_path.exists()), timeout=1)

        client_a = await connect_client(socket_path)
        await send_hello(client_a, sender_id=1)
        sender_a, hello_a_raw = await asyncio.wait_for(anext(incoming), timeout=1)
        assert sender_a == SenderId(1)
        assert codec.decode(hello_a_raw)[0] == "sender_hello"

        client_b = await connect_client(socket_path)
        await send_hello(client_b, sender_id=2)
        sender_b, hello_b_raw = await asyncio.wait_for(anext(incoming), timeout=1)
        assert sender_b == SenderId(2)
        assert codec.decode(hello_b_raw)[0] == "sender_hello"

        heartbeat = ipc_pb2.Heartbeat(process_id=1, timestamp_unix_ms=42)
        await loop.sock_sendall(client_a, codec.encode(heartbeat))
        sender_from_a, raw_from_a = await asyncio.wait_for(anext(incoming), timeout=1)
        assert sender_from_a == SenderId(1)
        assert codec.decode(raw_from_a) == ("heartbeat", heartbeat)

        assign = ipc_pb2.AssignSession(total_senders=2, target_host="127.0.0.1", target_port=9001)
        await server.send(SenderId(2), codec.encode(assign))
        received = await asyncio.wait_for(loop.sock_recv(client_b, RECV_BUFFER_BYTES), timeout=1)
        assert codec.decode(received) == ("assign_session", assign)

        client_a.close()
        await asyncio.wait_for(_wait_until(lambda: SenderId(1) not in server._peers), timeout=1)

        with pytest.raises(UnknownSenderError):
            await server.send(SenderId(1), b"anything")

        assert not serve_task.done()

        ack = ipc_pb2.SessionComplete(session_id="s1", packets_sent=10)
        await server.send(SenderId(2), codec.encode(ack))
        received_after = await asyncio.wait_for(
            loop.sock_recv(client_b, RECV_BUFFER_BYTES), timeout=1
        )
        assert codec.decode(received_after) == ("session_complete", ack)

        client_b.close()
    finally:
        serve_task.cancel()
        await asyncio.gather(serve_task, return_exceptions=True)


async def test_mismatched_proto_hash_is_refused(tmp_path: Path) -> None:
    socket_path = tmp_path / "file-monitor.sock"
    server = UdsIpcServer(socket_path, expected_proto_hash=EXPECTED_PROTO_HASH)
    serve_task = asyncio.create_task(server.serve())

    loop = asyncio.get_running_loop()
    try:
        await asyncio.wait_for(_wait_until(lambda: socket_path.exists()), timeout=1)

        client = await connect_client(socket_path)
        await send_hello(client, sender_id=1, proto_hash=b"stale-proto-hash")

        response = await asyncio.wait_for(loop.sock_recv(client, RECV_BUFFER_BYTES), timeout=1)
        assert response == b""

        assert SenderId(1) not in server._peers
        with pytest.raises(UnknownSenderError):
            await server.send(SenderId(1), b"anything")
        assert not serve_task.done()

        client.close()
    finally:
        serve_task.cancel()
        await asyncio.gather(serve_task, return_exceptions=True)


async def test_full_send_queue_raises_send_queue_full_error(tmp_path: Path) -> None:
    socket_path = tmp_path / "file-monitor.sock"
    server = UdsIpcServer(socket_path, expected_proto_hash=EXPECTED_PROTO_HASH)
    serve_task = asyncio.create_task(server.serve())

    try:
        await asyncio.wait_for(_wait_until(lambda: socket_path.exists()), timeout=1)

        client = await connect_client(socket_path)
        await send_hello(client, sender_id=1)
        await asyncio.wait_for(_wait_until(lambda: SenderId(1) in server._peers), timeout=1)

        payload = codec.encode(ipc_pb2.Heartbeat(process_id=1, timestamp_unix_ms=1))

        with pytest.raises(SendQueueFullError):
            for _ in range(SEND_QUEUE_MAXSIZE + 1):
                await server.send(SenderId(1), payload)

        client.close()
    finally:
        serve_task.cancel()
        await asyncio.gather(serve_task, return_exceptions=True)


async def test_write_loop_deregisters_peer_on_os_error() -> None:
    server = UdsIpcServer(Path("unused.sock"), expected_proto_hash=EXPECTED_PROTO_HASH)
    sender_id = SenderId(1)
    send_queue: asyncio.Queue[bytes] = asyncio.Queue()
    server._peers[sender_id] = send_queue

    server_side, client_side = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    server_side.setblocking(False)
    client_side.close()

    send_queue.put_nowait(b"payload")
    await asyncio.wait_for(server._write_loop(sender_id, server_side, send_queue), timeout=1)

    assert sender_id not in server._peers
    server_side.close()


async def _wait_until(predicate: Callable[[], bool]) -> None:
    while not predicate():
        await asyncio.sleep(0.01)
