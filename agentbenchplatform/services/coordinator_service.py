"""Coordinator service: meta-agent with system-wide visibility."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from agentbenchplatform.config import AppConfig
from agentbenchplatform.infra import git as git_ops
from agentbenchplatform.infra.db.agent_events import AgentEventRepo
from agentbenchplatform.infra.db.conversation_summaries import ConversationSummaryRepo
from agentbenchplatform.infra.db.coordinator_decisions import CoordinatorDecisionRepo
from agentbenchplatform.infra.db.coordinator_history import CoordinatorHistoryRepo
from agentbenchplatform.infra.db.session_reports import SessionReportRepo
from agentbenchplatform.infra.db.usage import UsageRepo
from agentbenchplatform.infra.db.workspaces import WorkspaceRepo
from agentbenchplatform.infra.providers.registry import get_provider_with_fallback
from agentbenchplatform.models.agent_event import AgentEvent, AgentEventType
from agentbenchplatform.models.conversation_summary import ConversationSummary
from agentbenchplatform.models.coordinator_decision import CoordinatorDecision, ToolCallRecord
from agentbenchplatform.models.memory import MemoryQuery, MemoryScope
from agentbenchplatform.models.provider import LLMConfig, LLMMessage
from agentbenchplatform.models.research import ResearchConfig
from agentbenchplatform.models.session import SessionLifecycle
from agentbenchplatform.models.session_report import DiffStats, SessionReport, TestResults
from agentbenchplatform.models.usage import UsageEvent
from agentbenchplatform.services.dashboard_service import DashboardService
from agentbenchplatform.services.memory_service import MemoryService
from agentbenchplatform.services.research_service import ResearchService
from agentbenchplatform.services.session_service import SessionService
from agentbenchplatform.services.task_service import TaskService

logger = logging.getLogger(__name__)

TOOL_DEFINITIONS = [
    {
        "name": "list_tasks",
        "description": "List all tasks with status summary",
        "parameters": {
            "type": "object",
            "properties": {
                "show_all": {
                    "type": "boolean",
                    "description": "Include archived/deleted tasks",
                },
            },
        },
    },
    {
        "name": "list_sessions",
        "description": "List sessions for a task or all sessions",
        "parameters": {
            "type": "object",
            "properties": {
                "task_slug": {
                    "type": "string",
                    "description": "Task slug to filter by (empty for all)",
                },
            },
        },
    },
    {
        "name": "start_coding_session",
        "description": "Start a coding session. Choose agent tier based on task complexity: claude_code (senior/complex), opencode (mid/implementation), opencode_local (junior/simple)",
        "parameters": {
            "type": "object",
            "properties": {
                "task_slug": {"type": "string", "description": "Task slug"},
                "agent": {
                    "type": "string",
                    "enum": ["claude_code", "opencode_local", "opencode"],
                    "description": "Agent tier: claude_code (senior), opencode (mid), opencode_local (junior). Choose the lowest tier capable of the work.",
                },
                "prompt": {"type": "string", "description": "Initial prompt"},
            },
            "required": ["task_slug"],
        },
    },
    {
        "name": "stop_session",
        "description": "Stop/archive a running session",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "get_session_output",
        "description": "Capture recent output from a session's tmux pane",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID"},
                "lines": {"type": "integer", "description": "Number of lines (default 50)"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "search_memory",
        "description": "Vector search over shared memories",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query text"},
                "task_slug": {"type": "string", "description": "Limit to task (optional)"},
                "limit": {"type": "integer", "description": "Max results (default 10)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "store_memory",
        "description": "Store a new shared memory entry with auto-embedding for vector search",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Memory key/identifier"},
                "content": {"type": "string", "description": "Memory content"},
                "task_slug": {"type": "string", "description": "Task to scope to (optional)"},
                "session_id": {"type": "string", "description": "Session to scope to (optional)"},
                "content_type": {"type": "string", "description": "Content type (text, code, json, etc.). Default: text"},
                "metadata": {"type": "object", "description": "Arbitrary metadata dict (optional)"},
            },
            "required": ["key", "content"],
        },
    },
    {
        "name": "create_task",
        "description": "Create a new task. Set workspace_path to enable coding sessions.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title"},
                "description": {"type": "string", "description": "Task description"},
                "workspace_path": {"type": "string", "description": "Absolute path to the project workspace (required for coding sessions)"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for categorization"},
                "complexity": {"type": "string", "enum": ["junior", "mid", "senior", ""], "description": "Task complexity tier"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "delete_task",
        "description": "Delete a task (soft-delete, hides from dashboard)",
        "parameters": {
            "type": "object",
            "properties": {
                "task_slug": {"type": "string", "description": "Task slug to delete"},
            },
            "required": ["task_slug"],
        },
    },
    {
        "name": "start_research",
        "description": "Kick off a research agent for a task",
        "parameters": {
            "type": "object",
            "properties": {
                "task_slug": {"type": "string", "description": "Task slug"},
                "query": {"type": "string", "description": "Research query"},
                "breadth": {"type": "integer", "description": "Search breadth (default 4)"},
                "depth": {"type": "integer", "description": "Search depth (default 3)"},
            },
            "required": ["task_slug", "query"],
        },
    },
    {
        "name": "get_research_status",
        "description": "Check research progress and learnings",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Research session ID"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "send_to_session",
        "description": "Send text/command to a session's tmux pane",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID"},
                "text": {"type": "string", "description": "Text to send"},
            },
            "required": ["session_id", "text"],
        },
    },
    {
        "name": "get_session_diff",
        "description": "Get the git diff from a session's worktree. Use to review work done by an agent, especially junior agents. Safe — worktree is isolated.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "run_in_worktree",
        "description": "Run a shell command in a session's worktree (e.g. 'pytest', 'npm test', 'cargo check'). Use to verify junior agent work. Timeout: 60s.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID"},
                "command": {"type": "string", "description": "Shell command to run"},
            },
            "required": ["session_id", "command"],
        },
    },
    # --- New tools ---
    {
        "name": "review_session",
        "description": "Generate a structured review of a session's work: diff stats, test results, and AI summary. Stores a SessionReport in the database. Use after a session completes to assess quality.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID to review"},
                "test_command": {"type": "string", "description": "Test command to run (e.g. 'pytest', 'npm test'). Optional."},
                "lint_command": {"type": "string", "description": "Lint command to run (e.g. 'ruff check .'). Optional."},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "pause_session",
        "description": "Pause a running session (SIGTSTP). Can be resumed later.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "resume_session",
        "description": "Resume a paused session (SIGCONT).",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "get_session_report",
        "description": "Retrieve the stored session report for a session.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "list_agent_events",
        "description": "List unacknowledged agent events (stalls, errors, completions, help requests).",
        "parameters": {
            "type": "object",
            "properties": {
                "event_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by event types (e.g. ['stalled', 'error', 'needs_help']). Optional.",
                },
                "limit": {"type": "integer", "description": "Max events to return (default 20)"},
            },
        },
    },
    {
        "name": "acknowledge_events",
        "description": "Mark agent events as handled/acknowledged.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of event IDs to acknowledge",
                },
            },
            "required": ["event_ids"],
        },
    },
    {
        "name": "set_session_deadline",
        "description": "Set an auto-stop deadline on a session. Session will be automatically stopped after the specified minutes.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID"},
                "minutes": {"type": "integer", "description": "Minutes until auto-stop"},
            },
            "required": ["session_id", "minutes"],
        },
    },
    # --- Phase 2 tools ---
    {
        "name": "get_task_detail",
        "description": "Get full task details including description, workspace_path, tags, complexity, and timestamps",
        "parameters": {
            "type": "object",
            "properties": {
                "task_slug": {"type": "string", "description": "Task slug"},
            },
            "required": ["task_slug"],
        },
    },
    {
        "name": "update_task",
        "description": "Update task fields: description, workspace_path, tags, complexity",
        "parameters": {
            "type": "object",
            "properties": {
                "task_slug": {"type": "string", "description": "Task slug"},
                "description": {"type": "string", "description": "New description"},
                "workspace_path": {"type": "string", "description": "New workspace path"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "New tags"},
                "complexity": {"type": "string", "enum": ["junior", "mid", "senior", ""], "description": "New complexity"},
            },
            "required": ["task_slug"],
        },
    },
    {
        "name": "archive_task",
        "description": "Archive a task (hides from default listing but preserves data)",
        "parameters": {
            "type": "object",
            "properties": {
                "task_slug": {"type": "string", "description": "Task slug to archive"},
            },
            "required": ["task_slug"],
        },
    },
    {
        "name": "list_memories",
        "description": "Browse stored memories with optional filters",
        "parameters": {
            "type": "object",
            "properties": {
                "task_slug": {"type": "string", "description": "Filter by task slug (optional)"},
                "scope": {"type": "string", "enum": ["global", "task", "session"], "description": "Filter by scope (optional)"},
                "limit": {"type": "integer", "description": "Max results (default 20)"},
            },
        },
    },
    {
        "name": "delete_memory",
        "description": "Delete a memory entry by ID",
        "parameters": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "Memory entry ID"},
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "get_usage_summary",
        "description": "Get token usage summary: recent window + all-time totals",
        "parameters": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "Hours for recent window (default 6)"},
            },
        },
    },
    {
        "name": "get_session_git_log",
        "description": "Get git log from a session's worktree to see commit history",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID"},
                "max_commits": {"type": "integer", "description": "Max commits to show (default 10)"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "list_workspaces",
        "description": "List all registered workspaces",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "send_notification",
        "description": "Send a Signal message notification to a phone number",
        "parameters": {
            "type": "object",
            "properties": {
                "recipient": {"type": "string", "description": "Phone number (e.g. +1234567890)"},
                "text": {"type": "string", "description": "Message text"},
            },
            "required": ["recipient", "text"],
        },
    },
    {
        "name": "merge_session",
        "description": "Merge a session's worktree branch into the main workspace. Use after reviewing and approving session work.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID whose branch to merge"},
            },
            "required": ["session_id"],
        },
    },
    # --- Phase 3 tools ---
    {
        "name": "check_session_liveness",
        "description": "Check if a session's process is still alive. Returns true/false.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "list_events_by_session",
        "description": "List agent events for a specific session (stalls, errors, completions, help requests)",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID to filter by"},
                "limit": {"type": "integer", "description": "Max events (default 20)"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "list_reports_by_task",
        "description": "List session reports for a task to see historical work quality",
        "parameters": {
            "type": "object",
            "properties": {
                "task_slug": {"type": "string", "description": "Task slug"},
                "limit": {"type": "integer", "description": "Max reports (default 10)"},
            },
            "required": ["task_slug"],
        },
    },
    {
        "name": "list_recent_reports",
        "description": "List most recent session reports across all tasks for a quick quality overview",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max reports (default 10)"},
            },
        },
    },
    {
        "name": "get_memory_by_key",
        "description": "Look up a memory entry by its exact key. Faster than vector search when you know the key.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Memory key"},
                "task_slug": {"type": "string", "description": "Task slug to scope lookup (optional)"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "update_memory",
        "description": "Update the content of an existing memory entry (auto re-embeds for vector search)",
        "parameters": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "Memory entry ID"},
                "content": {"type": "string", "description": "New content"},
            },
            "required": ["memory_id", "content"],
        },
    },
    {
        "name": "list_memories_by_session",
        "description": "List memories scoped to a specific session",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "get_usage_by_task",
        "description": "Get token usage breakdown for a specific task",
        "parameters": {
            "type": "object",
            "properties": {
                "task_slug": {"type": "string", "description": "Task slug"},
            },
            "required": ["task_slug"],
        },
    },
    {
        "name": "archive_session",
        "description": "Archive a session (cleans up worktree, preserves data). Different from stop — use for completed sessions.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "register_workspace",
        "description": "Register a new workspace path in the system",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute filesystem path to the workspace"},
                "name": {"type": "string", "description": "Human-friendly name (optional)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "delete_workspace",
        "description": "Remove a workspace registration (does NOT delete files, only the DB entry)",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace ID"},
            },
            "required": ["workspace_id"],
        },
    },
    {
        "name": "list_conversations",
        "description": "List all coordinator conversation histories (channels and senders)",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "clear_conversation",
        "description": "Clear conversation history for a channel/sender",
        "parameters": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel name (e.g. 'tui', 'signal')"},
                "sender_id": {"type": "string", "description": "Sender ID (optional, for Signal)"},
            },
            "required": ["channel"],
        },
    },
    {
        "name": "get_research_results",
        "description": "Get research learnings stored as task memories from a research session",
        "parameters": {
            "type": "object",
            "properties": {
                "task_slug": {"type": "string", "description": "Task slug"},
            },
            "required": ["task_slug"],
        },
    },
]

# Agent tier ordering for escalation
_AGENT_TIERS = {"opencode_local": 0, "opencode": 1, "claude_code": 2}
_TIER_ORDER = ["opencode_local", "opencode", "claude_code"]


class CoordinatorService:
    """Meta-agent with system-wide visibility and control.

    Can monitor, manage, advise, and delegate across all tasks and sessions.
    Accessible via TUI chat or Signal messenger.
    """

    def __init__(
        self,
        dashboard_service: DashboardService,
        session_service: SessionService,
        memory_service: MemoryService,
        task_service: TaskService,
        config: AppConfig,
        research_service: ResearchService | None = None,
        usage_repo: UsageRepo | None = None,
        history_repo: CoordinatorHistoryRepo | None = None,
        session_report_repo: SessionReportRepo | None = None,
        coordinator_decision_repo: CoordinatorDecisionRepo | None = None,
        conversation_summary_repo: ConversationSummaryRepo | None = None,
        agent_event_repo: AgentEventRepo | None = None,
        workspace_repo: WorkspaceRepo | None = None,
    ) -> None:
        self._dashboard = dashboard_service
        self._session = session_service
        self._memory = memory_service
        self._task = task_service
        self._config = config
        self._research = research_service
        self._usage_repo = usage_repo
        self._history_repo = history_repo
        self._session_report_repo = session_report_repo
        self._coordinator_decision_repo = coordinator_decision_repo
        self._conversation_summary_repo = conversation_summary_repo
        self._agent_event_repo = agent_event_repo
        self._workspace_repo = workspace_repo
        self._signal = None  # set via set_signal_service()
        self._provider = get_provider_with_fallback(config, config.coordinator.provider)
        self._llm_config = LLMConfig(
            model=config.coordinator.model,
            max_tokens=4096,
            temperature=0.7,
            tools=TOOL_DEFINITIONS,
        )
        self._conversations: dict[str, list[LLMMessage]] = {}
        self._watchdog_task: asyncio.Task | None = None
        self._patrol_task: asyncio.Task | None = None
        self._session_deadlines: dict[str, float] = {}  # session_id -> deadline timestamp

    # --- Late Binding ---

    def set_signal_service(self, signal_service) -> None:
        """Late-bind the signal service (avoids circular dependency)."""
        self._signal = signal_service

    # --- Watchdog ---

    def start_watchdog(
        self, check_interval: int = 120, stall_threshold: int = 600
    ) -> None:
        """Start background watchdog that monitors session health."""
        if self._watchdog_task is not None:
            return
        self._watchdog_task = asyncio.ensure_future(
            self._watchdog_loop(check_interval, stall_threshold)
        )
        logger.info("Coordinator watchdog started (interval=%ds, stall=%ds)",
                     check_interval, stall_threshold)
        # Start patrol if configured
        if self._config.coordinator.patrol_enabled and self._patrol_task is None:
            self._patrol_task = asyncio.ensure_future(self._patrol_loop())
            logger.info(
                "Coordinator patrol started (interval=%ds, autonomy=%s)",
                self._config.coordinator.patrol_interval,
                self._config.coordinator.patrol_autonomy,
            )

    def stop_watchdog(self) -> None:
        """Stop the background watchdog and patrol tasks."""
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            self._watchdog_task = None
            logger.info("Coordinator watchdog stopped")
        if self._patrol_task is not None:
            self._patrol_task.cancel()
            self._patrol_task = None
            logger.info("Coordinator patrol stopped")

    async def _watchdog_loop(
        self, check_interval: int, stall_threshold: int
    ) -> None:
        """Periodically check session health and deadlines."""
        try:
            while True:
                await asyncio.sleep(check_interval)
                try:
                    await self._check_sessions(stall_threshold)
                    await self._check_deadlines()
                except Exception:
                    logger.warning("Watchdog check failed", exc_info=True)
        except asyncio.CancelledError:
            pass

    async def _check_sessions(self, stall_threshold: int) -> None:
        """Check running sessions for dead processes and stalls."""
        sessions = await self._session.list_sessions()
        for session in sessions:
            if session.lifecycle != SessionLifecycle.RUNNING:
                continue
            try:
                is_alive = await self._session.check_session_liveness(session.id)
                if not is_alive:
                    await self._emit_event(
                        session.id, session.task_id,
                        AgentEventType.ERROR,
                        "Session process is no longer running",
                    )
                    continue

                # Check for stalls by looking at recent output
                output = await self._session.get_session_output(session.id, lines=5)
                if not output or not output.strip():
                    # No output at all — could be stalled
                    await self._emit_event(
                        session.id, session.task_id,
                        AgentEventType.STALLED,
                        f"No output detected (threshold={stall_threshold}s)",
                    )
            except Exception:
                logger.debug("Watchdog check failed for session %s", session.id, exc_info=True)

    async def _check_deadlines(self) -> None:
        """Stop sessions that have exceeded their deadline."""
        now = time.time()
        expired = [
            sid for sid, deadline in self._session_deadlines.items()
            if now >= deadline
        ]
        for sid in expired:
            self._session_deadlines.pop(sid, None)
            try:
                session = await self._session.get_session(sid)
                if session and session.lifecycle == SessionLifecycle.RUNNING:
                    await self._session.stop_session(sid)
                    await self._emit_event(
                        sid, session.task_id,
                        AgentEventType.COMPLETED,
                        "Auto-stopped: deadline expired",
                    )
                    logger.info("Watchdog auto-stopped session %s (deadline)", sid)
            except Exception:
                logger.warning("Failed to auto-stop session %s", sid, exc_info=True)

    # --- Conversation Management ---

    async def _get_conversation(self, channel: str, sender_id: str = "") -> list[LLMMessage]:
        """Get or create conversation history for a channel/sender.

        Loads from MongoDB on first access, then caches in memory.
        Sanitizes loaded history to ensure it doesn't end with orphaned
        tool messages (which would break the next API call).
        """
        key = f"{channel}:{sender_id}"
        if key not in self._conversations:
            if self._history_repo:
                try:
                    messages = await self._history_repo.load_conversation(
                        channel, sender_id
                    )
                    # Trim trailing messages that would leave the conversation
                    # in a broken state. A valid conversation must end with
                    # either a user message or an assistant message WITHOUT
                    # tool_calls. Strip orphaned tool results and incomplete
                    # tool-call sequences from the end.
                    while messages:
                        last = messages[-1]
                        if last.role == "tool":
                            messages.pop()
                        elif last.role == "assistant" and last.tool_calls:
                            messages.pop()
                        else:
                            break
                    self._conversations[key] = messages
                except Exception:
                    logger.debug("Failed to load conversation history", exc_info=True)
                    self._conversations[key] = []
            else:
                self._conversations[key] = []
        return self._conversations[key]

    async def _save_conversation(self, channel: str, sender_id: str = "") -> None:
        """Persist current conversation to MongoDB."""
        if not self._history_repo:
            return
        key = f"{channel}:{sender_id}"
        messages = self._conversations.get(key, [])
        try:
            await self._history_repo.save_conversation(channel, sender_id, messages)
        except Exception:
            logger.debug("Failed to save conversation history", exc_info=True)

    def _truncate_conversation(self, messages: list[LLMMessage], max_exchanges: int = 20) -> list[LLMMessage]:
        """Truncate conversation to keep only the last N user/assistant exchanges.

        Preserves conversation context while preventing unbounded growth.
        Cuts only at safe boundaries (before a user message) to ensure tool
        call sequences are never split -- every assistant(tool_calls) message
        is always followed by its corresponding tool result messages.
        """
        if len(messages) <= max_exchanges * 3:
            return messages

        # Find safe cut points: indices where a user message starts a new exchange.
        # A safe cut point is any index i where messages[i].role == "user" AND
        # messages[i-1].role is NOT "tool" (i.e., the previous exchange is complete).
        # The first message (i=0) is always a safe start if it's a user message.
        safe_cuts: list[int] = []
        for i, msg in enumerate(messages):
            if msg.role != "user":
                continue
            # Safe if first message, or previous message is not a tool result
            if i == 0 or messages[i - 1].role != "tool":
                safe_cuts.append(i)

        if not safe_cuts:
            # No safe cuts found — hard fallback: keep last N messages to prevent
            # unbounded growth. This may split a tool-call sequence, but is safer
            # than keeping an arbitrarily large conversation.
            hard_max = max_exchanges * 3
            if len(messages) > hard_max:
                logger.warning(
                    "No safe truncation point found; hard-cutting to last %d messages",
                    hard_max,
                )
                return messages[-hard_max:]
            return messages

        # Count exchanges backward from the end to find the right cut point
        # Each safe cut corresponds to the start of an exchange
        if len(safe_cuts) <= max_exchanges:
            return messages

        cut_index = safe_cuts[-max_exchanges]

        truncated = messages[cut_index:]
        logger.debug(
            "Truncated conversation from %d to %d messages (cut at index %d)",
            len(messages), len(truncated), cut_index,
        )
        return truncated

    # --- Conversation Summarization ---

    async def _maybe_summarize(
        self, key: str, conversation: list[LLMMessage]
    ) -> None:
        """Summarize older messages if truncation would drop >10 messages."""
        if not self._conversation_summary_repo:
            return

        max_keep = 20 * 3  # max_exchanges * ~3 msgs per exchange
        if len(conversation) <= max_keep + 10:
            return

        # Count messages that would be dropped
        drop_count = len(conversation) - max_keep
        if drop_count <= 10:
            return

        # Extract the messages that will be dropped for summarization
        to_summarize = conversation[:drop_count]
        summary_text_parts = []
        for msg in to_summarize:
            if msg.role == "user":
                summary_text_parts.append(f"User: {msg.content[:200]}")
            elif msg.role == "assistant" and msg.content:
                summary_text_parts.append(f"Assistant: {msg.content[:200]}")

        if not summary_text_parts:
            return

        summary_input = "\n".join(summary_text_parts[-30:])  # Last 30 entries max

        try:
            summary_config = LLMConfig(
                model=self._llm_config.model,
                max_tokens=500,
                temperature=0.3,
            )
            response = await self._provider.complete(
                [
                    LLMMessage(role="system", content="Summarize this conversation concisely. Focus on key decisions, tasks discussed, and current state. Be brief."),
                    LLMMessage(role="user", content=summary_input),
                ],
                summary_config,
            )

            # Find and supersede any existing active summary
            existing = await self._conversation_summary_repo.find_active(key)

            new_summary = await self._conversation_summary_repo.insert(
                ConversationSummary(
                    conversation_key=key,
                    summary=response.content,
                    exchanges_summarized=drop_count,
                )
            )

            if existing and existing.id and new_summary.id:
                await self._conversation_summary_repo.supersede(
                    existing.id, new_summary.id
                )

            logger.debug("Created conversation summary for %s (%d messages summarized)",
                         key, drop_count)
        except Exception:
            logger.debug("Failed to create conversation summary", exc_info=True)

    # --- Main Message Handler ---

    async def handle_message(
        self,
        user_message: str,
        channel: str = "tui",
        sender_id: str = "",
        on_progress: Callable[[str], None] | None = None,
    ) -> str:
        """Process a message from user (TUI or Signal). Returns response text.

        Args:
            on_progress: Optional callback for live progress updates. Called with
                display strings like "Using tool: list_tasks..." and intermediate
                coordinator text.
        """
        conversation = await self._get_conversation(channel, sender_id)
        key = f"{channel}:{sender_id}"

        # Summarize before truncation if needed
        await self._maybe_summarize(key, conversation)

        # Fetch context for enhanced system prompt
        summary = None
        unacked_events: list[AgentEvent] = []
        recent_reports: list[SessionReport] = []
        if self._conversation_summary_repo:
            try:
                summary = await self._conversation_summary_repo.find_active(key)
            except Exception:
                pass
        if self._agent_event_repo:
            try:
                unacked_events = await self._agent_event_repo.list_unacknowledged(limit=10)
            except Exception:
                pass
        if self._session_report_repo:
            try:
                recent_reports = await self._session_report_repo.list_recent(limit=5)
            except Exception:
                pass

        # Build system prompt with live system state
        snapshot = await self._dashboard.load_snapshot()
        system_prompt = self._build_system_prompt(
            snapshot,
            summary=summary,
            unacked_events=unacked_events,
            recent_reports=recent_reports,
        )

        # Add user message to history
        conversation.append(LLMMessage(role="user", content=user_message))

        # Truncate conversation to prevent unbounded growth
        truncated_conversation = self._truncate_conversation(conversation)

        # Build full message list
        messages = [
            LLMMessage(role="system", content=system_prompt),
            *truncated_conversation,
        ]

        # Decision logging accumulator
        tool_records: list[ToolCallRecord] = []
        total_tokens: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

        # LLM completion with tool use
        max_tool_rounds = 10
        response = None
        for _ in range(max_tool_rounds):
            response = await self._provider.complete(messages, self._llm_config)

            # Track token usage
            round_input = response.usage.get("input_tokens", 0)
            round_output = response.usage.get("output_tokens", 0)
            total_tokens["input_tokens"] += round_input
            total_tokens["output_tokens"] += round_output

            if self._usage_repo:
                try:
                    await self._usage_repo.insert(UsageEvent(
                        source="coordinator",
                        model=response.model or self._llm_config.model,
                        input_tokens=round_input,
                        output_tokens=round_output,
                        channel=channel,
                        timestamp=datetime.now(timezone.utc),
                    ))
                except Exception:
                    logger.warning("Failed to log coordinator usage", exc_info=True)

            # Budget guard: warn if coordinator is over-planning
            if round_output > 2000:
                logger.warning(
                    "Coordinator decomposition used %d output tokens — may be over-planning",
                    round_output,
                )

            if not response.has_tool_calls:
                # Final response
                conversation.append(
                    LLMMessage(role="assistant", content=response.content)
                )
                await self._save_conversation(channel, sender_id)

                # Log decision
                await self._log_decision(
                    key, user_message, tool_records,
                    response.content, total_tokens,
                    response.model or self._llm_config.model,
                )
                return response.content

            # Show intermediate text if the coordinator said something alongside tool calls
            if response.content and on_progress:
                on_progress(response.content)

            # Execute tool calls
            assistant_msg = LLMMessage(
                role="assistant",
                content=response.content,
                tool_calls=[
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in response.tool_calls
                ],
            )
            conversation.append(assistant_msg)
            messages.append(assistant_msg)

            # Execute tool calls in parallel with retry
            if on_progress:
                for tc in response.tool_calls:
                    on_progress(f"[tool] {tc.name}")

            tool_tasks = [
                self._timed_execute_tool(tc.name, tc.arguments)
                for tc in response.tool_calls
            ]
            timed_results = await asyncio.gather(*tool_tasks)

            # Build tool response messages and accumulate records
            for tc, (result, duration_ms) in zip(response.tool_calls, timed_results):
                result_str = json.dumps(result, default=str)
                tool_records.append(ToolCallRecord(
                    name=tc.name,
                    arguments=tc.arguments,
                    result_summary=result_str[:500],
                    duration_ms=duration_ms,
                ))
                tool_msg = LLMMessage(
                    role="tool",
                    content=result_str,
                    tool_call_id=tc.id,
                    name=tc.name,
                )
                conversation.append(tool_msg)
                messages.append(tool_msg)

        # Loop exhausted without a final non-tool response.
        # Add a synthetic assistant message so the conversation doesn't end
        # with orphaned tool results (which would break the next API call).
        fallback_text = response.content if response else "I couldn't complete the request."
        conversation.append(LLMMessage(role="assistant", content=fallback_text))
        await self._save_conversation(channel, sender_id)

        await self._log_decision(
            key, user_message, tool_records,
            fallback_text, total_tokens,
            (response.model if response else None) or self._llm_config.model,
        )
        return fallback_text

    # --- Enhanced System Prompt ---

    def _build_system_prompt(
        self,
        snapshot,
        summary: ConversationSummary | None = None,
        unacked_events: list[AgentEvent] | None = None,
        recent_reports: list[SessionReport] | None = None,
    ) -> str:
        """Build system prompt with live system state and contextual data."""
        state_summary = snapshot.summary_text()

        extra_sections = []

        if summary:
            extra_sections.append(
                f"Previous Conversation Summary:\n{summary.summary}"
            )

        if unacked_events:
            event_lines = []
            for ev in unacked_events:
                event_lines.append(
                    f"  - [{ev.event_type.value}] session={ev.session_id[:8]}... {ev.detail[:100]}"
                )
            extra_sections.append(
                "Unacknowledged Agent Events:\n" + "\n".join(event_lines)
            )

        if recent_reports:
            report_lines = []
            for rpt in recent_reports:
                status_icon = {"success": "OK", "partial": "PARTIAL", "failed": "FAIL"}.get(rpt.status, "?")
                report_lines.append(
                    f"  - [{status_icon}] session={rpt.session_id[:8]}... agent={rpt.agent} — {rpt.summary[:80]}"
                )
            extra_sections.append(
                "Recent Session Reports:\n" + "\n".join(report_lines)
            )

        extra_text = ""
        if extra_sections:
            extra_text = "\n\n" + "\n\n".join(extra_sections)

        return f"""You are the agentbench coordinator - a meta-agent with full visibility and control over all tasks, sessions, and agents in the system.

