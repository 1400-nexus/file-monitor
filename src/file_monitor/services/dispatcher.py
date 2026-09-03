from pathlib import Path

import structlog

from file_monitor.domain.ids import SenderId, SessionId
from file_monitor.domain.models import FecParams, ShardAssignment, SourceFile
from file_monitor.domain.planning import calculate_block_count, derive_shard_assignments
from file_monitor.ipc import codec
from file_monitor.ipc.errors import SendQueueFullError, UnknownSenderError
from file_monitor.ports.protocols import Clock, Hasher, IpcServer
from file_monitor.services import planner
from file_monitor.services.constants import DISPATCH_RETRY_DELAY_SECONDS, MAX_DISPATCH_ATTEMPTS
from file_monitor.services.registry import SenderRegistry

logger = structlog.get_logger(__name__)


class SessionDispatcher:
    def __init__(
        self,
        ipc: IpcServer,
        hasher: Hasher,
        registry: SenderRegistry,
        clock: Clock,
        fec_params: FecParams,
        watch_root: Path,
        target_host: str,
        base_port: int,
    ) -> None:
        self._ipc: IpcServer = ipc
        self._hasher: Hasher = hasher
        self._registry: SenderRegistry = registry
        self._clock: Clock = clock
        self._fec_params: FecParams = fec_params
        self._watch_root: Path = watch_root
        self._target_host: str = target_host
        self._base_port: int = base_port
        self._dispatched_sessions: dict[SessionId, list[SenderId]] = {}

    async def dispatch(self, path: Path) -> SessionId | None:
        size_bytes = path.stat().st_size
        file_hash = await self._hasher.compute_hash(path)
        source_file = SourceFile(path=path, size_bytes=size_bytes, file_hash=file_hash)

        active_senders = self._registry.active_senders()
        if not active_senders:
            logger.warning("dispatch_skipped_no_active_senders", path=str(path))
            return None

        session_id = planner.generate_session_id()
        total_blocks = calculate_block_count(source_file.size_bytes, self._fec_params)

        succeeded_sender_ids = await self._send_to_senders(
            session_id, source_file, total_blocks, active_senders
        )
        if succeeded_sender_ids is None:
            return None

        self._dispatched_sessions[session_id] = succeeded_sender_ids
        return session_id

    def complete_session(self, session_id: SessionId) -> None:
        self._dispatched_sessions.pop(session_id, None)

    async def _send_to_senders(
        self,
        session_id: SessionId,
        source_file: SourceFile,
        total_blocks: int,
        active_senders: list[SenderId],
    ) -> list[SenderId] | None:
        # Every sender gets at most one AssignSession per session_id: the
        # wire contract doesn't say whether a later one supersedes an
        # earlier one (flagged for the team). A failed sender's shard is
        # lost, not redistributed to survivors.
        assignments = derive_shard_assignments(total_blocks, active_senders, self._base_port)

        succeeded: list[SenderId] = []
        lost_assignments: list[ShardAssignment] = []

        for assignment in assignments:
            manifest = planner.build_manifest(
                source_file,
                self._fec_params,
                session_id=session_id,
                sender_index=assignment.shard_residue,
                shard_modulus=assignment.shard_modulus,
                watch_root=self._watch_root,
            )
            assign_session = planner.build_assign_session(
                manifest,
                shard_modulus=assignment.shard_modulus,
                target_host=self._target_host,
                target_port=assignment.target_port,
            )
            payload = codec.encode(assign_session)

            if await self._deliver(session_id, assignment, payload):
                logger.info(
                    "session_dispatched",
                    session_id=session_id,
                    sender_id=assignment.sender_id,
                    shard_residue=assignment.shard_residue,
                    shard_modulus=assignment.shard_modulus,
                    target_port=assignment.target_port,
                    block_count=len(assignment.assigned_blocks),
                )
                succeeded.append(assignment.sender_id)
            else:
                lost_assignments.append(assignment)

        if lost_assignments:
            self._log_partial_failure(session_id, lost_assignments)

        return succeeded or None

    async def _deliver(
        self, session_id: SessionId, assignment: ShardAssignment, payload: bytes
    ) -> bool:
        for attempt in range(MAX_DISPATCH_ATTEMPTS):
            try:
                await self._ipc.send(assignment.sender_id, payload)
            except UnknownSenderError as error:
                logger.warning(
                    "dispatch_send_failed",
                    session_id=session_id,
                    sender_id=assignment.sender_id,
                    reason="sender_disconnected",
                    error=str(error),
                )
                self._registry.remove(assignment.sender_id)
                return False
            except SendQueueFullError as error:
                logger.warning(
                    "dispatch_send_failed",
                    session_id=session_id,
                    sender_id=assignment.sender_id,
                    reason="send_queue_full",
                    error=str(error),
                )
                if attempt < MAX_DISPATCH_ATTEMPTS - 1:
                    await self._clock.sleep(DISPATCH_RETRY_DELAY_SECONDS)
                continue
            else:
                return True
        return False

    def _log_partial_failure(
        self, session_id: SessionId, lost_assignments: list[ShardAssignment]
    ) -> None:
        # (shard_residue, shard_modulus, block_count) identifies the lost
        # blocks exactly, without enumerating what could be thousands of ids.
        lost_block_count = sum(len(assignment.assigned_blocks) for assignment in lost_assignments)
        logger.error(
            "dispatch_partially_failed",
            session_id=session_id,
            failed_sender_ids=[assignment.sender_id for assignment in lost_assignments],
            lost_block_count=lost_block_count,
            lost_shards=[
                {
                    "sender_id": assignment.sender_id,
                    "shard_residue": assignment.shard_residue,
                    "shard_modulus": assignment.shard_modulus,
                    "block_count": len(assignment.assigned_blocks),
                }
                for assignment in lost_assignments
            ],
        )
