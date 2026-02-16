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
from agentbenchplatform.infra.db.agent_events import AgentEventRepo
from agentbenchplatform.infra.db.conversation_summaries import ConversationSummaryRepo
from agentbenchplatform.infra.db.coordinator_decisions import CoordinatorDecisionRepo
from agentbenchplatform.infra.db.coordinator_history import CoordinatorHistoryRepo
from agentbenchplatform.infra.db.session_reports import SessionReportRepo
from agentbenchplatform.infra.db.usage import UsageRepo
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
        "description": "Store a new shared memory entry",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Memory key/identifier"},
                "content": {"type": "string", "description": "Memory content"},
                "task_slug": {"type": "string", "description": "Task to scope to (optional)"},
            },
            "required": ["key", "content"],
        },
    },
    {
        "name": "create_task",
        "description": "Create a new task",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title"},
                "description": {"type": "string", "description": "Task description"},
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
        self._provider = get_provider_with_fallback(config, config.coordinator.provider)
        self._llm_config = LLMConfig(
            model=config.coordinator.model,
            max_tokens=4096,
            temperature=0.7,
            tools=TOOL_DEFINITIONS,
        )
        self._conversations: dict[str, list[LLMMessage]] = {}
        self._watchdog_task: asyncio.Task | None = None
        self._session_deadlines: dict[str, float] = {}  # session_id -> deadline timestamp

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

    def stop_watchdog(self) -> None:
        """Stop the background watchdog task."""
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            self._watchdog_task = None
            logger.info("Coordinator watchdog stopped")

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
- Monitor: See all tasks, sessions, their statuses, recent outputs, and errors
- Manage: Start/stop/pause/resume sessions, create tasks, assign work, set deadlines
- Advise: Answer questions about what agents are doing, summarize progress
- Delegate: Route user requests to the appropriate agent or action
- Remember: Access the full memory system (global + per-task)
- Review: Generate structured session reports with diff stats, test results, and summaries
- React: Check and acknowledge agent events (stalls, errors, help requests)

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
                    {"slug": t.slug, "title": t.title, "status": t.status.value}
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
                    {"key": m.key, "content": m.content[:200], "scope": m.scope.value}
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
                entry = await self._memory.store(
                    key=arguments["key"],
                    content=arguments["content"],
                    scope=scope,
                    task_id=task_id,
                )
                return {"stored": True, "id": entry.id}

            elif name == "create_task":
                task = await self._task.create_task(
                    title=arguments["title"],
                    description=arguments.get("description", ""),
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