You can:
- Monitor: See all tasks, sessions, their statuses, recent outputs, git logs, and errors
- Manage: Start/stop/pause/resume sessions, create/update/archive tasks, set deadlines
- Advise: Answer questions about what agents are doing, summarize progress, show usage
- Delegate: Route user requests to the appropriate agent or action
- Remember: Access the full memory system — search, list, store, and delete memories
- Review: Generate structured session reports with diff stats, test results, and summaries
- React: Check and acknowledge agent events (stalls, errors, help requests)
- Decompose: Break high-level goals into subtasks, create them, assign agents, monitor
- Merge: Merge completed session work back into the main workspace
- Notify: Send Signal messages to alert the user about important events

Agent Tiers (use these when starting coding sessions):
- claude_code: Senior engineer. Use for architecture, complex refactors, multi-file changes,
  tasks requiring deep reasoning or subtle judgment. Highest capability, highest cost.
- opencode: Mid-level engineer (Kimi2.5). Use for well-scoped implementation tasks with clear
  requirements — adding endpoints, implementing features from specs, moderate refactors.
- opencode_local: Junior engineer (local llama.cpp). Use for simple, well-defined work — boilerplate,
  renaming, formatting, straightforward tests, small bug fixes with obvious solutions.

When starting sessions, always choose the lowest tier capable of handling the work.
When decomposing tasks, classify briefly and assign — do not design the solution yourself.
Keep decomposition responses short (under 500 words). If a task can't be quickly classified,
send it to claude_code.

