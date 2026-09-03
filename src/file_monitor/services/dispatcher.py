from pathlib import Path

import structlog

from file_monitor.domain.ids import BlockId, SenderId
from file_monitor.domain.models import FecParams, ShardAssignment, SourceFile
from file_monitor.domain.planning import calculate_block_count, derive_shard_assignments
from file_monitor.ipc import codec
from file_monitor.ipc.errors import SendQueueFullError, UnknownSenderError
from file_monitor.ports.protocols import Hasher, IpcServer
from file_monitor.services import planner
from file_monitor.services.constants import MAX_DISPATCH_ATTEMPTS
from file_monitor.services.registry import SenderRegistry

logger = structlog.get_logger(__name__)


class SessionDispatcher:
    def __init__(
        self,
        ipc: IpcServer,
        hasher: Hasher,
        registry: SenderRegistry,
        fec_params: FecParams,
        watch_root: Path,
        target_host: str,
        base_port: int,
    ) -> None:
        self._ipc: IpcServer = ipc
        self._hasher: Hasher = hasher
        self._registry: SenderRegistry = registry
        self._fec_params: FecParams = fec_params
        self._watch_root: Path = watch_root
        self._target_host: str = target_host
        self._base_port: int = base_port
        self._dispatched_sessions: dict[str, list[SenderId]] = {}

    async def dispatch(self, path: Path) -> str | None:
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

    def complete_session(self, session_id: str) -> None:
        self._dispatched_sessions.pop(session_id, None)

    async def _send_to_senders(
        self,
        session_id: str,
        source_file: SourceFile,
        total_blocks: int,
        active_senders: list[SenderId],
    ) -> list[SenderId] | None:
        # Every sender gets at most one AssignSession for this session_id —
        # the wire contract doesn't say whether a later one supersedes an
        # earlier one (flagged for the team, unsettled with the C++ side),
        # so this never sends a second. A failed sender's shard is lost,
        # not redistributed to survivors.
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

    async def _deliver(self, session_id: str, assignment: ShardAssignment, payload: bytes) -> bool:
        # SendQueueFullError is transient and worth retrying; UnknownSenderError
        # means the peer is gone, so this assignment is abandoned immediately.
        for _attempt in range(MAX_DISPATCH_ATTEMPTS):
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
                continue
            else:
                return True
        return False

    def _log_partial_failure(
        self, session_id: str, lost_assignments: list[ShardAssignment]
    ) -> None:
        lost_block_ids: list[BlockId] = [
            block_id for assignment in lost_assignments for block_id in assignment.assigned_blocks
        ]
        logger.error(
            "dispatch_partially_failed",
            session_id=session_id,
            failed_sender_ids=[assignment.sender_id for assignment in lost_assignments],
            lost_block_ids=lost_block_ids,
        )
