# Stub sender

`stub_sender.py` is a throwaway peer that stands in for B's C++ sender. It is
the only check of the wire contract from the *receiving* side, rather than
from file-monitor's own tests — it exists to be replaced by the real C++
sender at integration, at which point this file (and the milestone runner
below) can be deleted.

## Why it can't import file_monitor.services or file_monitor.domain

If the stub shared file-monitor's own planning code (shard assignment, block
math, session bookkeeping), it would agree with the server by construction —
of course a copy of the same code produces the same numbers. That would prove
nothing about whether the *wire contract* is actually correct or whether an
independent implementation (the C++ sender) can agree with it.

The stub is only allowed to import `file_monitor.ipc.codec`,
`file_monitor.ipc.handshake`, and `file_monitor.ipc.constants` — those three
modules **are** the wire format (protobuf envelope encode/decode, the
proto-hash handshake algorithm, buffer sizing), not file-monitor's business
logic. Everything else the stub does — deriving which blocks a given
`(shard_residue, total_senders)` pair owns, checking `filepath` for
path-traversal — is written from scratch against the `.proto` files and the
printed/JSON output, the same way the C++ sender has to.

## Running a single stub by hand

```bash
export PYTHONPATH=libs/nexus-proto/generated/python
python -m file_monitor.main &                      # in one terminal
python tests/integration/stub_sender.py \
    --sender-id 0 --socket ./run/file-monitor.sock  # in another
```

Useful flags:

- `--json` — in addition to the human-readable printout, emit one
  `ASSIGN {...}` line per `AssignSession` so a script can parse it
  (`sender_arg`, `session_id`, `filepath`, `file_size`, `total_blocks`, `k`,
  `n`, `block_bytes`, `shard_residue`, `total_senders`, `target_host`,
  `target_port`, `blocks`).
- `--exit-after-assignments N` — exit 0 once N `AssignSession` messages have
  arrived (exit 1 if the connection closes first). Lets a caller wait on the
  process instead of guessing a sleep duration.
- `--expect-refused` — send the handshake and exit 0 if the server closes the
  connection (or never accepts it) within a few seconds, exit 1 if it doesn't.
  For exercising a deliberately wrong `--proto-dir`.

## Running the milestones

```bash
git submodule update --init   # if not already done
pip install -e '.[dev]'
scripts/run_milestones.sh
```

This starts a real `file-monitor` process (with its own temporary
`watch/`/`run/`/config, never touching the repo working tree) and drives it
through three scenarios end to end, printing a PASS/FAIL table:

1. **Three senders, disjoint and complete** — three stubs connect, a file is
   copied in, and each stub's shard is asserted disjoint from the others with
   their union covering every block exactly once.
2. **A dead sender degrades cleanly** — one sender is killed and the script
   waits past the registry's heartbeat-expiry window before copying a second
   file, so the surviving two are dispatched to as a clean 2-sender set (this
   is why no `dispatch_partially_failed` line is expected for that dispatch —
   see the comment in `run_milestones.sh` for the timing this depends on).
3. **A wrong contract hash is refused** — a stub started against a tampered
   copy of the `.proto` files is asserted to be refused, and the three
   original stubs are asserted to still be connected afterward.

The script requires nothing beyond the submodule and `pip install -e '.[dev]'`
having been run; it computes its own `PYTHONPATH` and creates its own
temporary directories via `mktemp -d`, cleaned up on exit (including on
Ctrl-C) by a trap.
