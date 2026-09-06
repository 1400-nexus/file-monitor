# Sender ↔ file-monitor contract

Everything a C++ sender needs to talk to `file-monitor`. You should be able to
implement against this document without reading the Python. Where it points at a
source file, that file is the authority and this is a summary.

Contract pin: **`nexus-proto` at `7f406db`**. Build your generated C++ from that
exact commit. `proto_hash` covers the raw bytes of every `.proto` file, so it
moves with any edit (a comment included) and a wrong one is a **refused
connection** — see §2. Your repo is currently pinned five commits behind this;
bump it first.

Unlike the RX side, the **file payload is yours to move**: `file-monitor` tells
you which file, which blocks, and where to send them; you mmap the file,
FEC-encode your shard, and transmit UDP to the receivers. `file-monitor` moves
assignments and liveness, not file data.

---

## 1. Transport

- **`AF_UNIX`, `SOCK_SEQPACKET`.** `file-monitor` is the **server**; you connect
  to `[paths].socket_path` (default `/run/nexus/file-monitor.sock`).
- **Message boundaries are preserved by the kernel.** One `send()` = one
  `recv()` = one message. There is **no length prefix** and you must not add
  one. Do not use `SOCK_STREAM`.
- Every message on the wire — both directions — is a serialized
  **`nexus.ipc.Envelope`** (`ipc.proto`), a `oneof` over the message types
  below. Decode by `WhichOneof`.
- One connection per sender, kept open for the process lifetime.

---

## 2. Handshake

The **first** message you send must be `SenderHello`. Anything else closes the
connection.

```
message SenderHello {
  uint32 sender_id   = 1;  // your identity: 0, 1, 2, ... distinct per sender
  uint32 pid         = 2;  // informational
  bytes  proto_hash  = 3;  // 32 bytes, computed — see below
}
```

### proto_hash

The algorithm is specified in full, language-independent, in the module
docstring of **`src/file_monitor/ipc/handshake.py`**. In brief:

1. List every `*.proto` directly in the contract directory (no recursion).
2. Sort those filenames lexicographically (byte-wise ASCII).
3. Read each file's **raw bytes** — no comment stripping, no whitespace
   normalization.
4. Feed the raw bytes, in that sorted order, into **one BLAKE3-256** hash, with
   **no separator** between files.
5. The digest is the standard **32-byte** BLAKE3 output.

`file-monitor` computes the same hash at startup over `NEXUS_PROTO_CONTRACT_DIR`
(`libs/nexus-proto/proto`). If yours does not match **byte for byte**, it raises
`ProtoHashMismatchError` and closes your connection (`peer_proto_hash_mismatch`
in its log). This is the first thing that fails if your pin is wrong, and the
error names a hash, not the cause.

At `nexus-proto@7f406db` the digest is:

```
38cac339d495241ae757fbeec84a6ecdc5377f838798ff9df1e19650bcff20df
```

(Recompute it — it changes with any `.proto` edit. If your checkout is on a
Windows box, confirm the submodule's `.proto` files came out LF, not CRLF; the
raw-bytes hash is line-ending sensitive and `nexus-proto/.gitattributes` pins
them to LF.)

A comment-only `.proto` edit changes this hash and forces a rebuild. Deliberate
— a reproducible check that occasionally over-fires beats one that quietly
diverges between C++ and Python.

---

## 3. Message flow

```
you → file-monitor                file-monitor → you
──────────────────                ──────────────────
SenderHello     ───────────────►
                              ◄── AssignSession   (0 or 1 per session — see §5)
SenderProgress  ───────────────►   (optional, periodic — logged, not acted on)
LocalCongestion ───────────────►   (optional — logged, not acted on)
SessionComplete ───────────────►   (once, when your shard is fully transmitted)
Heartbeat       ───────────────►   (every ~1 s, throughout, from just after Hello)
```

`UpdateRate` and `Abort` exist in `ipc.proto` (server→sender) but `file-monitor`
**does not send them today**. Do not block waiting for either.

### Ordering rules