Goal Decomposition:
When given a high-level goal, break it into concrete subtasks with create_task (set workspace_path!),
then start sessions for each. Monitor progress, review completed work, merge successful branches.

Review Policy:
- After an opencode_local (junior) session completes, review its work using review_session
  to get a structured report. This runs tests and generates a summary automatically.
- If the review shows status="failed" and the agent was junior/mid, the system will
  automatically escalate to a higher-tier agent. You'll see the escalation in the result.
- For opencode sessions, review is optional but recommended for complex changes.
- For claude_code sessions, trust the output — review only if the user asks.

Proactive Monitoring:
- Check list_agent_events periodically for stalls, errors, or help requests.
- Acknowledge events after handling them to keep the queue clean.
- Use set_session_deadline to prevent runaway sessions.

Current System State:
{state_summary}{extra_text}

Use the available tools to inspect and manage the system. Be helpful, concise, and proactive about suggesting actions when appropriate."""

    # --- Tool Execution ---

    async def _timed_execute_tool(
        self, name: str, arguments: dict
    ) -> tuple[Any, int]:
        """Execute a tool with timing. Returns (result, duration_ms)."""
        start = time.monotonic()
        result = await self._execute_tool_with_retry(name, arguments)
        duration_ms = int((time.monotonic() - start) * 1000)
        return result, duration_ms

    async def _execute_tool_with_retry(
        self, name: str, arguments: dict, max_retries: int = 2
    ) -> Any:
        """Execute a tool with retry on transient errors."""
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                return await self._execute_tool(name, arguments)
            except (TimeoutError, ConnectionError, OSError) as e:
                last_error = e
                if attempt < max_retries:
                    await asyncio.sleep(1 * (attempt + 1))  # Simple backoff
                    logger.debug("Retrying tool %s (attempt %d): %s", name, attempt + 1, e)
        return {"error": f"Tool failed after {max_retries + 1} attempts: {last_error}"}

    async def _execute_tool(self, name: str, arguments: dict) -> Any:
        """Execute a coordinator tool call."""
        try:
            if name == "list_tasks":
                tasks = await self._task.list_tasks(
                    show_all=arguments.get("show_all", False)
                )
                return [
                    {
                        "slug": t.slug,
                        "title": t.title,
                        "status": t.status.value,
                        "description": t.description[:100] if t.description else "",
                        "workspace_path": t.workspace_path,
                        "tags": list(t.tags),
                        "complexity": t.complexity,
                    }
                    for t in tasks
                ]

            elif name == "list_sessions":
                task_slug = arguments.get("task_slug", "")
                task_id = ""
                if task_slug:
                    task = await self._task.get_task(task_slug)
                    task_id = task.id if task else ""
                sessions = await self._session.list_sessions(task_id=task_id)
                return [
                    {
                        "id": s.id,
                        "display_name": s.display_name,
                        "kind": s.kind.value,
                        "lifecycle": s.lifecycle.value,
                        "task_id": s.task_id,
                        "agent_backend": s.agent_backend,
                        "worktree_path": s.worktree_path,
                        "created_at": s.created_at.isoformat(),
                        "updated_at": s.updated_at.isoformat(),
                    }
                    for s in sessions
                ]

            elif name == "start_coding_session":
                task = await self._task.get_task(arguments["task_slug"])
                if not task:
                    return {"error": f"Task not found: {arguments['task_slug']}"}
                session = await self._session.start_coding_session(
                    task_id=task.id,
                    agent_type=arguments.get("agent", ""),
                    prompt=arguments.get("prompt", ""),
                    workspace_path=task.workspace_path,
                    task_tags=task.tags,
                    task_complexity=task.complexity,
                )
                # Emit STARTED event
                await self._emit_event(
                    session.id, task.id,
                    AgentEventType.STARTED,
                    f"Agent {session.agent_backend} started",
                )
                return {"session_id": session.id, "status": session.lifecycle.value}

            elif name == "stop_session":
                session = await self._session.get_session(arguments["session_id"])
                stopped = await self._session.stop_session(arguments["session_id"])
                # Auto-generate basic report on stop
                if stopped and session:
                    await self._auto_report_on_stop(session)
                    await self._emit_event(
                        session.id, session.task_id,
                        AgentEventType.COMPLETED,
                        "Session stopped",
                    )
                return {"stopped": stopped is not None}

            elif name == "get_session_output":
                output = await self._session.get_session_output(
                    arguments["session_id"],
                    lines=arguments.get("lines", 50),
                )
                return {"output": output}

            elif name == "search_memory":
                task_id = ""
                if task_slug := arguments.get("task_slug"):
                    task = await self._task.get_task(task_slug)
                    task_id = task.id if task else ""
                query = MemoryQuery(
                    query_text=arguments["query"],
                    task_id=task_id,
                    limit=arguments.get("limit", 10),
                )
                results = await self._memory.search(query)
                return [
                    {"key": m.key, "content": m.content[:500], "scope": m.scope.value, "id": m.id}
                    for m in results
                ]

            elif name == "store_memory":
                task_id = ""
                scope = MemoryScope.GLOBAL
                if task_slug := arguments.get("task_slug"):
                    task = await self._task.get_task(task_slug)
                    if task:
                        task_id = task.id
                        scope = MemoryScope.TASK
                session_id = arguments.get("session_id", "")
                if session_id:
                    scope = MemoryScope.SESSION
                entry = await self._memory.store(
                    key=arguments["key"],
                    content=arguments["content"],
                    scope=scope,
                    task_id=task_id,
                    session_id=session_id,
                    content_type=arguments.get("content_type", "text"),
                    metadata=arguments.get("metadata"),
                )
                return {"stored": True, "id": entry.id}

            elif name == "create_task":
                task = await self._task.create_task(
                    title=arguments["title"],
                    description=arguments.get("description", ""),
                    workspace_path=arguments.get("workspace_path", ""),
                    tags=tuple(arguments.get("tags", [])),
                    complexity=arguments.get("complexity", ""),
                )
                return {"slug": task.slug, "id": task.id}

            elif name == "delete_task":
                task = await self._task.delete_task(arguments["task_slug"])
                if not task:
                    return {"error": f"Task not found: {arguments['task_slug']}"}
                return {"deleted": True, "slug": task.slug}

            elif name == "start_research":
                task = await self._task.get_task(arguments["task_slug"])
                if not task:
                    return {"error": f"Task not found: {arguments['task_slug']}"}
                if not self._research:
                    return {"error": "Research service not available"}

                research_config = ResearchConfig(
                    query=arguments["query"],
                    breadth=arguments.get("breadth", 4),
                    depth=arguments.get("depth", 3),
                    provider=self._config.research.default_provider,
                    search_provider=self._config.research.default_search,
                )
                session = await self._research.start_research(
                    task_id=task.id,
                    research_config=research_config,
                )
                return {
                    "started": True,
                    "session_id": session.id,
                    "query": arguments["query"],
                }

            elif name == "get_research_status":
                session = await self._session.get_session(arguments["session_id"])
                if not session:
                    return {"error": "Session not found"}
                rp = session.research_progress
                return {
                    "lifecycle": session.lifecycle.value,
                    "progress": rp.to_doc() if rp else None,
                }

            elif name == "send_to_session":
                success = await self._session.send_to_session(
                    arguments["session_id"], arguments["text"]
                )
                return {"sent": success}

            elif name == "get_session_diff":
                try:
                    diff = await self._session.get_session_diff(
                        arguments["session_id"]
                    )
                except Exception:
                    # Fallback to git status if diff fails
                    diff = await self._session.run_in_worktree(
                        arguments["session_id"], "git status --short"
                    )
                return {"diff": diff or "(no changes)"}

            elif name == "run_in_worktree":
                output = await self._session.run_in_worktree(
                    arguments["session_id"], arguments["command"]
                )
                return {"output": output}

            # --- New tool handlers ---

            elif name == "review_session":
                return await self._handle_review_session(arguments)

            elif name == "pause_session":
                session = await self._session.pause_session(arguments["session_id"])
                return {"paused": session is not None}

            elif name == "resume_session":
                session = await self._session.resume_session(arguments["session_id"])
                return {"resumed": session is not None}

            elif name == "get_session_report":
                if not self._session_report_repo:
                    return {"error": "Session report repo not available"}
                report = await self._session_report_repo.find_by_session(
                    arguments["session_id"]
                )
                if not report:
                    return {"error": "No report found for this session"}
                return {
                    "session_id": report.session_id,
                    "status": report.status,
                    "summary": report.summary,
                    "files_changed": list(report.files_changed),
                    "test_results": report.test_results.to_doc() if report.test_results else None,
                    "diff_stats": report.diff_stats.to_doc() if report.diff_stats else None,
                    "agent_notes": report.agent_notes,
                }

            elif name == "list_agent_events":
                if not self._agent_event_repo:
                    return {"error": "Agent event repo not available"}
                events = await self._agent_event_repo.list_unacknowledged(
                    event_types=arguments.get("event_types"),
                    limit=arguments.get("limit", 20),
                )
                return [
                    {
                        "id": e.id,
                        "session_id": e.session_id,
                        "event_type": e.event_type.value,
                        "detail": e.detail,
                        "created_at": e.created_at.isoformat(),
                    }
                    for e in events
                ]

            elif name == "acknowledge_events":
                if not self._agent_event_repo:
                    return {"error": "Agent event repo not available"}
                count = await self._agent_event_repo.acknowledge(
                    arguments["event_ids"]
                )
                return {"acknowledged": count}

            elif name == "set_session_deadline":
                sid = arguments["session_id"]
                minutes = arguments["minutes"]
                self._session_deadlines[sid] = time.time() + (minutes * 60)
                return {"deadline_set": True, "session_id": sid, "minutes": minutes}

            # --- Phase 2 tool handlers ---

            elif name == "get_task_detail":
                task = await self._task.get_task(arguments["task_slug"])
                if not task:
                    return {"error": f"Task not found: {arguments['task_slug']}"}
                return {
                    "slug": task.slug,
                    "title": task.title,
                    "status": task.status.value,
                    "description": task.description,
                    "workspace_path": task.workspace_path,
                    "tags": list(task.tags),
                    "complexity": task.complexity,
                    "created_at": task.created_at.isoformat(),
                    "updated_at": task.updated_at.isoformat(),
                    "id": task.id,
                }

            elif name == "update_task":
                task = await self._task.update_task(
                    slug=arguments["task_slug"],
                    description=arguments.get("description"),
                    workspace_path=arguments.get("workspace_path"),
                    tags=tuple(arguments["tags"]) if "tags" in arguments else None,
                    complexity=arguments.get("complexity"),
                )
                if not task:
                    return {"error": f"Task not found: {arguments['task_slug']}"}
                return {"updated": True, "slug": task.slug}

            elif name == "archive_task":
                task = await self._task.archive_task(arguments["task_slug"])
                if not task:
                    return {"error": f"Task not found: {arguments['task_slug']}"}
                return {"archived": True, "slug": task.slug}

            elif name == "list_memories":
                task_id = ""
                if task_slug := arguments.get("task_slug"):
                    task = await self._task.get_task(task_slug)
                    task_id = task.id if task else ""
                scope = MemoryScope(arguments["scope"]) if arguments.get("scope") else None
                memories = await self._memory.list_memories(
                    task_id=task_id, scope=scope,
                )
                limit = arguments.get("limit", 20)
                return [
                    {
                        "id": m.id,
                        "key": m.key,
                        "content": m.content[:500],
                        "scope": m.scope.value,
                        "task_id": m.task_id,
                        "created_at": m.created_at.isoformat(),
                    }
                    for m in memories[:limit]
                ]

            elif name == "delete_memory":
                deleted = await self._memory.delete_memory(arguments["memory_id"])
                return {"deleted": deleted}

            elif name == "get_usage_summary":
                if not self._usage_repo:
                    return {"error": "Usage tracking not available"}
                hours = arguments.get("hours", 6)
                recent = await self._usage_repo.aggregate_recent(hours=hours)
                totals = await self._usage_repo.aggregate_totals()
                return {"recent": recent, "totals": totals, "recent_hours": hours}

            elif name == "get_session_git_log":
                session = await self._session.get_session(arguments["session_id"])
                if not session:
                    return {"error": "Session not found"}
                if not session.worktree_path:
                    return {"error": "Session has no worktree"}
                log = await git_ops.get_log(
                    session.worktree_path,
                    max_commits=arguments.get("max_commits", 10),
                )
                return {"log": log}

            elif name == "list_workspaces":
                if not self._workspace_repo:
                    return {"error": "Workspace repo not available"}
                workspaces = await self._workspace_repo.list_all()
                return [
                    {"id": ws.id, "path": ws.path, "name": ws.name}
                    for ws in workspaces
                ]

            elif name == "send_notification":
                if not self._signal:
                    return {"error": "Signal service not available"}
                sent = await self._signal.send_notification(
                    arguments["recipient"], arguments["text"],
                )
                return {"sent": sent}

            elif name == "merge_session":
                session = await self._session.get_session(arguments["session_id"])
                if not session:
                    return {"error": "Session not found"}
                if not session.worktree_path:
                    return {"error": "Session has no worktree"}
                # Find the task to get the main workspace path
                task = await self._task.get_task_by_id(session.task_id)
                if not task or not task.workspace_path:
                    return {"error": "Task has no workspace_path — cannot determine merge target"}
                # Get the branch name from the worktree
                branch_proc = await asyncio.create_subprocess_exec(
                    "git", "rev-parse", "--abbrev-ref", "HEAD",
                    cwd=session.worktree_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await branch_proc.communicate()
                branch_name = stdout.decode().strip()
                if not branch_name:
                    return {"error": "Could not determine session branch name"}
                result = await git_ops.merge_branch(task.workspace_path, branch_name)
                return {"merged": True, "branch": branch_name, "output": result}

            # --- Phase 3 tool handlers ---

            elif name == "check_session_liveness":
                alive = await self._session.check_session_liveness(
                    arguments["session_id"]
                )
                return {"alive": alive, "session_id": arguments["session_id"]}

            elif name == "list_events_by_session":
                if not self._agent_event_repo:
                    return {"error": "Agent event repo not available"}
                events = await self._agent_event_repo.list_by_session(
                    session_id=arguments["session_id"],
                    limit=arguments.get("limit", 20),
                )
                return [
                    {
                        "id": e.id,
                        "session_id": e.session_id,
                        "event_type": e.event_type.value,
                        "detail": e.detail,
                        "acknowledged": e.acknowledged,
                        "created_at": e.created_at.isoformat(),
                    }
                    for e in events
                ]

            elif name == "list_reports_by_task":
                if not self._session_report_repo:
                    return {"error": "Session report repo not available"}
                task = await self._task.get_task(arguments["task_slug"])
                if not task:
                    return {"error": f"Task not found: {arguments['task_slug']}"}
                reports = await self._session_report_repo.list_by_task(
                    task_id=task.id,
                    limit=arguments.get("limit", 10),
                )
                return [
                    {
                        "session_id": r.session_id,
                        "agent": r.agent,
                        "status": r.status,
                        "summary": r.summary[:200],
                        "files_changed": list(r.files_changed),
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in reports
                ]

            elif name == "list_recent_reports":
                if not self._session_report_repo:
                    return {"error": "Session report repo not available"}
                reports = await self._session_report_repo.list_recent(
                    limit=arguments.get("limit", 10),
                )
                return [
                    {
                        "session_id": r.session_id,
                        "task_id": r.task_id,
                        "agent": r.agent,
                        "status": r.status,
                        "summary": r.summary[:200],
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in reports
                ]

            elif name == "get_memory_by_key":
                task_id = ""
                if task_slug := arguments.get("task_slug"):
                    task = await self._task.get_task(task_slug)
                    task_id = task.id if task else ""
                entry = await self._memory.find_by_key(
                    arguments["key"], task_id=task_id,
                )
                if not entry:
                    return {"error": f"No memory found with key: {arguments['key']}"}
                return {
                    "id": entry.id,
                    "key": entry.key,
                    "content": entry.content,
                    "scope": entry.scope.value,
                    "task_id": entry.task_id,
                    "session_id": entry.session_id,
                    "content_type": entry.content_type,
                    "created_at": entry.created_at.isoformat(),
                }

            elif name == "update_memory":
                updated = await self._memory.update_memory(
                    arguments["memory_id"], arguments["content"],
                )
                if not updated:
                    return {"error": f"Memory not found: {arguments['memory_id']}"}
                return {"updated": True, "id": updated.id}

            elif name == "list_memories_by_session":
                memories = await self._memory.list_by_session(
                    arguments["session_id"],
                )
                return [
                    {
                        "id": m.id,
                        "key": m.key,
                        "content": m.content[:500],
                        "scope": m.scope.value,
                        "created_at": m.created_at.isoformat(),
                    }
                    for m in memories
                ]

            elif name == "get_usage_by_task":
                if not self._usage_repo:
                    return {"error": "Usage tracking not available"}
                task = await self._task.get_task(arguments["task_slug"])
                if not task:
                    return {"error": f"Task not found: {arguments['task_slug']}"}
                result = await self._usage_repo.aggregate_by_task(task.id)
                return result

            elif name == "archive_session":
                session = await self._session.archive_session(
                    arguments["session_id"]
                )
                if not session:
                    return {"error": "Session not found"}
                return {"archived": True, "session_id": session.id}

            elif name == "register_workspace":
                if not self._workspace_repo:
                    return {"error": "Workspace repo not available"}
                from agentbenchplatform.models.workspace import Workspace
                ws = await self._workspace_repo.insert(Workspace(
                    path=arguments["path"],
                    name=arguments.get("name", ""),
                ))
                return {"registered": True, "id": ws.id, "path": ws.path}

            elif name == "delete_workspace":
                if not self._workspace_repo:
                    return {"error": "Workspace repo not available"}
                deleted = await self._workspace_repo.delete(arguments["workspace_id"])
                return {"deleted": deleted}

            elif name == "list_conversations":
                if not self._history_repo:
                    return {"error": "History repo not available"}
                convos = await self._history_repo.list_conversations()
                for c in convos:
                    if "updated_at" in c and c["updated_at"] is not None:
                        c["updated_at"] = c["updated_at"].isoformat()
                return convos

            elif name == "clear_conversation":
                if not self._history_repo:
                    return {"error": "History repo not available"}
                cleared = await self._history_repo.clear_conversation(
                    arguments["channel"],
                    arguments.get("sender_id", ""),
                )
                # Also clear in-memory cache
                key = f"{arguments['channel']}:{arguments.get('sender_id', '')}"
                self._conversations.pop(key, None)
                return {"cleared": cleared}

            elif name == "get_research_results":
                if not self._research:
                    return {"error": "Research service not available"}
                task = await self._task.get_task(arguments["task_slug"])
                if not task:
                    return {"error": f"Task not found: {arguments['task_slug']}"}
                results = await self._research.get_research_results(task.id)
                return [
                    {
                        "key": m.key,
                        "content": m.content[:500],
                        "created_at": m.created_at.isoformat(),
                    }
                    for m in results
                ]

            else:
                return {"error": f"Unknown tool: {name}"}

        except KeyError as e:
            logger.warning("Tool %s missing required argument: %s", name, e)
            return {"error": f"Missing required argument: {e}"}
        except ValueError as e:
            logger.warning("Tool %s received invalid argument: %s", name, e)
            return {"error": f"Invalid argument: {e}"}
        except Exception as e:
            logger.exception("Tool %s execution failed unexpectedly", name)
            return {"error": f"Tool execution failed: {str(e)}"}

    # --- Review Session Handler ---

    async def _handle_review_session(self, arguments: dict) -> dict:
        """Generate a comprehensive session review with diff, tests, and AI summary."""
        session_id = arguments["session_id"]
        session = await self._session.get_session(session_id)
        if not session:
            return {"error": "Session not found"}

        # 1. Get diff and parse stats
        try:
            diff = await self._session.get_session_diff(session_id)
        except Exception:
            diff = ""
        diff_stats = self._parse_diff_stats(diff or "")
        files_changed = self._parse_files_from_diff(diff or "")

        # 2. Run tests if command provided
        test_results = None
        test_output = ""
        if test_cmd := arguments.get("test_command"):
            try:
                test_output = await self._session.run_in_worktree(session_id, test_cmd)
                test_results = self._parse_test_results(test_output)
            except Exception as e:
                test_output = str(e)
                test_results = TestResults(errors=1, output_snippet=test_output[:500])

        # 3. Run lint if command provided
        lint_output = ""
        if lint_cmd := arguments.get("lint_command"):
            try:
                lint_output = await self._session.run_in_worktree(session_id, lint_cmd)
            except Exception as e:
                lint_output = str(e)

        # 4. Generate AI summary
        summary = ""
        try:
            summary_input = f"Diff stats: {diff_stats.insertions}+ {diff_stats.deletions}- across {diff_stats.files} files"
            if test_results:
                summary_input += f"\nTests: {test_results.passed} passed, {test_results.failed} failed, {test_results.errors} errors"
            if lint_output:
                summary_input += f"\nLint output: {lint_output[:300]}"
            if diff:
                summary_input += f"\nDiff preview:\n{diff[:1000]}"

            summary_config = LLMConfig(
                model=self._llm_config.model,
                max_tokens=200,
                temperature=0.3,
            )
            resp = await self._provider.complete(
                [
                    LLMMessage(role="system", content="Summarize this session's work in 2 sentences. Focus on what was changed and whether it looks correct."),
                    LLMMessage(role="user", content=summary_input),
                ],
                summary_config,
            )
            summary = resp.content
        except Exception:
            summary = f"Changed {diff_stats.files} files ({diff_stats.insertions}+ {diff_stats.deletions}-)"

        # 5. Determine status
        if test_results and test_results.failed > 0:
            status = "failed"
        elif test_results and test_results.errors > 0:
            status = "failed"
        elif diff_stats.files == 0:
            status = "partial"
        else:
            status = "success"

        # 6. Store report
        report = SessionReport(
            session_id=session_id,
            task_id=session.task_id,
            agent=session.agent_backend,
            status=status,
            summary=summary,
            files_changed=files_changed,
            test_results=test_results,
            diff_stats=diff_stats,
            agent_notes=lint_output[:500] if lint_output else "",
        )
        if self._session_report_repo:
            try:
                report = await self._session_report_repo.insert(report)
            except Exception:
                logger.warning("Failed to store session report", exc_info=True)

        result: dict[str, Any] = {
            "session_id": session_id,
            "status": status,
            "summary": summary,
            "files_changed": list(files_changed),
            "diff_stats": diff_stats.to_doc(),
        }
        if test_results:
            result["test_results"] = test_results.to_doc()

        # 7. Auto-escalation if failed and agent is junior/mid
        if status == "failed" and session.agent_backend in ("opencode_local", "opencode"):
            escalation = await self._auto_escalate(session, summary)
            if escalation:
                result["escalation"] = escalation

        return result

    async def _auto_escalate(self, session, failure_summary: str) -> dict | None:
        """Auto-start a higher-tier session when a lower tier fails."""
        current_tier = _AGENT_TIERS.get(session.agent_backend, 0)
        if current_tier >= 2:  # Already at highest tier
            return None

        next_agent = _TIER_ORDER[current_tier + 1]

        # Emit needs_help event
        await self._emit_event(
            session.id, session.task_id,
            AgentEventType.NEEDS_HELP,
            f"Auto-escalating from {session.agent_backend} to {next_agent}: {failure_summary[:200]}",
        )

        # Start escalated session
        try:
            task = await self._task.get_task_by_id(session.task_id)
            if not task:
                return None
            escalated = await self._session.start_coding_session(
                task_id=task.id,
                agent_type=next_agent,
                prompt=f"Previous {session.agent_backend} session failed. Issue: {failure_summary}\nPlease fix the problems and complete the task.",
                workspace_path=task.workspace_path,
                task_tags=task.tags,
                task_complexity=task.complexity,
            )
            await self._emit_event(
                escalated.id, task.id,
                AgentEventType.STARTED,
                f"Escalated from {session.agent_backend}: {next_agent} started",
            )
            return {
                "escalated_to": next_agent,
                "new_session_id": escalated.id,
                "reason": failure_summary[:200],
            }
        except Exception:
            logger.warning("Auto-escalation failed", exc_info=True)
            return None

    # --- Auto Report on Stop ---

    async def _auto_report_on_stop(self, session) -> None:
        """Generate a basic report when a session is stopped (diff only, no LLM)."""
        if not self._session_report_repo:
            return
        try:
            # Check if report already exists
            existing = await self._session_report_repo.find_by_session(session.id)
            if existing:
                return

            diff = ""
            try:
                diff = await self._session.get_session_diff(session.id)
            except Exception:
                pass
            diff_stats = self._parse_diff_stats(diff or "")
            files_changed = self._parse_files_from_diff(diff or "")

            report = SessionReport(
                session_id=session.id,
                task_id=session.task_id,
                agent=session.agent_backend,
                status="partial" if diff_stats.files == 0 else "success",
                summary=f"Session stopped. {diff_stats.files} files changed ({diff_stats.insertions}+ {diff_stats.deletions}-).",
                files_changed=files_changed,
                diff_stats=diff_stats,
            )
            await self._session_report_repo.insert(report)
        except Exception:
            logger.debug("Failed to auto-generate report on stop", exc_info=True)

    # --- Decision Logging ---

    async def _log_decision(
        self,
        key: str,
        user_input: str,
        tool_records: list[ToolCallRecord],
        final_response: str,
        tokens: dict,
        model: str,
    ) -> None:
        """Log a coordinator decision to MongoDB."""
        if not self._coordinator_decision_repo:
            return
        try:
            # Count existing decisions for turn number
            existing = await self._coordinator_decision_repo.list_by_conversation(key, limit=1)
            turn_number = (existing[0].turn_number + 1) if existing else 1

            await self._coordinator_decision_repo.insert(
                CoordinatorDecision(
                    conversation_key=key,
                    turn_number=turn_number,
                    user_input=user_input[:500],
                    tools_called=tuple(tool_records),
                    reasoning_excerpt=final_response[:300],
                    final_response=final_response[:2000],
                    tokens=tokens,
                    model=model,
                )
            )
        except Exception:
            logger.debug("Failed to log coordinator decision", exc_info=True)

    # --- Event Helpers ---

    async def _emit_event(
        self,
        session_id: str,
        task_id: str,
        event_type: AgentEventType,
        detail: str,
    ) -> None:
        """Emit an agent event to MongoDB."""
        if not self._agent_event_repo:
            return
        try:
            await self._agent_event_repo.insert(
                AgentEvent(
                    session_id=session_id,
                    task_id=task_id,
                    event_type=event_type,
                    detail=detail,
                )
            )
        except Exception:
            logger.debug("Failed to emit agent event", exc_info=True)

    # --- Parsing Helpers ---

    @staticmethod
    def _parse_diff_stats(diff: str) -> DiffStats:
        """Parse insertions/deletions/files from a git diff."""
        insertions = 0
        deletions = 0
        files = set()

        for line in diff.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                # Extract filename
                parts = line.split("\t", 1)
                if len(parts) > 1:
                    files.add(parts[1])
                elif line.startswith("+++ b/") or line.startswith("--- a/"):
                    fname = line[6:]
                    if fname != "/dev/null":
                        files.add(fname)
            elif line.startswith("+") and not line.startswith("+++"):
                insertions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1

        return DiffStats(
            insertions=insertions,
            deletions=deletions,
            files=len(files),
        )

    @staticmethod
    def _parse_files_from_diff(diff: str) -> tuple[str, ...]:
        """Extract changed file paths from a git diff."""
        files = []
        for line in diff.splitlines():
            if line.startswith("diff --git"):
                parts = line.split(" b/", 1)
                if len(parts) > 1:
                    files.append(parts[1])
        return tuple(files)

    @staticmethod
    def _parse_test_results(output: str) -> TestResults:
        """Parse test results from common test runner output."""
        passed = 0
        failed = 0
        errors = 0

        # pytest pattern: "X passed, Y failed, Z errors"
        pytest_match = re.search(
            r"(\d+)\s+passed", output
        )
        if pytest_match:
            passed = int(pytest_match.group(1))
        fail_match = re.search(r"(\d+)\s+failed", output)
        if fail_match:
            failed = int(fail_match.group(1))
        error_match = re.search(r"(\d+)\s+error", output)
        if error_match:
            errors = int(error_match.group(1))

        # npm test / jest pattern
        if not pytest_match:
            jest_pass = re.search(r"Tests:\s+(\d+)\s+passed", output)
            jest_fail = re.search(r"Tests:\s+(\d+)\s+failed", output)
            if jest_pass:
                passed = int(jest_pass.group(1))
            if jest_fail:
                failed = int(jest_fail.group(1))

        return TestResults(
            passed=passed,
            failed=failed,
            errors=errors,
            output_snippet=output[-500:] if len(output) > 500 else output,
        )

    # --- Patrol Mode ---

    async def _patrol_loop(self) -> None:
        """Background loop that periodically surveys system state."""
        interval = self._config.coordinator.patrol_interval
        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self._run_patrol()
                except Exception:
                    logger.warning("Patrol check failed", exc_info=True)
        except asyncio.CancelledError:
            pass

    async def _run_patrol(self) -> None:
        """Single patrol iteration: gather state, optionally act."""
        autonomy = self._config.coordinator.patrol_autonomy

        # Gather system snapshot
        snapshot = await self._dashboard.load_snapshot()
        state_text = snapshot.summary_text()

        # Gather unacked events
        unacked_events: list[AgentEvent] = []
        if self._agent_event_repo:
            try:
                unacked_events = await self._agent_event_repo.list_unacknowledged(limit=20)
            except Exception:
                pass

        # Gather running session outputs (brief)
        session_summaries: list[str] = []
        sessions = await self._session.list_sessions()
        for s in sessions:
            if s.lifecycle == SessionLifecycle.RUNNING:
                try:
                    output = await self._session.get_session_output(s.id, lines=5)
                    last_line = (output or "").strip().splitlines()[-1] if output else "(no output)"
                    session_summaries.append(f"  {s.id[:8]}... ({s.agent_backend}): {last_line[:100]}")
                except Exception:
                    session_summaries.append(f"  {s.id[:8]}... ({s.agent_backend}): (could not read output)")

        if autonomy == "observe":
            # Log-only mode — no LLM calls, zero cost
            logger.info(
                "Patrol [observe]: %d running sessions, %d unacked events",
                len(session_summaries), len(unacked_events),
            )
            return

        # Build patrol prompt for the LLM
        event_text = ""
        if unacked_events:
            event_lines = [
                f"  [{e.event_type.value}] session={e.session_id[:8]}... {e.detail[:100]}"
                for e in unacked_events
            ]
            event_text = "\nUnacknowledged Events:\n" + "\n".join(event_lines)

        session_text = ""
        if session_summaries:
            session_text = "\nRunning Sessions (last output):\n" + "\n".join(session_summaries)

        # Restrict available tools based on autonomy level
        if autonomy == "nudge":
            allowed_tools = {"send_to_session", "acknowledge_events", "list_agent_events",
                             "get_session_output", "list_tasks", "list_sessions"}
        else:  # full
            allowed_tools = {t["name"] for t in TOOL_DEFINITIONS}

        patrol_prompt = f"""You are running in autonomous patrol mode (autonomy={autonomy}).
