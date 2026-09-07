# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**nexus-file-monitor** is the TX-side file monitor and transfer planner for the Nexus distributed file transfer system. It watches a directory for new files, plans FEC-encoded block transfers, and dispatches assignments to sender processes via Unix Domain Sockets.

This is part of a multi-service system:

- **file-monitor** (this repo): Detects files, plans FEC encoding, dispatches sender assignments
- **session-manager**: Aggregates receiver progress, verifies transfers, publishes output
- **router**: Test harness for network impairment (loss, corruption, misrouting)
- **s3-sync** (optional): Polls MinIO and downloads files to watched directory

The system uses a custom UDP-based FEC protocol with Reed-Solomon coding to handle lossy networks.

## Commands

### Running the application

```bash
# Set up environment (PYTHONPATH is critical for proto imports)
cp .env.example .env
source .env  # or use direnv

# Run the application
python -m file_monitor.main

# Or with custom config
NEXUS_CONFIG=custom.toml python -m file_monitor.main
```

`python -m file_monitor.main` is **Linux-only** — `main.py` imports
`inotify_simple` at module load and inotify is a Linux syscall (on Windows the
import dies at `from select import poll`, before any config is read). On a
Windows dev box, `mypy` / `ruff` / `pytest` run natively (the POSIX-only tests
skip); a real run and `scripts/run_milestones.sh` need Linux or a container.

### Development commands

```bash
# Install dependencies
pip install -e '.[dev]'

# Type checking (strict mode enabled)
mypy --strict src/file_monitor tests

# Linting
ruff check src tests

# Auto-format
ruff format src tests

# Run all tests
pytest

# Run specific test file
pytest tests/unit/test_planning.py

# Run with coverage
pytest --cov=file_monitor --cov-report=term-missing

# Run only unit tests
pytest tests/unit

# Run only integration tests
pytest tests/integration
```

### Proto generation

The protobuf definitions live in `libs/nexus-proto` (git submodule). Generated Python files are already committed in that repo.

If you need to regenerate:

```bash
cd libs/nexus-proto
./compile.sh  # Linux/Mac
# or
compile.bat   # Windows
```

## Design Principles & Standards

### Stack Requirements

- **Python 3.11+** (this project uses 3.11+ features like `tomllib`)
- **Type hints mandatory** on every function signature and class attribute
- **`mypy --strict`** must pass—no untyped `Any` unless explicitly justified
- **`typing.Protocol`** for structural interfaces—no ABCs unless nominal inheritance is genuinely required
- **`dataclasses`** with `frozen=True` for immutability (all domain models are frozen)
- **`typing.NewType`** for every ID type—never pass raw `str`/`int` as identifier across boundaries
- **pytest** with `hypothesis` for property-based testing

### Design Patterns & Abstraction

**Reach for a design pattern before writing ad-hoc logic:**

- **Strategy** via Protocol + injected callables/objects
- **Factory** for constructing instances behind a Protocol
- **Repository Protocol** for data access
- **Decorator** for layering behavior without modifying core logic
- **Observer** for event/pub-sub flows
- **Chain of Responsibility** for pipelines
- **Builder** for complex object assembly
- **Adapter** for wrapping incompatible interfaces (see `adapters/` directory)
- **Command** for encapsulating actions

**Core principles:**

- **Program to protocols, not implementations.** Every component that could vary is defined as a `typing.Protocol`; consumers depend on the protocol type. Concrete classes are wired via constructor injection.
- **Push abstraction as high as it usefully goes.** Domain logic must not import infrastructure (I/O, frameworks, DB clients, network calls) directly—those sit behind Protocols and get injected.
- **No god classes or god modules.** A class/module with more than one reason to change should be split. Single Responsibility is non-negotiable.
- **Favor composition over inheritance.** Use inheritance only for genuine is-a hierarchies; otherwise compose behavior via injected collaborators.
- **Open/Closed in practice:** New behavior should be addable by adding a new class implementing the Protocol, not by editing existing conditionals.

### SOLID Principles

