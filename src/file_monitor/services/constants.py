MISSED_HEARTBEAT_LIMIT = 3
HEARTBEAT_INTERVAL_SECONDS = 5.0
DEBOUNCE_SECONDS = 0.2

# Per-sender attempts to send the same already-planned AssignSession,
# retried only on a transient SendQueueFullError.
MAX_DISPATCH_ATTEMPTS = 2

# IpcServer.send() enqueues via put_nowait and never awaits, so a retry with
# no delay runs in the same event-loop tick as the failed attempt and can
# never observe a drained queue. This gives the write loop a chance to run.
DISPATCH_RETRY_DELAY_SECONDS = 0.05

SESSION_ID_RANDOM_BYTES = 8

# proto3 leaves an unset uint64 as 0, so 0 must mean UNLIMITED, never
# "throttled to zero bytes per second" (which would mean transmit nothing).
# The C++ sender must treat sender_bps_limit == 0 as unlimited.
UNSET_SENDER_BPS_LIMIT = 0

FILE_HASH_HEX_LENGTH = 64  # BLAKE3's 32-byte digest, hex-encoded
