import ipc_pb2
from google.protobuf.message import Message

FIELD_NAME_BY_MESSAGE_TYPE: dict[type[Message], str] = {
    ipc_pb2.SenderHello: "sender_hello",
    ipc_pb2.Heartbeat: "heartbeat",
    ipc_pb2.SenderProgress: "sender_progress",
    ipc_pb2.SessionComplete: "session_complete",
    ipc_pb2.LocalCongestion: "local_congestion",
    ipc_pb2.AssignSession: "assign_session",
    ipc_pb2.UpdateRate: "update_rate",
    ipc_pb2.Abort: "abort",
}
