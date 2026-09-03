#!/usr/bin/env bash
# Runs the three stub-sender milestones (see tests/integration/README.md)
# against a real file-monitor process and exits non-zero if any assertion
# fails. Uses a temporary directory for all runtime state, so it never
# touches the repo working tree.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

export PYTHONPATH="$REPO_ROOT/libs/nexus-proto/generated/python"

if ! python3 -c "import file_monitor" >/dev/null 2>&1; then
    echo "file_monitor is not importable -- run: pip install -e '.[dev]'" >&2
    exit 1
fi
if ! python3 -c "import ipc_pb2" >/dev/null 2>&1; then
    echo "ipc_pb2 is not importable -- did you run: git submodule update --init?" >&2
    exit 1
fi

REGISTRY_EXPIRY_SECONDS="$(python3 -c '
from file_monitor.services.constants import HEARTBEAT_INTERVAL_SECONDS, MISSED_HEARTBEAT_LIMIT
print(HEARTBEAT_INTERVAL_SECONDS * MISSED_HEARTBEAT_LIMIT)
')"
# Margin on top of the registry's own expiry window, so a slow scheduler
# doesn't make the wait race the expiry itself.
WAIT_FOR_EXPIRY_SECONDS="$(python3 -c "print(int($REGISTRY_EXPIRY_SECONDS) + 3)")"
# Long enough to cover connecting, the expiry wait above, and dispatch.
MILESTONE_2_STUB_TIMEOUT="$(python3 -c "print(int($WAIT_FOR_EXPIRY_SECONDS) + 15)")"

BASE_PORT=9500

WORK_DIR="$(mktemp -d)"
WATCH_DIR="$WORK_DIR/watch"
RUN_DIR="$WORK_DIR/run"
BIN_DIR="$WORK_DIR/bin"
LOG_DIR="$WORK_DIR/logs"
CONFIG_PATH="$WORK_DIR/config.toml"
SOCKET_PATH="$RUN_DIR/file-monitor.sock"
FAKE_SENDER_BINARY="$BIN_DIR/fake-sender.sh"

mkdir -p "$WATCH_DIR" "$RUN_DIR" "$BIN_DIR" "$LOG_DIR"

# The supervisor's own children (unrelated to the stub senders below, which
# stand in for real senders talking over the socket) just need to exist so
# ProcessSupervisor has something real to spawn instead of logging
# child_spawn_failed for every retry.
cat > "$FAKE_SENDER_BINARY" << 'EOF'
#!/bin/sh
exec sleep 3600
EOF
chmod +x "$FAKE_SENDER_BINARY"

cat > "$CONFIG_PATH" << EOF
[paths]
watch_path = "$WATCH_DIR"
socket_path = "$SOCKET_PATH"

[pacing]
rate_ceiling_bps = 20000000
rate_floor_bps = 5000000

[fec]
k = 1
n = 2
symbol_bytes = 1

[senders]
target_host = "127.0.0.1"
base_port = $BASE_PORT
binary_path = "$FAKE_SENDER_BINARY"
sender_count = 1
EOF

MONITOR_PID=""
STUB_PIDS=()
MILESTONE_NAMES=()
MILESTONE_RESULTS=()

cleanup() {
    local pid
    for pid in "${STUB_PIDS[@]:-}"; do
        [ -n "$pid" ] && kill "$pid" >/dev/null 2>&1 || true
    done
    if [ -n "$MONITOR_PID" ]; then
        kill "$MONITOR_PID" >/dev/null 2>&1 || true
    fi
    for pid in "${STUB_PIDS[@]:-}" "$MONITOR_PID"; do
        [ -n "$pid" ] && wait "$pid" >/dev/null 2>&1 || true
    done
    rm -rf "$WORK_DIR"
}
trap cleanup EXIT
# A trap handler for INT/TERM that doesn't itself exit only runs cleanup and
# then RESUMES the script where it was interrupted -- on a now-deleted
# WORK_DIR, since cleanup() already removed it. Exiting explicitly instead
# triggers the EXIT trap above (running cleanup exactly once) and actually
# stops the script, with the conventional 128+signal exit code.
trap 'exit 130' INT
trap 'exit 143' TERM

