"""Tool execution context — shared dependencies for all tool handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentbenchplatform.infra.db.agent_events import AgentEventRepo
    from agentbenchplatform.infra.db.coordinator_history import CoordinatorHistoryRepo
    from agentbenchplatform.infra.db.session_reports import SessionReportRepo
    from agentbenchplatform.infra.db.usage import UsageRepo
    from agentbenchplatform.infra.db.workspaces import WorkspaceRepo
    from agentbenchplatform.services.memory_service import MemoryService
    from agentbenchplatform.services.research_service import ResearchService
    from agentbenchplatform.services.session_service import SessionService
    from agentbenchplatform.services.task_service import TaskService
    from agentbenchplatform.config import AppConfig


@dataclass
class ToolContext:
    """Dependency bundle passed to every tool handler.

    Keeps tool handlers decoupled from CoordinatorService while giving
    them access to all services and repos they need.
    """

    session: SessionService
    task: TaskService
    memory: MemoryService
    config: AppConfig
    research: ResearchService | None = None
    signal: Any = None  # SignalService, late-bound
    usage_repo: UsageRepo | None = None
    history_repo: CoordinatorHistoryRepo | None = None
    session_report_repo: SessionReportRepo | None = None
    agent_event_repo: AgentEventRepo | None = None
    workspace_repo: WorkspaceRepo | None = None
    merge_record_repo: Any = None
    session_metric_repo: Any = None
    playbook_repo: Any = None

    # Callbacks into coordinator for cross-cutting concerns
    emit_event: Any = None  # async (session_id, task_id, event_type, detail) -> None
    execute_tool: Any = None  # async (name, arguments) -> Any  (for playbook self-calls)
    llm_config: Any = None  # LLMConfig
    provider: Any = None  # LLM provider for review summaries

    # Mutable state references
    session_deadlines: dict | None = None
    session_output_hashes: dict | None = None
    conversations: dict | None = None