Survey the system and take appropriate action if needed.

System State:
{state_text}{event_text}{session_text}

Rules:
- Only act if something clearly needs attention (stalls, errors, help requests)
- In nudge mode: you can only send messages to sessions and acknowledge events
- In full mode: you can start/stop sessions, send notifications, and escalate
- Be conservative — prefer observing over acting
- Keep responses very brief (under 100 words)"""

        patrol_config = LLMConfig(
            model=self._llm_config.model,
            max_tokens=1024,
            temperature=0.3,
            tools=[t for t in TOOL_DEFINITIONS if t["name"] in allowed_tools],
        )

        messages = [
            LLMMessage(role="system", content=patrol_prompt),
            LLMMessage(role="user", content="Run patrol check now."),
        ]

        # Allow up to 3 tool rounds in patrol
        for _ in range(3):
            try:
                response = await self._provider.complete(messages, patrol_config)
            except Exception:
                logger.warning("Patrol LLM call failed", exc_info=True)
                return

            if not response.has_tool_calls:
                if response.content:
                    logger.info("Patrol [%s]: %s", autonomy, response.content[:200])
                return

            # Execute tool calls
            assistant_msg = LLMMessage(
                role="assistant",
                content=response.content,
                tool_calls=[
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in response.tool_calls
                ],
            )
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name not in allowed_tools:
                    result = {"error": f"Tool {tc.name} not allowed in {autonomy} mode"}
                else:
                    result = await self._execute_tool_with_retry(tc.name, tc.arguments)
                logger.info("Patrol executed tool %s -> %s", tc.name, json.dumps(result, default=str)[:200])
                messages.append(LLMMessage(
                    role="tool",
                    content=json.dumps(result, default=str),
                    tool_call_id=tc.id,
                    name=tc.name,
                ))

    # --- One-Shot Ask ---

    async def ask(self, question: str) -> str:
        """One-shot question to the coordinator (no conversation history).

        Supports tool calls — the coordinator can query system state to
        answer the question, just like handle_message().
        """
        snapshot = await self._dashboard.load_snapshot()
        system_prompt = self._build_system_prompt(snapshot)

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=question),
        ]

        max_tool_rounds = 10
        response = None
        for _ in range(max_tool_rounds):
            response = await self._provider.complete(messages, self._llm_config)

            if not response.has_tool_calls:
                return response.content

            # Execute tool calls in parallel
            assistant_msg = LLMMessage(
                role="assistant",
                content=response.content,
                tool_calls=[
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in response.tool_calls
                ],
            )
            messages.append(assistant_msg)

            tool_tasks = [
                self._execute_tool_with_retry(tc.name, tc.arguments)
                for tc in response.tool_calls
            ]
            results = await asyncio.gather(*tool_tasks)

            for tc, result in zip(response.tool_calls, results):
                messages.append(LLMMessage(
                    role="tool",
                    content=json.dumps(result, default=str),
                    tool_call_id=tc.id,
                    name=tc.name,
                ))

        return response.content if response else "I couldn't complete the request."