start_monitor() {
    NEXUS_CONFIG="$CONFIG_PATH" python3 -m file_monitor.main > "$LOG_DIR/monitor.log" 2>&1 &
    MONITOR_PID=$!
    local i
    for i in $(seq 1 100); do
        if [ -S "$SOCKET_PATH" ]; then
            return 0
        fi
        sleep 0.1
    done
    echo "file-monitor did not create the socket in time"
    return 1
}

stop_monitor() {
    # Waits on each PID individually rather than a bare `wait` -- a bare
    # `wait` blocks on every background job of this shell, including
    # MONITOR_PID before it has been killed below, which deadlocks (waiting
    # for the monitor to exit before ever reaching the line that kills it).
    local pid
    for pid in "${STUB_PIDS[@]:-}"; do
        if [ -n "$pid" ]; then
            kill "$pid" >/dev/null 2>&1 || true
            wait "$pid" >/dev/null 2>&1 || true
        fi
    done
    STUB_PIDS=()
    if [ -n "$MONITOR_PID" ]; then
        kill "$MONITOR_PID" >/dev/null 2>&1 || true
        wait "$MONITOR_PID" >/dev/null 2>&1 || true
        MONITOR_PID=""
    fi
    rm -rf "$WATCH_DIR"
    mkdir -p "$WATCH_DIR"
}

LAST_STUB_PID=""

start_stub() {
    # $1=timeout seconds, $2=sender-id, $3=log file, rest = extra stub_sender.py args
    # Sets LAST_STUB_PID rather than echoing it: called via command
    # substitution, this function would run in a subshell, and the
    # backgrounded job it starts would be a child of THAT subshell -- once
    # the subshell exits, the job is orphaned from the main script and no
    # longer `wait`-able from here (bash reports "not a child of this
    # shell" and returns 127). Called plainly, it runs in this same shell.
    local timeout_seconds="$1" sender_id="$2" log_file="$3"
    shift 3
    timeout "$timeout_seconds" python3 tests/integration/stub_sender.py \
        --sender-id "$sender_id" --socket "$SOCKET_PATH" "$@" > "$log_file" 2>&1 &
    LAST_STUB_PID=$!
}

interruptible_sleep() {
    # A plain foreground `sleep N` blocks bash from noticing a trapped
    # signal until N elapses -- bash only checks for one between commands,
    # and (unlike `docker kill`, which signals only PID 1) nothing signals
    # the sleep child itself to end it early. Backgrounding it and waiting
    # on the wait builtin instead is interruptible: wait returns as soon as
    # a trapped signal arrives -- though the sleep itself is then still
    # running, so it's killed explicitly rather than left as a (short-lived,
    # but still needless) orphan.
    local sleep_pid
    sleep "$1" &
    sleep_pid=$!
    wait "$sleep_pid" 2>/dev/null
    kill "$sleep_pid" >/dev/null 2>&1 || true
}

record() {
    MILESTONE_NAMES+=("$1")
    MILESTONE_RESULTS+=("$2")
}

