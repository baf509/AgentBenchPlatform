"""RemoteContext: drop-in replacement for AppContext that delegates to server via RPC."""

from __future__ import annotations

import logging
from typing import Any

from agentbenchplatform.infra.rpc.client import RpcClient
from agentbenchplatform.infra.rpc.serialization import (
    deserialize_agent_event,
    deserialize_coordinator_decision,
    deserialize_dashboard_snapshot,
    deserialize_memory,
    deserialize_session,
    deserialize_session_report,
    deserialize_task,
    deserialize_usage,
    deserialize_workspace,
    deserialize_workspace_snapshot,
)
from agentbenchplatform.models.memory import MemoryQuery, MemoryScope
from agentbenchplatform.models.workspace import Workspace

logger = logging.getLogger(__name__)


class RemoteContext:
    """Proxy for AppContext that routes all calls to the RPC server.

    Provides the same property interface as AppContext so the TUI and CLI
    commands can use it without knowing whether they're local or remote.
    """

    def __init__(self, socket_path: str) -> None:
        self._client = RpcClient(socket_path)
        self._task_service: RemoteTaskService | None = None
        self._session_service: RemoteSessionService | None = None
        self._coordinator_service: RemoteCoordinatorService | None = None
        self._dashboard_service: RemoteDashboardService | None = None
        self._memory_service: RemoteMemoryService | None = None
        self._signal_service: RemoteSignalService | None = None
        self._usage_repo: RemoteUsageRepo | None = None
        self._coordinator_history_repo: RemoteCoordinatorHistoryRepo | None = None
        self._session_report_repo: RemoteSessionReportRepo | None = None
        self._agent_event_repo: RemoteAgentEventRepo | None = None
        self._coordinator_decision_repo: RemoteCoordinatorDecisionRepo | None = None
        self._workspace_repo: RemoteWorkspaceRepo | None = None
        self._db_explorer: RemoteDbExplorer | None = None

    async def initialize(self) -> None:
        """Connect to the server and verify it's running."""
        await self._client.connect()
        result = await self._client.call("server.ping")
        if result != "pong":
            raise RuntimeError("Server did not respond to ping")
        logger.info("RemoteContext connected to server")

    async def close(self) -> None:
        """Close the RPC client connection."""
        await self._client.close()
        logger.info("RemoteContext disconnected")

    @property
    def task_service(self) -> RemoteTaskService:
        if self._task_service is None:
            self._task_service = RemoteTaskService(self._client)
        return self._task_service

    @property
    def session_service(self) -> RemoteSessionService:
        if self._session_service is None:
            self._session_service = RemoteSessionService(self._client)
        return self._session_service

    @property
    def coordinator_service(self) -> RemoteCoordinatorService:
        if self._coordinator_service is None:
            self._coordinator_service = RemoteCoordinatorService(self._client)
        return self._coordinator_service

    @property
    def dashboard_service(self) -> RemoteDashboardService:
        if self._dashboard_service is None:
            self._dashboard_service = RemoteDashboardService(self._client)
        return self._dashboard_service

    @property
    def memory_service(self) -> RemoteMemoryService:
        if self._memory_service is None:
            self._memory_service = RemoteMemoryService(self._client)
        return self._memory_service

    @property
    def signal_service(self) -> RemoteSignalService:
        if self._signal_service is None:
            self._signal_service = RemoteSignalService(self._client)
        return self._signal_service

    @property
    def usage_repo(self) -> RemoteUsageRepo:
        if self._usage_repo is None:
            self._usage_repo = RemoteUsageRepo(self._client)
        return self._usage_repo

    @property
    def coordinator_history_repo(self) -> RemoteCoordinatorHistoryRepo:
        if self._coordinator_history_repo is None:
            self._coordinator_history_repo = RemoteCoordinatorHistoryRepo(self._client)
        return self._coordinator_history_repo

    @property
    def session_report_repo(self) -> RemoteSessionReportRepo:
        if self._session_report_repo is None:
            self._session_report_repo = RemoteSessionReportRepo(self._client)
        return self._session_report_repo

    @property
    def agent_event_repo(self) -> RemoteAgentEventRepo:
        if self._agent_event_repo is None:
            self._agent_event_repo = RemoteAgentEventRepo(self._client)
        return self._agent_event_repo

    @property
    def coordinator_decision_repo(self) -> RemoteCoordinatorDecisionRepo:
        if self._coordinator_decision_repo is None:
            self._coordinator_decision_repo = RemoteCoordinatorDecisionRepo(self._client)
        return self._coordinator_decision_repo

    @property
    def workspace_repo(self) -> RemoteWorkspaceRepo:
        if self._workspace_repo is None:
            self._workspace_repo = RemoteWorkspaceRepo(self._client)
        return self._workspace_repo

    @property
    def db_explorer(self) -> RemoteDbExplorer:
        if self._db_explorer is None:
            self._db_explorer = RemoteDbExplorer(self._client)
        return self._db_explorer


