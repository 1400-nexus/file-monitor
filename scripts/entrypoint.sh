#!/bin/sh
# Validates the container's minimum configuration and prepares its runtime
# directories, then hands off to the application. No orchestration, no
# retries, no supervision -- that belongs to file_monitor itself.
set -eu

missing=""
[ -z "${NEXUS_CONFIG:-}" ] && missing="$missing NEXUS_CONFIG"
[ -z "${WATCH_PATH:-}" ] && missing="$missing WATCH_PATH"
[ -z "${SOCKET_PATH:-}" ] && missing="$missing SOCKET_PATH"

if [ -n "$missing" ]; then
    echo "entrypoint: missing required environment variable(s):$missing" >&2
    exit 78
fi

mkdir -p "$WATCH_PATH" "$(dirname "$SOCKET_PATH")"

exec "$@"