# ------------------------------------------------------------------------
# Milestone 1: three senders, disjoint and complete
# ------------------------------------------------------------------------
milestone_1() {
    set +e
    stop_monitor
    if ! start_monitor; then
        set -e
        return 1
    fi

    local log0="$LOG_DIR/m1_stub0.log" log1="$LOG_DIR/m1_stub1.log" log2="$LOG_DIR/m1_stub2.log"
    local pid0 pid1 pid2
    start_stub 10 0 "$log0" --json --exit-after-assignments 1; pid0=$LAST_STUB_PID
    start_stub 10 1 "$log1" --json --exit-after-assignments 1; pid1=$LAST_STUB_PID
    start_stub 10 2 "$log2" --json --exit-after-assignments 1; pid2=$LAST_STUB_PID
    STUB_PIDS=("$pid0" "$pid1" "$pid2")

    interruptible_sleep 1
    head -c 4 /dev/urandom > "$WATCH_DIR/milestone1.bin"

    local code0 code1 code2
    wait "$pid0"; code0=$?
    wait "$pid1"; code1=$?
    wait "$pid2"; code2=$?
    STUB_PIDS=()

    if [ "$code0" -ne 0 ] || [ "$code1" -ne 0 ] || [ "$code2" -ne 0 ]; then
        echo "FAIL: stub exit codes were $code0 $code1 $code2 (expected 0 0 0)"
        set -e
        return 1
    fi

    python3 - "$log0" "$log1" "$log2" "$BASE_PORT" << 'PYEOF'
import json
import sys


def extract_assigns(path):
    assigns = []
    with open(path) as f:
        for line in f:
            if line.startswith("ASSIGN "):
                assigns.append(json.loads(line[len("ASSIGN "):]))
    return assigns


paths = sys.argv[1:4]
base_port = int(sys.argv[4])

assigns = [extract_assigns(p) for p in paths]
for p, a in zip(paths, assigns):
    if len(a) != 1:
        print(f"FAIL: expected exactly 1 ASSIGN line in {p}, got {len(a)}")
        sys.exit(1)
records = [a[0] for a in assigns]

session_ids = {r["session_id"] for r in records}
if len(session_ids) != 1:
    print(f"FAIL: expected one shared session_id, got {session_ids}")
    sys.exit(1)

residues = sorted(r["shard_residue"] for r in records)
if residues != [0, 1, 2]:
    print(f"FAIL: expected shard_residue values [0,1,2], got {residues}")
    sys.exit(1)

senders = [r["total_senders"] for r in records]
if any(s != 3 for s in senders):
    print(f"FAIL: expected total_senders == 3 for all, got {senders}")
    sys.exit(1)

by_residue = {r["shard_residue"]: r for r in records}
block_sets = {residue: set(r["blocks"]) for residue, r in by_residue.items()}
residue_list = sorted(block_sets)
for i in range(len(residue_list)):
    for j in range(i + 1, len(residue_list)):
        a, b = residue_list[i], residue_list[j]
        overlap = block_sets[a] & block_sets[b]
        if overlap:
            print(f"FAIL: residue {a} and residue {b} share blocks {overlap}")
            sys.exit(1)

total_blocks = records[0]["total_blocks"]
union = set()
for s in block_sets.values():
    union |= s
if union != set(range(total_blocks)):
    print(f"FAIL: union of blocks {sorted(union)} != range({total_blocks})")
    sys.exit(1)

ports = set()
for residue, r in by_residue.items():
    expected_port = base_port + residue
    if r["target_port"] != expected_port:
        print(f"FAIL: residue {residue} target_port {r['target_port']} != {expected_port}")
        sys.exit(1)
    ports.add(r["target_port"])
if len(ports) != 3:
    print(f"FAIL: target_port values not distinct: {ports}")
    sys.exit(1)

for r in records:
    fp = r["filepath"]
    if fp.startswith("/") or ".." in fp.split("/"):
        print(f"FAIL: filepath not relative/safe: {fp}")
        sys.exit(1)

print("milestone 1: all assertions passed")
PYEOF
    local ok=$?

    set -e
    return "$ok"
}

