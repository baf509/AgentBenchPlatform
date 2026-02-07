"""RPC method registry: maps JSON-RPC method names to AppContext service calls."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agentbenchplatform.infra.rpc.serialization import (
    serialize_dashboard_snapshot,
    serialize_memory,
    serialize_session,
    serialize_task,
    serialize_usage,
    serialize_workspace,
    serialize_workspace_snapshot,
)
from agentbenchplatform.models.memory import MemoryQuery, MemoryScope

if TYPE_CHECKING:
    from agentbenchplatform.context import AppContext

logger = logging.getLogger(__name__)


class MethodRegistry:
    """Dispatch table mapping RPC method names to service calls."""

    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx
        self._methods: dict[str, Any] = {}
        self._register_all()

    def _register_all(self) -> None:
        """Register all RPC methods."""
        # Server
        self._methods["server.ping"] = self._server_ping
        self._methods["server.status"] = self._server_status

        # Task
        self._methods["task.list"] = self._task_list
        self._methods["task.get"] = self._task_get
        self._methods["task.get_by_id"] = self._task_get_by_id
        self._methods["task.create"] = self._task_create
        self._methods["task.archive"] = self._task_archive
        self._methods["task.delete"] = self._task_delete

        # Session
        self._methods["session.list"] = self._session_list
        self._methods["session.get"] = self._session_get
        self._methods["session.start_coding"] = self._session_start_coding
        self._methods["session.stop"] = self._session_stop
        self._methods["session.pause"] = self._session_pause
        self._methods["session.resume"] = self._session_resume
        self._methods["session.archive"] = self._session_archive
        self._methods["session.get_output"] = self._session_get_output
        self._methods["session.send_to"] = self._session_send_to
        self._methods["session.check_liveness"] = self._session_check_liveness
        self._methods["session.get_diff"] = self._session_get_diff
        self._methods["session.run_in_worktree"] = self._session_run_in_worktree

        # Dashboard
        self._methods["dashboard.snapshot"] = self._dashboard_snapshot
        self._methods["dashboard.workspaces"] = self._dashboard_workspaces

        # Coordinator
        self._methods["coordinator.message"] = self._coordinator_message
        self._methods["coordinator.ask"] = self._coordinator_ask

        # Memory
        self._methods["memory.list"] = self._memory_list
        self._methods["memory.search"] = self._memory_search
        self._methods["memory.store"] = self._memory_store

        # Usage
        self._methods["usage.aggregate_recent"] = self._usage_aggregate_recent
        self._methods["usage.aggregate_totals"] = self._usage_aggregate_totals
        self._methods["usage.list_recent"] = self._usage_list_recent

        # Workspace
        self._methods["workspace.find_by_path"] = self._workspace_find_by_path
        self._methods["workspace.insert"] = self._workspace_insert
        self._methods["workspace.delete"] = self._workspace_delete

        # Signal
        self._methods["signal.start"] = self._signal_start
        self._methods["signal.stop"] = self._signal_stop
        self._methods["signal.status"] = self._signal_status
        self._methods["signal.pair_sender"] = self._signal_pair_sender

        # Coordinator history
        self._methods["coordinator_history.list_conversations"] = self._ch_list
        self._methods["coordinator_history.load_conversation"] = self._ch_load

    async def dispatch(self, method: str, params: dict) -> Any:
        """Dispatch an RPC method call. Returns serializable result."""
        handler = self._methods.get(method)
        if handler is None:
            raise ValueError(f"Unknown method: {method}")
        return await handler(params)

    def has_method(self, method: str) -> bool:
        return method in self._methods

    # --- Server ---

    async def _server_ping(self, params: dict) -> str:
        return "pong"

    async def _server_status(self, params: dict) -> dict:
        return {
            "status": "running",
            "signal_enabled": self._ctx.config.signal.enabled,
        }

    # --- Task ---

    async def _task_list(self, params: dict) -> list[dict]:
        tasks = await self._ctx.task_service.list_tasks(
            show_all=params.get("show_all", False),
            archived=params.get("archived", False),
        )
        return [serialize_task(t) for t in tasks]

    async def _task_get(self, params: dict) -> dict | None:
        task = await self._ctx.task_service.get_task(params["slug"])
        return serialize_task(task) if task else None

    async def _task_get_by_id(self, params: dict) -> dict | None:
        task = await self._ctx.task_service.get_task_by_id(params["task_id"])
        return serialize_task(task) if task else None

    async def _task_create(self, params: dict) -> dict:
        task = await self._ctx.task_service.create_task(
            title=params["title"],
            description=params.get("description", ""),
            workspace_path=params.get("workspace_path", ""),
            tags=tuple(params.get("tags", [])),
            complexity=params.get("complexity", ""),
        )
        return serialize_task(task)

    async def _task_archive(self, params: dict) -> dict | None:
        task = await self._ctx.task_service.archive_task(params["slug"])
        return serialize_task(task) if task else None

    async def _task_delete(self, params: dict) -> dict | None:
        task = await self._ctx.task_service.delete_task(params["slug"])
        return serialize_task(task) if task else None

    # --- Session ---

    async def _session_list(self, params: dict) -> list[dict]:
        sessions = await self._ctx.session_service.list_sessions(
            task_id=params.get("task_id", ""),
        )
        return [serialize_session(s) for s in sessions]

    async def _session_get(self, params: dict) -> dict | None:
        session = await self._ctx.session_service.get_session(params["session_id"])
        return serialize_session(session) if session else None

    async def _session_start_coding(self, params: dict) -> dict:
        session = await self._ctx.session_service.start_coding_session(
            task_id=params["task_id"],
            agent_type=params.get("agent_type", ""),
            prompt=params.get("prompt", ""),
            model=params.get("model", ""),
            workspace_path=params.get("workspace_path", ""),
            task_tags=tuple(params.get("task_tags", [])),
            task_complexity=params.get("task_complexity", ""),
        )
        return serialize_session(session)

    async def _session_stop(self, params: dict) -> dict | None:
        session = await self._ctx.session_service.stop_session(params["session_id"])
        return serialize_session(session) if session else None

    async def _session_pause(self, params: dict) -> dict | None:
        session = await self._ctx.session_service.pause_session(params["session_id"])
        return serialize_session(session) if session else None

    async def _session_resume(self, params: dict) -> dict | None:
        session = await self._ctx.session_service.resume_session(params["session_id"])
        return serialize_session(session) if session else None

    async def _session_archive(self, params: dict) -> dict | None:
        session = await self._ctx.session_service.archive_session(params["session_id"])
        return serialize_session(session) if session else None

    async def _session_get_output(self, params: dict) -> str:
        return await self._ctx.session_service.get_session_output(
            params["session_id"],
            lines=params.get("lines", 100),
        )

    async def _session_send_to(self, params: dict) -> bool:
        return await self._ctx.session_service.send_to_session(
            params["session_id"], params["text"]
        )

    async def _session_check_liveness(self, params: dict) -> bool:
        return await self._ctx.session_service.check_session_liveness(
            params["session_id"]
        )

    async def _session_get_diff(self, params: dict) -> str:
        return await self._ctx.session_service.get_session_diff(
            params["session_id"]
        )

    async def _session_run_in_worktree(self, params: dict) -> str:
        return await self._ctx.session_service.run_in_worktree(
            params["session_id"], params["command"]
        )

    # --- Dashboard ---

    async def _dashboard_snapshot(self, params: dict) -> dict:
        snapshot = await self._ctx.dashboard_service.load_snapshot()
        return serialize_dashboard_snapshot(snapshot)

    async def _dashboard_workspaces(self, params: dict) -> list[dict]:
        workspaces = await self._ctx.dashboard_service.load_workspaces()
        return [serialize_workspace_snapshot(ws) for ws in workspaces]

    # --- Coordinator ---

    async def _coordinator_message(self, params: dict) -> dict:
        """Handle coordinator message. Returns {"response": str, "progress": [str]}.

        Progress callbacks are collected and returned in the result since streaming
        notifications are handled at the server transport level.
        """
        progress_items: list[str] = []

        def on_progress(text: str) -> None:
            progress_items.append(text)

        response = await self._ctx.coordinator_service.handle_message(
            user_message=params["user_message"],
            channel=params.get("channel", "rpc"),
            sender_id=params.get("sender_id", ""),
            on_progress=on_progress,
        )
        return {"response": response, "progress": progress_items}

    async def _coordinator_ask(self, params: dict) -> str:
        return await self._ctx.coordinator_service.ask(params["question"])

    # --- Memory ---

    async def _memory_list(self, params: dict) -> list[dict]:
        scope = MemoryScope(params["scope"]) if params.get("scope") else None
        memories = await self._ctx.memory_service.list_memories(
            task_id=params.get("task_id", ""),
            scope=scope,
        )
        return [serialize_memory(m) for m in memories]

    async def _memory_search(self, params: dict) -> list[dict]:
        scope = MemoryScope(params["scope"]) if params.get("scope") else None
        query = MemoryQuery(
            query_text=params["query_text"],
            task_id=params.get("task_id", ""),
            scope=scope,
            limit=params.get("limit", 10),
        )
        results = await self._ctx.memory_service.search(query)
        return [serialize_memory(m) for m in results]

    async def _memory_store(self, params: dict) -> dict:
        scope = MemoryScope(params.get("scope", "global"))
        entry = await self._ctx.memory_service.store(
            key=params["key"],
            content=params["content"],
            scope=scope,
            task_id=params.get("task_id", ""),
            session_id=params.get("session_id", ""),
            content_type=params.get("content_type", "text"),
            metadata=params.get("metadata"),
        )
        return serialize_memory(entry)

    # --- Usage ---

    async def _usage_aggregate_recent(self, params: dict) -> dict:
        return await self._ctx.usage_repo.aggregate_recent(
            hours=params.get("hours", 6),
        )

    async def _usage_aggregate_totals(self, params: dict) -> dict:
        return await self._ctx.usage_repo.aggregate_totals()

    async def _usage_list_recent(self, params: dict) -> list[dict]:
        events = await self._ctx.usage_repo.list_recent(
            limit=params.get("limit", 20),
        )
        return [serialize_usage(e) for e in events]

    # --- Workspace ---

    async def _workspace_find_by_path(self, params: dict) -> dict | None:
        ws = await self._ctx.workspace_repo.find_by_path(params["path"])
        return serialize_workspace(ws) if ws else None

    async def _workspace_insert(self, params: dict) -> dict:
        from agentbenchplatform.models.workspace import Workspace

        ws = Workspace(
            path=params["path"],
            name=params.get("name", ""),
        )
        ws = await self._ctx.workspace_repo.insert(ws)
        return serialize_workspace(ws)

    async def _workspace_delete(self, params: dict) -> bool:
        return await self._ctx.workspace_repo.delete(params["workspace_id"])

    # --- Signal ---

    async def _signal_start(self, params: dict) -> str:
        await self._ctx.signal_service.start()
        return "started"

    async def _signal_stop(self, params: dict) -> str:
        await self._ctx.signal_service.stop()
        return "stopped"

    async def _signal_status(self, params: dict) -> dict:
        return await self._ctx.signal_service.status()

    async def _signal_pair_sender(self, params: dict) -> str:
        await self._ctx.signal_service.pair_sender(params["phone"])
        return "paired"

    # --- Coordinator History ---

    async def _ch_list(self, params: dict) -> list[dict]:
        convos = await self._ctx.coordinator_history_repo.list_conversations()
        # datetime values need to be serialized
        for c in convos:
            if "updated_at" in c and c["updated_at"] is not None:
                c["updated_at"] = c["updated_at"].isoformat()
        return convos

    async def _ch_load(self, params: dict) -> list[dict]:
        messages = await self._ctx.coordinator_history_repo.load_conversation(
            channel=params["channel"],
            sender_id=params.get("sender_id", ""),
        )
        return [m.to_dict() for m in messages]
