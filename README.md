# nexus-file-monitor

The TX-side file monitor and transfer planner for Nexus, a one-way file
transfer system built for lossy networks. It watches a directory for new
files, plans FEC-encoded block transfers using Reed-Solomon coding, and
dispatches shard assignments to sender processes over Unix Domain Sockets. It
is the single source of truth for which blocks each sender transmits — every
other process derives its behavior from what this one decides.

## Architecture

In a live transfer there are eight processes: this file-monitor, N sender
child processes it spawns and supervises (3 by default, once a real sender
binary is available — see `senders.sender_count` below), a session-manager on
the receiving machine that aggregates per-block progress from N receiver
processes it in turn supervises, and those N receivers. A separate `router`
process is used independently as a network-impairment test harness (packet
loss, corruption, misrouting) and is not part of a normal transfer. Within
this repo, file-monitor follows hexagonal architecture: `domain/` holds pure
planning logic (shard math, block layout) with no I/O; `ports/` defines the
Protocol interfaces domain and services depend on; `adapters/` implements
those against real infrastructure (inotify, BLAKE3, Unix sockets); `services/`
orchestrates watching, dispatching, and sender-liveness tracking; `main.py` is
the composition root that wires everything together.

## Setup

```bash
git submodule update --init          # pulls in libs/nexus-proto
cp .env.example .env && source .env  # sets PYTHONPATH for the generated protobuf code
pip install -e '.[dev]'
python -m file_monitor.main          # reads ./config.toml by default
```

`NEXUS_CONFIG=/path/to/config.toml python -m file_monitor.main` points at a
different config file; every value under `[paths]` and `[senders]` can also be
overridden by an environment variable (table below).

## Testing

```bash
pytest                          # unit + integration tests
mypy --strict src/file_monitor tests
ruff check src tests && ruff format src tests

scripts/run_milestones.sh       # end-to-end: starts a real file-monitor and
                                 # three stub senders (see tests/integration/README.md),
                                 # exercises three scenarios, prints a PASS/FAIL table
```

## Configuration

TOML file (default `config.toml`), overridden by environment variables, then
validated. Relative paths (`watch_path`, `socket_path`, `binary_path`) resolve
against the *config file's own directory*, not the process's working
directory.

Every environment variable is namespaced `NEXUS_`, so it can't collide with
another process's variable of the same generic name once this runs in a
shared compose stack alongside session-manager, s3-sync, and MinIO.

| Section.key | Env var | Default | Notes |
|---|---|---|---|
| `paths.watch_path` | `NEXUS_WATCH_PATH` | *(required)* | Created on startup if missing |
| `paths.socket_path` | `NEXUS_SOCKET_PATH` | *(required)* | Unix Domain Socket, `SOCK_SEQPACKET` |
| `pacing.rate_ceiling_bps` | `NEXUS_RATE_CEILING_BPS` | 20,000,000 | |
| `pacing.rate_floor_bps` | `NEXUS_RATE_FLOOR_BPS` | 5,000,000 | |
| `fec.k` / `fec.n` / `fec.symbol_bytes` | `NEXUS_FEC_K` / `NEXUS_FEC_N` / `NEXUS_FEC_SYMBOL_BYTES` | *(required)* | Cross-service contract with the C++ sender/receiver — never change unilaterally |
| `senders.target_host` | `NEXUS_SENDERS_TARGET_HOST` | `127.0.0.1` | RX host senders transmit to |
| `senders.base_port` | `NEXUS_SENDERS_BASE_PORT` | 9000 | First sender's port; `base_port + shard_residue` per sender |
| `senders.binary_path` | `NEXUS_SENDERS_BINARY_PATH` | `./bin/nexus-sender` | Not shipped in this repo |
| `senders.sender_count` | `NEXUS_SENDERS_SENDER_COUNT` | 0 | `0` = supervise nothing (no crash-loop when the binary is absent) |
| — | `NEXUS_PROTO_CONTRACT_DIR` | `libs/nexus-proto/proto` | `.proto` source files hashed at startup for the handshake |
| — | `NEXUS_CONFIG` | `config.toml` | Which config file to load |

`fec.*` and the proto contract are cross-service contracts: a mismatch does
not fail loudly, it produces transfers that complete "successfully" and write
garbage. See `CLAUDE.md` for the full design constraints.

## Running in a container

`docker compose up` builds and runs file-monitor alone (`Dockerfile`,
`compose.yml`); see those files for details. Native execution
(`python -m file_monitor.main`) remains fully supported and is what the graded
machines run.
