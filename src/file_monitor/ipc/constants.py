# Comfortably above the largest Envelope seen today (AssignSession carrying a
# Manifest, a few hundred bytes), leaving headroom for a future explicit
# block-list shard (potentially several KB). SOCK_SEQPACKET silently discards
# any part of a datagram beyond this size, so undersizing it produces
# truncated frames that fail to parse with no indication of why.
RECV_BUFFER_BYTES = 65536

SEND_QUEUE_MAXSIZE = 64
INCOMING_QUEUE_MAXSIZE = 256

ENVELOPE_ONEOF_GROUP_NAME = "msg"
SENDER_HELLO_FIELD_NAME = "sender_hello"
HEARTBEAT_FIELD_NAME = "heartbeat"
SENDER_PROGRESS_FIELD_NAME = "sender_progress"
SESSION_COMPLETE_FIELD_NAME = "session_complete"
LOCAL_CONGESTION_FIELD_NAME = "local_congestion"
ASSIGN_SESSION_FIELD_NAME = "assign_session"
UPDATE_RATE_FIELD_NAME = "update_rate"
ABORT_FIELD_NAME = "abort"
