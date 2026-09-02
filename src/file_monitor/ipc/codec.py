import ipc_pb2
from google.protobuf.message import Message

from file_monitor.ipc.message_types import FIELD_NAME_BY_MESSAGE_TYPE


def encode(payload: Message) -> bytes:
    field_name = FIELD_NAME_BY_MESSAGE_TYPE[type(payload)]
    envelope = ipc_pb2.Envelope(**{field_name: payload})
    serialized: bytes = envelope.SerializeToString()
    return serialized


def decode(raw: bytes) -> tuple[str, Message]:
    envelope = ipc_pb2.Envelope()
    envelope.ParseFromString(raw)
    field_name = envelope.WhichOneof("msg")
    if field_name is None:
        raise ValueError("Envelope has no message set")
    return field_name, getattr(envelope, field_name)