class RemoteTaskService:
    """Proxy for TaskService over RPC."""

    def __init__(self, client: RpcClient) -> None:
        self._client = client

    async def create_task(self, title: str, description: str = "",
                          workspace_path: str = "", tags: tuple[str, ...] = (),
                          complexity: str = "") -> Any:
        data = await self._client.call(
            "task.create", title=title, description=description,
            workspace_path=workspace_path, tags=list(tags), complexity=complexity,
        )
        return deserialize_task(data)

    async def get_task(self, slug: str) -> Any:
        data = await self._client.call("task.get", slug=slug)
        return deserialize_task(data) if data else None

    async def get_task_by_id(self, task_id: str) -> Any:
        data = await self._client.call("task.get_by_id", task_id=task_id)
        return deserialize_task(data) if data else None

    async def list_tasks(self, show_all: bool = False, archived: bool = False) -> list:
        data = await self._client.call("task.list", show_all=show_all, archived=archived)
        return [deserialize_task(t) for t in data]

    async def archive_task(self, slug: str) -> Any:
        data = await self._client.call("task.archive", slug=slug)
        return deserialize_task(data) if data else None

    async def delete_task(self, slug: str) -> Any:
        data = await self._client.call("task.delete", slug=slug)
        return deserialize_task(data) if data else None


class RemoteSessionService:
    """Proxy for SessionService over RPC."""

    def __init__(self, client: RpcClient) -> None:
        self._client = client

    async def start_coding_session(self, task_id: str, agent_type: str = "",
                                   prompt: str = "", model: str = "",
                                   workspace_path: str = "",
                                   task_tags: tuple[str, ...] = (),
                                   task_complexity: str = "") -> Any:
        data = await self._client.call(
            "session.start_coding", task_id=task_id, agent_type=agent_type,
            prompt=prompt, model=model, workspace_path=workspace_path,
            task_tags=list(task_tags), task_complexity=task_complexity,
        )
        return deserialize_session(data)

    async def get_session(self, session_id: str) -> Any:
        data = await self._client.call("session.get", session_id=session_id)
        return deserialize_session(data) if data else None

    async def list_sessions(self, task_id: str = "") -> list:
        data = await self._client.call("session.list", task_id=task_id)
        return [deserialize_session(s) for s in data]

    async def stop_session(self, session_id: str) -> Any:
        data = await self._client.call("session.stop", session_id=session_id)
        return deserialize_session(data) if data else None

    async def pause_session(self, session_id: str) -> Any:
        data = await self._client.call("session.pause", session_id=session_id)
        return deserialize_session(data) if data else None

    async def resume_session(self, session_id: str) -> Any:
        data = await self._client.call("session.resume", session_id=session_id)
        return deserialize_session(data) if data else None

    async def archive_session(self, session_id: str) -> Any:
        data = await self._client.call("session.archive", session_id=session_id)
        return deserialize_session(data) if data else None

    async def get_session_output(self, session_id: str, lines: int = 100) -> str:
        return await self._client.call(
            "session.get_output", session_id=session_id, lines=lines,
        )

    async def send_to_session(self, session_id: str, text: str) -> bool:
        return await self._client.call(
            "session.send_to", session_id=session_id, text=text,
        )

    async def check_session_liveness(self, session_id: str) -> bool:
        return await self._client.call(
            "session.check_liveness", session_id=session_id,
        )

    async def get_session_diff(self, session_id: str) -> str:
        return await self._client.call(
            "session.get_diff", session_id=session_id,
        )

    async def run_in_worktree(self, session_id: str, command: str) -> str:
        return await self._client.call(
            "session.run_in_worktree", session_id=session_id, command=command,
        )