- **S** (Single Responsibility): One reason to change per class/module. Split anything doing more.
- **O** (Open/Closed): Open for extension, closed for modification. New behavior = new class implementing the Protocol, not edited conditionals.
- **L** (Liskov Substitution): Any class implementing a Protocol must be substitutable for it without breaking callers. No raising `NotImplementedError` in an implementation.
- **I** (Interface Segregation): Many small, focused Protocols over one broad one. No client forced to depend on methods it doesn't use.
- **D** (Dependency Inversion): Depend on Protocols, not concretions. Wiring happens via constructor injection.

### Naming Conventions

- Follow **PEP 8**: `snake_case` for modules/functions/variables; `PascalCase` for classes/Protocols; `UPPER_SNAKE_CASE` for constants
- Protocols use plain names like `Clock`, `Hasher`, not `ClockProtocol` or `IClock`
- Names must be descriptive and unabbreviated—no `mgr`, `calc`, `svc`, `cfg` (write `app_config`), `fh`/`f` (write `file_handle`), `env` (write `environment`), `conn` (write `connection`)
- File name matches its primary type in `snake_case` (e.g., `blake3_hasher.py` defines `Blake3Hasher`)

### Coding Standards

- **Type hints on every function signature and class attribute**—no implicit `Any`. This includes every instance attribute assigned in `__init__`, even when its type is trivially inferable from an already-typed parameter (`self.path: Path = path`, not `self.path = path`)—mypy tolerates the omission, but the standard here is stricter than what mypy requires
- **Models are frozen** (immutable) dataclasses; entities with identity may be mutable but still fully typed
- **IDs are dedicated types** (`NewType` or frozen wrapper), never bare `str`/`int`
- **Dependency injection for everything**—no constructing collaborators inline inside business logic
- **Comments record decisions and hazards, not what the code says.** Code must be self-documenting through naming and structure—but a comment that defends a correct-looking-wrong line is not redundant with the code, it is protecting it from a future "fix".
  - **Remove:** comments that restate what the code says, narrate obvious steps, or duplicate a docstring or a test name.
  - **Keep:** cross-language or cross-service contracts; explanations of why a line that looks wrong is correct; recorded trade-offs; pending dependencies on another repo (with what to change when they land); and anything whose absence would make a future "simplification" look safe.
  - This distinction is load-bearing, not stylistic. An over-trim under the old blanket "no comments" rule once deleted the `proto_hash` algorithm spec from `file-monitor/src/file_monitor/ipc/handshake.py`—a cross-language contract the C++ side implements from that prose—and it had to be restored. Same failure mode removed four decision/hazard comments from `session-manager/src/session_manager/domain/models.py` (block/symbol size wire trap, gauge-vs-counter aggregation, pending `rx_pb2` enum, frozen-dataclass mutable-container reach); also restored.
- **No magic values—every literal becomes a named constant**, and constants live in a dedicated `constants.py`, never inline in the file that uses them:
  - One `constants.py` per package (`ipc/constants.py`, `services/constants.py`, `adapters/constants.py`, `domain/constants.py` if domain ever needs one); top-level modules (`config.py`, `main.py`) share `file_monitor/constants.py`
  - This covers **string literals used as keys or dispatch discriminators**, not just numbers—TOML keys, env var names, protobuf oneof field names (e.g., `SENDER_HELLO_FIELD_NAME`, `ENVELOPE_ONEOF_GROUP_NAME` in `ipc/constants.py`). If the same literal is compared, looked up, or must match an external contract in more than one place, it is a constant, imported from one place, not retyped at each site
  - Exception: purely descriptive/presentational strings—structlog event names, human-readable prose inside a raised exception's message—stay inline. They carry no control-flow weight and keeping them at the call site is what makes them greppable against actual log/error output
