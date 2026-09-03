MISSED_HEARTBEAT_LIMIT = 3
HEARTBEAT_INTERVAL_SECONDS = 5.0
DEBOUNCE_SECONDS = 0.2

# Per-sender attempts to resend the same AssignSession on SendQueueFullError.
MAX_DISPATCH_ATTEMPTS = 2

# send() enqueues via put_nowait and never awaits, so an immediate retry
# can't observe a drained queue without this.
DISPATCH_RETRY_DELAY_SECONDS = 0.05

SESSION_ID_RANDOM_BYTES = 8

# proto3 leaves an unset uint64 as 0, so 0 must mean UNLIMITED, never
# "throttled to zero bytes per second" (which would mean transmit nothing).
# The C++ sender must treat sender_bps_limit == 0 as unlimited.
UNSET_SENDER_BPS_LIMIT = 0

FILE_HASH_HEX_LENGTH = 64  # BLAKE3's 32-byte digest, hex-encoded