| If you… | then… |
|---|---|
| send anything before `SenderHello` | connection closed immediately. |
| stop sending `Heartbeat` for 15 s (`HEARTBEAT_INTERVAL_SECONDS` 5 × `MISSED_HEARTBEAT_LIMIT` 3) | the registry drops you. You stop being assigned work, and the residues of the senders that remain shift (§5, property 1). |
| never send `SenderProgress` / `LocalCongestion` | fine — they are observability only right now. |
| never send `SessionComplete` | `file-monitor` keeps the session in its dispatched-set forever; harmless today, but send it. |
| receive an `AssignSession` for a session you already have one for | that will not happen — see §5, property 4. |

---

## 4. Message reference

All are `nexus.ipc.*`. S→M = sender to file-monitor.

### `AssignSession` (M→S)

```
message AssignSession {
  nexus.common.Manifest manifest = 1;
  uint32 total_senders  = 2;   // shard modulus for THIS assignment
  string target_host    = 3;   // RX host to transmit to
  uint32 target_port     = 4;  // your port: base_port + your shard residue
  string source_path    = 5;   // ABSOLUTE path to the file — mmap this
}
```

`Manifest` (`nexus.common`, `common.proto`):

| field | meaning |
|---|---|
| `session_id` | 16 hex chars; rides every `DataPacket`. |
| `filepath` | **relative** to file-monitor's watch root, POSIX separators. Exists so the RX side can name its output. **Not for you** — see §5, property 3. |
| `file_size` | bytes. |
| `file_hash` | BLAKE3-256 of the whole file — what the RX side verifies against. |
| `k`, `n` | FEC parameters. A block is `k` symbols; encode to `n`. |
| `block_bytes` | **symbol** size, not block size — see §5, property 2. |
| `total_blocks` | `ceil(file_size / (k * block_bytes))`. |
| `sender_id` | **your shard residue** — see §5, property 1. Not your `SenderHello.sender_id`. |
| `sender_bps_limit` | rate cap; `0` = unlimited — see §6. |

### `SenderProgress` (S→M), `LocalCongestion` (S→M)

```
message SenderProgress   { string session_id = 1; uint64 stripes_done = 2;
                           uint64 packets_sent = 3; uint64 bytes_sent = 4; }
message LocalCongestion  { string session_id = 1; uint64 enobufs_count = 2;
                           uint64 qdisc_drops = 3; uint64 current_rate_bps = 4; }
```

`file-monitor` logs these and does nothing else with them yet. Send
`SenderProgress` on a timer; send `LocalCongestion` when your socket backs up
(`ENOBUFS`, qdisc drops) — it is the signal a future rate controller will use.

### `SessionComplete` (S→M)

```
message SessionComplete { string session_id = 1; uint64 packets_sent = 2; }
```

Send once, when you have transmitted every block in your shard. `file-monitor`
drops the session from its tracking.

### `Heartbeat` (S→M)

```
message Heartbeat { uint32 process_id = 1; uint64 timestamp_unix_ms = 2; }
```

Every ~1 s. See §5, property 1 for what being dropped costs.

### Note on `sender_id`

`file-monitor` identifies you by `SenderHello.sender_id` and the connection it
arrived on. The `sender_id` **inside `Manifest`** is a different thing — a shard
residue (§5). Two senders must not share a `SenderHello.sender_id`.

---

## 5. The properties you must respect

### Property 1 — `Manifest.sender_id` is a SHARD RESIDUE, not your identity

**This is the item most likely to be got wrong, and it silently loses half a
file when it is.**

You transmit exactly the blocks where

```
block_id % AssignSession.total_senders == Manifest.sender_id
```

`file-monitor` assigns `sender_id` **positionally over the senders that are
currently alive**, not from your `SenderHello.sender_id`. It enumerates the live
senders in id order and hands out residues `0, 1, 2, …`. So:

- 3 senders alive (ids 0, 1, 2) → residues 0, 1, 2, modulus 3.
- Sender 1 dies. Next session: senders 0 and 2 alive → residues **0 and 1**,
  modulus **2**. Sender 2 is now residue **1**, not 2.

If you derive your shard from your own `SenderHello.sender_id` instead of reading
`Manifest.sender_id`, then the moment any lower-id sender dies, your residue in
the Python is `1` but your code still uses `2` — and `block_id % 2 == 2` is
never true. **You transmit nothing. Half the file never leaves the machine, with
no error on either side.** The RX side stalls waiting for blocks that were never
sent.