# ------------------------------------------------------------------------
# Milestone 2: a dead sender degrades cleanly
# ------------------------------------------------------------------------
milestone_2() {
    set +e
    stop_monitor
    if ! start_monitor; then
        set -e
        return 1
    fi

    local log0="$LOG_DIR/m2_stub0.log" log1="$LOG_DIR/m2_stub1.log" log2="$LOG_DIR/m2_stub2.log"
    local pid0 pid1 pid2
    start_stub "$MILESTONE_2_STUB_TIMEOUT" 0 "$log0" --json --exit-after-assignments 1
    pid0=$LAST_STUB_PID
    start_stub "$MILESTONE_2_STUB_TIMEOUT" 1 "$log1"
    pid1=$LAST_STUB_PID
    start_stub "$MILESTONE_2_STUB_TIMEOUT" 2 "$log2" --json --exit-after-assignments 1
    pid2=$LAST_STUB_PID
    STUB_PIDS=("$pid0" "$pid1" "$pid2")

    interruptible_sleep 1

    kill "$pid1" >/dev/null 2>&1
    wait "$pid1" >/dev/null 2>&1
    STUB_PIDS=("$pid0" "$pid2")

    echo "killed sender 1; waiting ${WAIT_FOR_EXPIRY_SECONDS}s for the registry to expire it" \
        "(heartbeat_interval * missed_heartbeat_limit = ${REGISTRY_EXPIRY_SECONDS}s)..."
    interruptible_sleep "$WAIT_FOR_EXPIRY_SECONDS"

    head -c 4 /dev/urandom > "$WATCH_DIR/milestone2.bin"

    local code0 code2
    wait "$pid0"; code0=$?
    wait "$pid2"; code2=$?
    STUB_PIDS=()

    if [ "$code0" -ne 0 ] || [ "$code2" -ne 0 ]; then
        echo "FAIL: survivor exit codes were $code0 $code2 (expected 0 0)"
        set -e
        return 1
    fi

    python3 - "$log0" "$log2" "$LOG_DIR/monitor.log" << 'PYEOF'
import json
import sys


def extract_assigns(path):
    assigns = []
    with open(path) as f:
        for line in f:
            if line.startswith("ASSIGN "):
                assigns.append(json.loads(line[len("ASSIGN "):]))
    return assigns


log0, log2, monitor_log = sys.argv[1], sys.argv[2], sys.argv[3]

assigns0 = extract_assigns(log0)
assigns2 = extract_assigns(log2)
if len(assigns0) != 1 or len(assigns2) != 1:
    print(f"FAIL: expected exactly 1 ASSIGN line each, got {len(assigns0)} and {len(assigns2)}")
    sys.exit(1)
r0, r2 = assigns0[0], assigns2[0]

if r0["session_id"] != r2["session_id"]:
    print(f"FAIL: survivors got different session_ids: {r0['session_id']} vs {r2['session_id']}")
    sys.exit(1)

if r0["total_senders"] != 2 or r2["total_senders"] != 2:
    print(f"FAIL: expected total_senders == 2, got {r0['total_senders']} and {r2['total_senders']}")
    sys.exit(1)

residues = sorted([r0["shard_residue"], r2["shard_residue"]])
if residues != [0, 1]:
    print(f"FAIL: expected shard_residue values [0,1], got {residues}")
    sys.exit(1)

blocks0, blocks2 = set(r0["blocks"]), set(r2["blocks"])
if blocks0 & blocks2:
    print(f"FAIL: survivor block sets overlap: {blocks0 & blocks2}")
    sys.exit(1)

total_blocks = r0["total_blocks"]
if (blocks0 | blocks2) != set(range(total_blocks)):
    print(f"FAIL: union of survivor blocks {sorted(blocks0 | blocks2)} != range({total_blocks})")
    sys.exit(1)

# The registry was given longer than heartbeat_interval * missed_heartbeat_limit
# to expire sender 1 BEFORE this file was even copied in, so
# derive_shard_assignments only ever saw the 2 live senders when planning
# this dispatch -- nothing was attempted against sender 1 and nothing failed,
# so no dispatch_partially_failed line should exist for this run at all.
# (Copying the file BEFORE expiry instead -- so the dispatcher still counts
# 3 senders, attempts sender 1, and gets UnknownSenderError -- IS the case
# that produces dispatch_partially_failed, but then total_senders stays 3
# for the survivors, not 2. Only one of these two outcomes is possible for
# a given timing; this run deliberately chose the post-expiry one, per the
# task's instruction to wait past registry expiry.)
with open(monitor_log) as f:
    monitor_text = f.read()
if "dispatch_partially_failed" in monitor_text:
    print("FAIL: unexpected dispatch_partially_failed -- sender 1 should have "
          "already been expired from the registry before this dispatch")
    sys.exit(1)

print("milestone 2: all assertions passed")
PYEOF
    local ok=$?

    set -e
    return "$ok"
}

