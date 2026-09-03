MISSED_HEARTBEAT_LIMIT = 3
HEARTBEAT_INTERVAL_SECONDS = 5.0
DEBOUNCE_SECONDS = 0.2

# One initial send attempt plus one retry after dropping any sender that
# failed and re-planning shards over the survivors.
MAX_DISPATCH_ATTEMPTS = 2

SESSION_ID_RANDOM_BYTES = 8

# proto3 leaves an unset uint64 as 0, so 0 must mean UNLIMITED, never
# "throttled to zero bytes per second" (which would mean transmit nothing).
# The C++ sender must treat sender_bps_limit == 0 as unlimited.
UNSET_SENDER_BPS_LIMIT = 0

FILE_HASH_HEX_LENGTH = 64  # BLAKE3's 32-byte digest, hex-encoded