- **No duplicate logic.** If two methods have the same body (e.g., `register`/`refresh` on a registry), one calls the other—never copy the implementation. Prefer a data table (list/dict of tuples) plus a loop over N near-identical `if`/`elif` blocks doing the same shape of work (see `config.py`'s `ENV_OVERRIDES`)—adding a case becomes a table row, not a new branch
- **Keep functions/methods short and single-purpose**; extract instead of nesting
- **Always push for optimization.** Prefer efficient algorithms and data structures; consider time/space complexity. Avoid unnecessary copies, redundant iteration, premature materialization, and redundant system calls (e.g., check `is_dir()` before falling back to `exists()`, not both unconditionally). Optimization must never compromise design principles above.

## Architecture

### Hexagonal (Ports & Adapters) Structure

The codebase follows strict hexagonal architecture with three layers. This implements the Dependency Inversion principle: high-level domain logic depends on Protocol abstractions, and low-level adapters implement those protocols.

1. **Domain** (`domain/`): Pure business logic, no I/O, no framework dependencies
   - `ids.py`: NewType wrappers for type safety (SessionId, BlockId, SymbolId, SenderId)
   - `models.py`: Frozen dataclasses for core domain concepts (SourceFile, FecParams, BlockPlan, ShardAssignment)
   - `planning.py`: Pure functions for block calculation and shard assignment

2. **Ports** (`ports/`): Protocol (interface) definitions only
   - `protocols.py`: Clock, FileEvents, Hasher, IpcServer protocols
   - Dependencies are injected as protocols, never concrete types

3. **Adapters** (`adapters/`): Concrete implementations of ports
   - `constants.py`: adapter-level constants (e.g. `CHUNK_SIZE`)
   - `blake3_hasher.py`: BLAKE3 file hashing via asyncio.to_thread
   - `inotify_events.py`: Linux inotify integration (watches CLOSE_WRITE and MOVED_TO)
   - `system_clock.py`: System clock implementation

4. **Services** (`services/`): Orchestration built on ports + domain, no adapter coupling
   - `constants.py`: service-level constants (e.g. `MISSED_HEARTBEAT_LIMIT`)
   - `registry.py`: `SenderRegistry`—tracks which senders are connected and alive (`SenderHello` registers, `Heartbeat` refreshes, three missed heartbeats marks dead, disconnect removes). Exposes `active_senders() -> list[SenderId]`, sorted and stable—this is what shard assignment iterates over, which is why sharding can't be a compile-time constant

**Folder Structure Note:** This project uses `ports/` to contain Protocol definitions (following hexagonal architecture terminology). When implementing new features, keep protocols in `ports/protocols.py` and concrete implementations in `adapters/`. This is equivalent to a `protocols/` subfolder approach—the key is keeping interfaces separate from implementations.

### IPC Layer

The IPC subsystem uses **SOCK_SEQPACKET** Unix Domain Sockets (message boundaries preserved, no framing needed):

- `ipc/constants.py`: buffer sizes, queue limits, and the shared wire-contract string literals (`ENVELOPE_ONEOF_GROUP_NAME`, `SENDER_HELLO_FIELD_NAME`)—never redefine these inline at a call site
- `ipc/errors.py`: `HandshakeError`, `UnknownSenderError`, `ProtoHashMismatchError`—each owns its own message formatting (no bare `pass` bodies) and exposes the relevant data as attributes
- `ipc/codec.py`: Protobuf Envelope encoding/decoding
- `ipc/message_types.py`: Mapping from protobuf message types to oneof field names
- `ipc/handshake.py`: computes `proto_hash` to detect a sender/receiver running against a stale contract. The algorithm — a **cross-language contract** B and A reimplement in C++ from the docstring prose: the `*.proto` files in the contract dir (no recursion), **sorted by filename** (byte-wise ASCII), their **raw bytes** fed in that order into **one BLAKE3-256** hash with **no separator**, yielding the standard **32-byte** digest. **No canonicalization** — no comment stripping, no whitespace collapsing, no transformation of any kind. An earlier version canonicalized the text; it was replaced because reproducing that byte-for-byte in C++ is unreasonably fragile (one difference refuses every connection with a symptom pointing at a hash, not the cause). **Accepted trade-off:** a comment-only `.proto` edit changes the hash and forces every process to rebuild — a reproducible check that occasionally over-fires beats an irreproducible one that blocks all integration. **CRLF trap:** the hash is over raw bytes, so a stale Windows working tree with CRLF `.proto` files computes a *different* hash at the *same* commit and the handshake refuses even though `git submodule status` shows the right pin — hence `.gitattributes` pins `*.proto` to `eol=lf` in every repo. BLAKE3, matching `adapters/blake3_hasher.py` — never introduce a second hash algorithm for the same kind of check.
- `ipc/uds.py`: `UdsIpcServer`—UDS server implementation. Peers are anonymous until `SenderHello` passes both the message-type check and the proto-hash check from `handshake.py`; only then are they keyed by `SenderId`. Bounded per-peer send queues (a wedged sender must not stall the server); disconnect and task-failure cleanup happen in `finally` blocks so one bad peer can't take down the accept loop

The codec uses the `oneof` pattern from `ipc.proto`:

- `Envelope` wraps all messages with a `oneof msg` field
- Encoding: Takes a concrete message type, looks up its field name, builds Envelope
- Decoding: Uses `WhichOneof()` to determine message type

**Message Dispatch Pattern:** When implementing message handlers, use a **registry keyed by `oneof` field name**, not a chain of `isinstance` checks. This follows the **Open/Closed** principle—new message types are added by registering a new handler, not by editing a growing if/elif chain.

Example pattern:
```python
handlers: dict[str, Callable[[Message], None]] = {
    "sender_hello": handle_sender_hello,
    "heartbeat": handle_heartbeat,
    # Add new handlers here without modifying existing code
}

field_name, message = decode(raw_bytes)
handler = handlers[field_name]
handler(message)
```

### Configuration

Configuration follows a layered merge strategy:

1. Load from TOML file (default: `config.toml`)
2. Override with environment variables (see `.env.example`)
3. Validate all constraints before starting

All TOML section/key names, env var names, and numeric limits used by `config.py` live in `file_monitor/constants.py`, not inline in `config.py` itself. The env-var-override step is a data table (`ENV_OVERRIDES`: env var → section → key → caster) plus a loop, not one `if` block per field—adding a new overridable field means adding a table row.

**Critical validation rules:**

- `fec.k < fec.n` (otherwise FEC is impossible)
- `fec.n <= 255` (GF(2^8) field limit)
- `fec.symbol_bytes <= 1442` (MTU budget after headers)
- `rate_ceiling_bps >= rate_floor_bps`

**FEC parameters are a cross-service contract** with C++ sender/receiver processes. Mismatches don't fail loudly—they produce "successful" transfers that write garbage. Never change FEC config unilaterally.

### Proto Import Strategy

The generated Python protobuf files are **flat modules on sys.path**, not a package:

- `ipc_pb2.py` does `import common_pb2` (not `from nexus.common import common_pb2`)
- Always import as: `import ipc_pb2`, `import common_pb2`
- PYTHONPATH must include `libs/nexus-proto/generated/python`

This is configured in:

- `.env.example` (PYTHONPATH)
- `.vscode/settings.json` (python.analysis.extraPaths)
- `pyproject.toml` (hatch force-include for wheel builds)

### Type Safety with NewTypes

The domain uses NewType extensively to prevent ID confusion:

```python
BlockId = NewType("BlockId", int)
SymbolId = NewType("SymbolId", int)
SenderId = NewType("SenderId", int)
```

These are **not interchangeable**—mypy in strict mode will catch misuse. This prevents the most common bug class in FEC systems (confusing block indices with symbol indices).

## Testing Strategy

### Unit Tests (`tests/unit/`)

- **Test domain logic in isolation** with pure functions (no I/O, no network, no filesystem)
- **Inject test doubles** (fakes) via Protocol dependencies to test business logic without infrastructure
- Use **`hypothesis`** for property-based testing (see `test_shard_assignment_properties.py`)
- **Critical properties to verify:**
  - Shard assignments cover every block exactly once (no gaps, no overlaps)
  - Block plans are contiguous and non-overlapping
  - FEC validation catches impossible configurations before they cause silent data corruption

### Integration Tests (`tests/integration/`)

- Test IPC codec round-trips with real protobuf serialization
- Test UDS communication with actual sockets (not mocked)—`tests/integration/test_uds.py` runs `AF_UNIX`/`SOCK_SEQPACKET` for real and is skipped (not faked) on a host without `AF_UNIX`
- Test adapter implementations against real dependencies where practical

### Test Doubles (Fakes)

`tests/conftest.py` holds shared fixtures (e.g. putting the generated proto modules on `sys.path`). Fakes live in `tests/fakes/`:

- **FakeClock** (`tests/fakes/fake_clock.py`, manually advanced time): Test timeout logic, backoff, debouncing without waiting—used by `test_registry.py` to prove a sender drops out after exactly its configured heartbeat timeout
- **FakeFileEvents** (`fake_file_events.py`, inject events): Test file detection, including queue overflow scenarios
- **FakeIpcServer** (`fake_ipc_server.py`): Test message dispatch without real sockets
- **FakeHasher** (`fake_hasher.py`): Test file processing without actual I/O
- **FakeSpawner** / **FakeProcess** (`fake_spawner.py`): Test the supervisor's backoff and crash-loop detection without spawning anything

**A fake that cannot fail is worse than no fake**—it makes tests pass that would fail in production. Every fake must support:
- Success cases
- Failure injection (raise on Nth call, intermittent failures)
- Controllable timing/ordering

This follows the **Dependency Inversion** principle: tests depend on the same Protocol interfaces as production code, so fakes are drop-in replacements.

## Key Design Constraints

### Block Size vs Symbol Size

This was an early open question; the code settled it and `docs/GUIDE.md` §9
records the answer. **`Manifest.block_bytes` carries the symbol size.** A block
is `k` symbols wide — `block_size = k * symbol_bytes` (280 KB at `k=200`,
`symbol_bytes=1400`). Files are split into blocks; each block is FEC-encoded
into `n` symbols. `domain/models.py` carries the hazard comment. Getting it
backwards produces transfers that complete "successfully" and write garbage.

### Shard Assignment

A sender transmits the blocks where `block_id % shard_modulus == shard_residue`.
`shard_residue` is **positional** — the sender's index in the currently-live set,
assigned by `planning.derive_shard_assignments` — **not** the sender's own id.
`shard_modulus` is `len(active_senders)`. Both are explicit fields on
`ShardAssignment` and are copied into the `Manifest` (`sender_id` = the
residue), so the two sides cannot disagree. A sender that keys its shard off its
own Hello id transmits nothing the moment any lower-id sender dies — half the
file never leaves the machine, with no error either side. `docs/GUIDE.md` §6 and
`docs/SENDER_CONTRACT.md` have the worked example.

### Dependencies and Constraints

**Do NOT:**

- Use pybind11 or custom C++ bindings (Python's mmap/numpy + blake3 wheel cover everything)
- Use `tc netem` for network impairment (Docker kernel issues; use nexus-router instead)
- Put protobuf types in domain layer (keep wire format separate from business logic)
- Chain `isinstance` checks for message dispatch (use registry keyed by oneof field name)
- Use SOCK_STREAM (use SOCK_SEQPACKET for message boundaries)

**DO:**

- Inject dependencies as protocols
- Keep domain logic pure (testable without I/O)
- Validate config at load time and fail loudly
- Use asyncio.to_thread for CPU-bound work (hashing)
- Handle inotify Q_OVERFLOW with full directory rescan

## Where the detail lives

The service is complete. For architecture, every design decision and its
reasoning, the shared machinery, and the cross-language contracts, read
`docs/GUIDE.md` (verified against the code). `docs/SENDER_CONTRACT.md` is what
A's C++ sender implements against. `session-manager/SHARED_CODE.md` is the
ledger of what is copied between the two services and must be fixed in both.