class RemoteCoordinatorService:
    """Proxy for CoordinatorService over RPC."""

    def __init__(self, client: RpcClient) -> None:
        self._client = client

    async def handle_message(self, user_message: str, channel: str = "rpc",
                             sender_id: str = "",
                             on_progress: Any = None) -> str:
        result = await self._client.call_streaming(
            "coordinator.message",
            on_notification=on_progress,
            user_message=user_message,
            channel=channel,
            sender_id=sender_id,
        )
        return result.get("response", "") if isinstance(result, dict) else str(result)

    async def ask(self, question: str) -> str:
        return await self._client.call("coordinator.ask", question=question)


class RemoteDashboardService:
    """Proxy for DashboardService over RPC."""

    def __init__(self, client: RpcClient) -> None:
        self._client = client

    async def load_snapshot(self) -> Any:
        data = await self._client.call("dashboard.snapshot")
        return deserialize_dashboard_snapshot(data)

    async def load_workspaces(self) -> list:
        data = await self._client.call("dashboard.workspaces")
        return [deserialize_workspace_snapshot(ws) for ws in data]


class RemoteMemoryService:
    """Proxy for MemoryService over RPC."""

    def __init__(self, client: RpcClient) -> None:
        self._client = client

    async def store(self, key: str, content: str,
                    scope: MemoryScope = MemoryScope.GLOBAL,
                    task_id: str = "", session_id: str = "",
                    content_type: str = "text",
                    metadata: dict | None = None) -> Any:
        data = await self._client.call(
            "memory.store", key=key, content=content, scope=scope.value,
            task_id=task_id, session_id=session_id,
            content_type=content_type, metadata=metadata,
        )
        return deserialize_memory(data)

    async def search(self, query: MemoryQuery) -> list:
        data = await self._client.call(
            "memory.search", query_text=query.query_text,
            task_id=query.task_id,
            scope=query.scope.value if query.scope else None,
            limit=query.limit,
        )
        return [deserialize_memory(m) for m in data]

    async def list_memories(self, task_id: str = "",
                            scope: MemoryScope | None = None) -> list:
        data = await self._client.call(
            "memory.list", task_id=task_id,
            scope=scope.value if scope else None,
        )
        return [deserialize_memory(m) for m in data]

    async def delete_memory(self, memory_id: str) -> bool:
        return await self._client.call("memory.delete", memory_id=memory_id)


class RemoteSignalService:
    """Proxy for SignalService over RPC."""

    def __init__(self, client: RpcClient) -> None:
        self._client = client

    async def start(self) -> None:
        await self._client.call("signal.start")

    async def stop(self) -> None:
        await self._client.call("signal.stop")

    async def status(self) -> dict:
        return await self._client.call("signal.status")

    async def pair_sender(self, phone: str) -> None:
        await self._client.call("signal.pair_sender", phone=phone)

    async def is_running(self) -> bool:
        """Check if the signal daemon is running via RPC."""
        result = await self._client.call("signal.is_running")
        return bool(result)


class RemoteUsageRepo:
    """Proxy for UsageRepo over RPC."""

    def __init__(self, client: RpcClient) -> None:
        self._client = client

    async def aggregate_recent(self, hours: int = 6) -> dict:
        return await self._client.call("usage.aggregate_recent", hours=hours)

    async def aggregate_totals(self) -> dict:
        return await self._client.call("usage.aggregate_totals")

    async def list_recent(self, limit: int = 20) -> list:
        data = await self._client.call("usage.list_recent", limit=limit)
        return [deserialize_usage(e) for e in data]


