import ipc_pb2
from google.protobuf.message import Message

from file_monitor.ipc.constants import (
    ABORT_FIELD_NAME,
    ASSIGN_SESSION_FIELD_NAME,
    HEARTBEAT_FIELD_NAME,
    LOCAL_CONGESTION_FIELD_NAME,
    SENDER_HELLO_FIELD_NAME,
    SENDER_PROGRESS_FIELD_NAME,
    SESSION_COMPLETE_FIELD_NAME,
    UPDATE_RATE_FIELD_NAME,
)

FIELD_NAME_BY_MESSAGE_TYPE: dict[type[Message], str] = {
    ipc_pb2.SenderHello: SENDER_HELLO_FIELD_NAME,
    ipc_pb2.Heartbeat: HEARTBEAT_FIELD_NAME,
    ipc_pb2.SenderProgress: SENDER_PROGRESS_FIELD_NAME,
    ipc_pb2.SessionComplete: SESSION_COMPLETE_FIELD_NAME,
    ipc_pb2.LocalCongestion: LOCAL_CONGESTION_FIELD_NAME,
    ipc_pb2.AssignSession: ASSIGN_SESSION_FIELD_NAME,
    ipc_pb2.UpdateRate: UPDATE_RATE_FIELD_NAME,
    ipc_pb2.Abort: ABORT_FIELD_NAME,
}
