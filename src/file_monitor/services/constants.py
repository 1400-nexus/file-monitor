MISSED_HEARTBEAT_LIMIT = 3
HEARTBEAT_INTERVAL_SECONDS = 5.0
DEBOUNCE_SECONDS = 0.2

# Per-sender attempts to resend the same AssignSession on SendQueueFullError.
MAX_DISPATCH_ATTEMPTS = 2

# send() enqueues via put_nowait and never awaits, so an immediate retry
# can't observe a drained queue without this.
DISPATCH_RETRY_DELAY_SECONDS = 0.05

SESSION_ID_RANDOM_BYTES = 8

# proto3's unset uint64 is 0, so 0 means UNLIMITED here, never "throttled to
# zero bytes per second".
UNSET_SENDER_BPS_LIMIT = 0

FILE_HASH_HEX_LENGTH = 64  # BLAKE3's 32-byte digest, hex-encoded