Read `Manifest.sender_id` and `AssignSession.total_senders` fresh from every
`AssignSession`. Never cache a residue across sessions.

### Property 2 — `Manifest.block_bytes` is the SYMBOL size

`block_bytes` is the size of one FEC **symbol**, not one block. A block is
**`k * block_bytes`** wide. With `k = 200` and `block_bytes = 1400`, a block is
280 KB. Block `i` starts at byte `i * k * block_bytes` in the source file; the
last block is shorter when `file_size` is not a multiple.

Get this backwards and every block boundary is off by a factor of `k` — the RX
side reassembles a file that fails its hash, with no other symptom.

### Property 3 — `AssignSession.source_path` is absolute; `Manifest.filepath` is not

mmap **`source_path`** exactly as given. It is the absolute path to the file on
file-monitor's machine.

**Do not** build a path from `Manifest.filepath` — that is relative to a watch
root you do not know, and joining it onto your own guess is how the RX side got
a path bug that took days to find. `Manifest.filepath` is on the wire only so
the receiver can name its output file.

### Property 4 — exactly one `AssignSession` per sender per session

`file-monitor` sends each live sender **at most one** `AssignSession` for a given
`session_id`. If the send fails (your queue is full past the retry limit, or you
disconnected), that sender's shard is **logged as lost and dropped** —
`file-monitor` does not reassign it to a survivor and does not retry later. So
you will never receive a second, conflicting assignment for a `session_id` you
are already working.

Consequence: if you miss an assignment, that shard of that file is simply not
transmitted. Stay connected and keep your receive queue drained.

---

## 6. Rate control

`Manifest.sender_bps_limit` is a per-sender byte-rate cap. **`0` means
UNLIMITED.** In proto3 an unset `uint64` is `0`, so there is no way to tell "no
limit" from "limited to zero" — and the contract resolves it as unlimited.
`file-monitor` currently always sends `0`; the `[pacing]` config
(`rate_ceiling_bps` / `rate_floor_bps`) is not yet wired to per-sender limits.

`UpdateRate { session_id, rate_bps }` is the intended mechanism for changing a
limit mid-session. When it is wired, apply the new rate **at the next stripe
boundary**, not mid-stripe — a rate change inside a stripe makes the receiver's
loss estimate jump. `file-monitor` does not send `UpdateRate` yet.

`LocalCongestion` is your side of this: report `ENOBUFS` counts and qdisc drops
so a future controller can back you off before the link does.

---

## 7. Worked example

One session: **3 senders (`SenderHello.sender_id` 0, 1, 2), `total_blocks = 12`,
`base_port = 9000`.**

| you (Hello id) | `Manifest.sender_id` (residue) | `total_senders` | `target_port` | blocks you transmit |
|---|---|---|---|---|
| 0 | 0 | 3 | 9000 | 0, 3, 6, 9 |
| 1 | 1 | 3 | 9001 | 1, 4, 7, 10 |
| 2 | 2 | 3 | 9002 | 2, 5, 8, 11 |

Union = every block 0–11, no overlap.

Now **sender 1 dies** (stops heartbeating; the registry drops it after 15 s).
The **next** session file-monitor dispatches sees only senders 0 and 2 alive:

| you (Hello id) | `Manifest.sender_id` (residue) | `total_senders` | `target_port` | blocks you transmit |
|---|---|---|---|---|
| 0 | 0 | 2 | 9000 | 0, 2, 4, 6, 8, 10 |
| 2 | **1** | **2** | **9001** | 1, 3, 5, 7, 9, 11 |

Sender 2's residue went from **2 → 1** and its port from **9002 → 9001**, purely
because the live set shrank. A sender that keyed its shard off its own Hello id
(2) would compute `block_id % 2 == 2` — nothing — and the odd blocks would never
be sent.

(Within a *single* session, a mid-transfer death is not redistributed: the
survivors keep the shards they were assigned, and that sender's blocks are
logged lost. The residue shift above happens between sessions, when file-monitor
re-derives the assignment from the current live set.)