# ------------------------------------------------------------------------
# Milestone 3: a wrong contract hash is refused
# ------------------------------------------------------------------------
milestone_3() {
    set +e
    stop_monitor
    if ! start_monitor; then
        set -e
        return 1
    fi

    local log0="$LOG_DIR/m3_stub0.log" log1="$LOG_DIR/m3_stub1.log" log2="$LOG_DIR/m3_stub2.log"
    local pid0 pid1 pid2
    start_stub 60 0 "$log0"; pid0=$LAST_STUB_PID
    start_stub 60 1 "$log1"; pid1=$LAST_STUB_PID
    start_stub 60 2 "$log2"; pid2=$LAST_STUB_PID
    STUB_PIDS=("$pid0" "$pid1" "$pid2")

    interruptible_sleep 1

    local bad_proto_dir="$WORK_DIR/bad-proto"
    mkdir -p "$bad_proto_dir"
    cp "$REPO_ROOT"/libs/nexus-proto/proto/*.proto "$bad_proto_dir/"
    # The hash covers raw file bytes, so a comment-only edit changes it --
    # that is the documented trade-off in ipc/handshake.py.
    printf '\n// tampered for milestone 3\n' >> "$bad_proto_dir/ipc.proto"

    local bad_log="$LOG_DIR/m3_bad_stub.log"
    timeout 10 python3 tests/integration/stub_sender.py \
        --sender-id 9 --socket "$SOCKET_PATH" --proto-dir "$bad_proto_dir" --expect-refused \
        > "$bad_log" 2>&1
    local bad_exit=$?

    interruptible_sleep 0.3

    local ok=0
    if [ "$bad_exit" -ne 0 ]; then
        echo "FAIL: bad-hash stub exited $bad_exit, expected 0 (refused)"
        cat "$bad_log"
        ok=1
    fi

    python3 - "$LOG_DIR/monitor.log" << 'PYEOF'
import sys

monitor_log = sys.argv[1]
with open(monitor_log) as f:
    lines = f.readlines()

if not any("peer_proto_hash_mismatch" in line for line in lines):
    print("FAIL: monitor log is missing peer_proto_hash_mismatch")
    sys.exit(1)

for sender_id in (0, 1, 2):
    marker = f"sender_id={sender_id}"
    connected = any("peer_connected" in line and marker in line for line in lines)
    disconnected = any("peer_disconnected" in line and marker in line for line in lines)
    if not connected:
        print(f"FAIL: sender {sender_id} never appears as peer_connected")
        sys.exit(1)
    if disconnected:
        print(f"FAIL: sender {sender_id} was disconnected, should have stayed healthy")
        sys.exit(1)

print("milestone 3: log assertions passed")
PYEOF
    if [ "$?" -ne 0 ]; then
        ok=1
    fi

    for pid in "$pid0" "$pid1" "$pid2"; do
        if ! kill -0 "$pid" >/dev/null 2>&1; then
            echo "FAIL: original stub pid $pid is no longer running"
            ok=1
        fi
    done
    if ! kill -0 "$MONITOR_PID" >/dev/null 2>&1; then
        echo "FAIL: file-monitor process is no longer running"
        ok=1
    fi

    set -e
    return "$ok"
}

echo "=== Milestone 1: three senders, disjoint and complete ==="
if milestone_1; then
    record "milestone-1" "PASS"
else
    record "milestone-1" "FAIL"
fi
echo

echo "=== Milestone 2: a dead sender degrades cleanly ==="
if milestone_2; then
    record "milestone-2" "PASS"
else
    record "milestone-2" "FAIL"
fi
echo

echo "=== Milestone 3: a wrong contract hash is refused ==="
if milestone_3; then
    record "milestone-3" "PASS"
else
    record "milestone-3" "FAIL"
fi
echo

echo "==================== RESULTS ===================="
overall=0
for i in "${!MILESTONE_NAMES[@]}"; do
    printf "%-14s %s\n" "${MILESTONE_NAMES[$i]}" "${MILESTONE_RESULTS[$i]}"
    if [ "${MILESTONE_RESULTS[$i]}" != "PASS" ]; then
        overall=1
    fi
done
echo "==================================================="

exit "$overall"