class RemoteCoordinatorHistoryRepo:
    """Proxy for CoordinatorHistoryRepo over RPC."""

    def __init__(self, client: RpcClient) -> None:
        self._client = client

    async def list_conversations(self) -> list[dict]:
        return await self._client.call("coordinator_history.list_conversations")

    async def load_conversation(self, channel: str, sender_id: str = "") -> list:
        from agentbenchplatform.models.provider import LLMMessage

        data = await self._client.call(
            "coordinator_history.load_conversation",
            channel=channel, sender_id=sender_id,
        )
        return [
            LLMMessage(
                role=m["role"],
                content=m.get("content", ""),
                tool_call_id=m.get("tool_call_id", ""),
                tool_calls=m.get("tool_calls"),
                name=m.get("name", ""),
            )
            for m in data
        ]


class RemoteDbExplorer:
    """Proxy for DB Explorer operations over RPC."""

    def __init__(self, client: RpcClient) -> None:
        self._client = client

    async def list_databases(self) -> list[str]:
        return await self._client.call("db.list_databases")

    async def list_collections(self, db_name: str) -> list[str]:
        return await self._client.call("db.list_collections", db_name=db_name)

    async def collection_info(self, db_name: str, collection_name: str) -> dict:
        return await self._client.call(
            "db.collection_info", db_name=db_name, collection_name=collection_name,
        )

    async def collection_indexes(self, db_name: str, collection_name: str) -> dict:
        return await self._client.call(
            "db.collection_indexes", db_name=db_name, collection_name=collection_name,
        )

    async def collection_search_indexes(self, db_name: str, collection_name: str) -> list[dict]:
        return await self._client.call(
            "db.collection_search_indexes", db_name=db_name, collection_name=collection_name,
        )


class RemoteWorkspaceRepo:
    """Proxy for WorkspaceRepo over RPC."""

    def __init__(self, client: RpcClient) -> None:
        self._client = client

    async def find_by_path(self, path: str) -> Any:
        data = await self._client.call("workspace.find_by_path", path=path)
        return deserialize_workspace(data) if data else None

    async def insert(self, workspace: Workspace) -> Any:
        data = await self._client.call(
            "workspace.insert", path=workspace.path, name=workspace.name,
        )
        return deserialize_workspace(data)

    async def list_all(self) -> list:
        data = await self._client.call("workspace.list_all")
        return [deserialize_workspace(ws) for ws in data]

    async def delete(self, workspace_id: str) -> bool:
        return await self._client.call("workspace.delete", workspace_id=workspace_id)


class RemoteSessionReportRepo:
    """Proxy for SessionReportRepo over RPC."""

    def __init__(self, client: RpcClient) -> None:
        self._client = client

    async def find_by_session(self, session_id: str) -> Any:
        data = await self._client.call("session_report.get", session_id=session_id)
        return deserialize_session_report(data) if data else None

    async def list_by_task(self, task_id: str, limit: int = 20) -> list:
        data = await self._client.call(
            "session_report.list_by_task", task_id=task_id, limit=limit,
        )
        return [deserialize_session_report(r) for r in data]


class RemoteAgentEventRepo:
    """Proxy for AgentEventRepo over RPC."""

    def __init__(self, client: RpcClient) -> None:
        self._client = client

    async def list_unacknowledged(
        self, event_types: list[str] | None = None, limit: int = 50
    ) -> list:
        data = await self._client.call(
            "agent_event.list_unacknowledged",
            event_types=event_types, limit=limit,
        )
        return [deserialize_agent_event(e) for e in data]

    async def acknowledge(self, event_ids: list[str]) -> int:
        return await self._client.call(
            "agent_event.acknowledge", event_ids=event_ids,
        )

    async def list_by_session(self, session_id: str, limit: int = 50) -> list:
        data = await self._client.call(
            "agent_event.list_by_session",
            session_id=session_id, limit=limit,
        )
        return [deserialize_agent_event(e) for e in data]


class RemoteCoordinatorDecisionRepo:
    """Proxy for CoordinatorDecisionRepo over RPC."""

    def __init__(self, client: RpcClient) -> None:
        self._client = client

    async def list_recent(self, limit: int = 20) -> list:
        data = await self._client.call(
            "coordinator_decision.list_recent", limit=limit,
        )
        return [deserialize_coordinator_decision(d) for d in data]
