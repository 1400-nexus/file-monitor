import argparse
import asyncio
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any, cast

import ipc_pb2

from file_monitor.ipc import codec, handshake
from file_monitor.ipc.constants import RECV_BUFFER_BYTES

DEFAULT_PROTO_DIR = "libs/nexus-proto/proto"
HEARTBEAT_INTERVAL_SECONDS = 1.0
EDGE_ID_COUNT = 5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Throwaway stand-in for the C++ sender, for exercising the wire contract."
    )
    parser.add_argument("--sender-id", type=int, required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--proto-dir", type=Path, default=Path(DEFAULT_PROTO_DIR))
    return parser.parse_args()


async def connect(socket_path: Path) -> socket.socket:
    loop = asyncio.get_running_loop()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    client.setblocking(False)
    await loop.sock_connect(client, str(socket_path))
    return client


async def send_hello(client: socket.socket, sender_id: int, proto_hash: bytes) -> None:
    loop = asyncio.get_running_loop()
    hello = ipc_pb2.SenderHello(sender_id=sender_id, pid=os.getpid(), proto_hash=proto_hash)
    await loop.sock_sendall(client, codec.encode(hello))


async def heartbeat_loop(client: socket.socket, sender_id: int) -> None:
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
        heartbeat = ipc_pb2.Heartbeat(
            process_id=os.getpid(), timestamp_unix_ms=int(time.time() * 1000)
        )
        await loop.sock_sendall(client, codec.encode(heartbeat))
        print(f"[sender {sender_id}] heartbeat sent", flush=True)


def print_assign_session(sender_id: int, assign_session: Any) -> None:
    manifest = assign_session.manifest

    filepath = Path(manifest.filepath)
    assert not filepath.is_absolute(), f"filepath must be relative, got {manifest.filepath!r}"
    assert ".." not in filepath.parts, f"filepath escapes watch root: {manifest.filepath!r}"

    print(f"[sender {sender_id}] AssignSession:")
    print(f"  session_id    = {manifest.session_id}")
    print(f"  filepath      = {manifest.filepath}")
    print(f"  file_size     = {manifest.file_size}")
    print(f"  total_blocks  = {manifest.total_blocks}")
    print(f"  k             = {manifest.k}")
    print(f"  n             = {manifest.n}")
    print(f"  block_bytes   = {manifest.block_bytes}")
    print(f"  sender_id     = {manifest.sender_id}  (shard residue, not --sender-id)")
    print(f"  total_senders = {assign_session.total_senders}")
    print(f"  target_host   = {assign_session.target_host}")
    print(f"  target_port   = {assign_session.target_port}")

    # This is the same residue arithmetic the C++ sender must perform on its
    # own side; if the convention drifts between the two implementations,
    # this is where it becomes visible.
    blocks = [
        block_id
        for block_id in range(manifest.total_blocks)
        if block_id % assign_session.total_senders == manifest.sender_id
    ]
    print(f"  block_count   = {len(blocks)}")
    print(f"  first blocks  = {blocks[:EDGE_ID_COUNT]}")
    print(f"  last blocks   = {blocks[-EDGE_ID_COUNT:]}")


async def receive_loop(
    client: socket.socket, sender_id: int, heartbeat_task: asyncio.Task[None]
) -> None:
    try:
        loop = asyncio.get_running_loop()
        while True:
            raw = await loop.sock_recv(client, RECV_BUFFER_BYTES)
            if not raw:
                print(f"[sender {sender_id}] connection closed by server", flush=True)
                return

            field_name, message = codec.decode(raw)
            if field_name == "assign_session":
                print_assign_session(sender_id, cast(Any, message))
            else:
                print(f"[sender {sender_id}] received {field_name}: {message}", flush=True)
    finally:
        heartbeat_task.cancel()


async def run(sender_id: int, socket_path: Path, proto_dir: Path) -> None:
    proto_hash = handshake.compute_proto_hash(proto_dir)
    client = await connect(socket_path)
    try:
        await send_hello(client, sender_id, proto_hash)
        print(f"[sender {sender_id}] connected, proto_hash={proto_hash.hex()}", flush=True)

        async with asyncio.TaskGroup() as task_group:
            heartbeat_task = task_group.create_task(heartbeat_loop(client, sender_id))
            task_group.create_task(receive_loop(client, sender_id, heartbeat_task))
    finally:
        client.close()


def main() -> int:
    args = parse_args()
    sender_id: int = args.sender_id
    socket_path: Path = args.socket
    proto_dir: Path = args.proto_dir

    try:
        asyncio.run(run(sender_id, socket_path, proto_dir))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
