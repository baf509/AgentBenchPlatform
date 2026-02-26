"""Coordinator service: meta-agent with system-wide visibility.

Tool execution is delegated to handler functions in
``coordinator_tools/`` via a registry, keeping this module focused
on conversation management, watchdog, and patrol orchestration.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
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
from agentbenchplatform.infra.db.workspaces import WorkspaceRepo
from agentbenchplatform.infra.providers.registry import get_provider_with_fallback
from agentbenchplatform.models.agent_event import AgentEvent, AgentEventType
from agentbenchplatform.models.conversation_summary import ConversationSummary
from agentbenchplatform.models.coordinator_decision import CoordinatorDecision, ToolCallRecord
from agentbenchplatform.models.provider import LLMConfig, LLMMessage
from agentbenchplatform.models.session import SessionLifecycle
from agentbenchplatform.models.session_report import SessionReport
from agentbenchplatform.models.usage import UsageEvent
from agentbenchplatform.services.coordinator_tools.context import ToolContext
from agentbenchplatform.services.coordinator_tools.registry import get_tool_handlers
from agentbenchplatform.services.dashboard_service import DashboardService
from agentbenchplatform.services.memory_service import MemoryService
from agentbenchplatform.services.research_service import ResearchService
from agentbenchplatform.services.session_service import SessionService
from agentbenchplatform.services.task_service import TaskService

logger = logging.getLogger(__name__)

# Errors considered transient and worth retrying
_RETRYABLE_ERRORS = (
    TimeoutError,
    ConnectionError,
    OSError,
)
# Try to include pymongo errors if available
try:
    from pymongo.errors import AutoReconnect, ConnectionFailure, NetworkTimeout
    _RETRYABLE_ERRORS = (*_RETRYABLE_ERRORS, AutoReconnect, ConnectionFailure, NetworkTimeout)
except ImportError:
    pass

# Max consecutive summarization failures before aggressive truncation
_MAX_SUMMARY_FAILURES = 3

# Patterns that match common interactive prompts agents may encounter.
# Each tuple: (compiled regex, auto_response or None, human-readable description)
INTERACTIVE_PROMPT_PATTERNS: list[tuple[re.Pattern, str | None, str]] = [
    # Claude Code permission prompts (safety net if bypassPermissions is off)
    (re.compile(r"Allow|Deny|allow this|deny this", re.IGNORECASE), "y\n", "permission prompt"),
    # Generic yes/no confirmations
    (re.compile(r"\(y/n\)|\(Y/n\)|\[y/N\]|\[Y/n\]"), "y\n", "yes/no confirmation"),
    # "Do you want to proceed/continue?"
    (re.compile(r"(?:proceed|continue|overwrite|replace)\?", re.IGNORECASE), "y\n", "proceed confirmation"),
    # npm/pip install confirmations
    (re.compile(r"Do you want to install", re.IGNORECASE), "y\n", "install confirmation"),
    # Git prompts
    (re.compile(r"Are you sure you want to", re.IGNORECASE), "y\n", "git confirmation"),
    # Press enter to continue
    (re.compile(r"[Pp]ress [Ee]nter|press any key|hit enter"), "\n", "press enter prompt"),
    # OpenCode permission patterns
    (re.compile(r"approve|reject|Tool requires approval", re.IGNORECASE), "approve\n", "opencode tool approval"),
]


def _detect_interactive_prompt(output: str) -> tuple[str | None, str] | None:
    """Check if output ends with a known interactive prompt.

    Examines the last 5 non-empty lines for matches.
    Returns (auto_response, description) if matched, None otherwise.
    """
    lines = [ln for ln in output.strip().splitlines() if ln.strip()]
    tail = lines[-5:] if len(lines) >= 5 else lines
    for line in reversed(tail):
        for pattern, auto_response, description in INTERACTIVE_PROMPT_PATTERNS:
            if pattern.search(line):
                return (auto_response, description)
    return None


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
        "description": "Merge a session's worktree branch into the main workspace. Auto-checks for conflicts unless force=true.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID whose branch to merge"},
                "force": {"type": "boolean", "description": "Skip conflict check and merge anyway (default false)"},
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
    # --- Dependency tools ---
    {
        "name": "add_dependency",
        "description": "Add a dependency: task_slug depends on depends_on_slug. Validates both exist and detects cycles.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_slug": {"type": "string", "description": "Task that depends on another"},
                "depends_on_slug": {"type": "string", "description": "Task that must complete first"},
            },
            "required": ["task_slug", "depends_on_slug"],
        },
    },
    {
        "name": "remove_dependency",
        "description": "Remove a dependency between two tasks",
        "parameters": {
            "type": "object",
            "properties": {
                "task_slug": {"type": "string", "description": "Task to remove dependency from"},
                "depends_on_slug": {"type": "string", "description": "Dependency to remove"},
            },
            "required": ["task_slug", "depends_on_slug"],
        },
    },
    {
        "name": "get_task_dependencies",
        "description": "Get dependency info: direct deps, transitive deps, and blocking (unsatisfied) deps",
        "parameters": {
            "type": "object",
            "properties": {
                "task_slug": {"type": "string", "description": "Task slug"},
            },
            "required": ["task_slug"],
        },
    },
    {
        "name": "get_ready_tasks",
        "description": "List active tasks with all dependencies satisfied (ready to work on)",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    # --- Conflict detection tools ---
    {
        "name": "check_conflicts",
        "description": "Check if a session's changed files overlap with other sessions for the same task",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID to check"},
            },
            "required": ["session_id"],
        },
    },
    # --- Rollback tools ---
    {
        "name": "rollback_session",
        "description": "Revert a previously merged session by git-reverting its merge commit",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID whose merge to revert"},
            },
            "required": ["session_id"],
        },
    },
    # --- Progress estimation tools ---
    {
        "name": "estimate_duration",
        "description": "Estimate session duration based on historical data. Returns avg, count, p90. If session_id given, shows elapsed + estimated remaining.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent": {"type": "string", "description": "Agent backend to filter by (optional)"},
                "complexity": {"type": "string", "description": "Complexity tier to filter by (optional)"},
                "session_id": {"type": "string", "description": "Running session ID to estimate remaining time (optional)"},
            },
        },
    },
    # --- Playbook tools ---
    {
        "name": "list_playbooks",
        "description": "List all available playbooks/templates",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "create_playbook",
        "description": "Create a reusable playbook with steps (create_task, start_session, review_session, merge_session)",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Playbook name (unique)"},
                "description": {"type": "string", "description": "What this playbook does"},
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["create_task", "start_session", "review_session", "merge_session"]},
                            "params": {"type": "object", "description": "Action-specific parameters"},
                        },
                        "required": ["action", "params"],
                    },
                    "description": "Ordered list of steps",
                },
                "workspace_path": {"type": "string", "description": "Default workspace path for tasks"},
            },
            "required": ["name", "description", "steps"],
        },
    },
    {
        "name": "run_playbook",
        "description": "Execute a playbook. Creates tasks/sessions as defined. Use dry_run=true to preview without executing.",
        "parameters": {
            "type": "object",
            "properties": {
                "playbook_name": {"type": "string", "description": "Playbook name"},
                "workspace_path": {"type": "string", "description": "Override workspace path (optional)"},
                "dry_run": {"type": "boolean", "description": "Preview without executing (default false)"},
            },
            "required": ["playbook_name"],
        },
    },
]


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
        merge_record_repo=None,
        session_metric_repo=None,
        playbook_repo=None,
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
        self._merge_record_repo = merge_record_repo
        self._session_metric_repo = session_metric_repo
        self._playbook_repo = playbook_repo
        self._signal = None  # set via set_signal_service()
        self._provider = get_provider_with_fallback(config, config.coordinator.provider)
        self._llm_config = LLMConfig(
            model=config.coordinator.model,
            max_tokens=4096,
            temperature=0.7,
            tools=TOOL_DEFINITIONS,
            provider_order=config.coordinator.provider_order,
        )
        self._conversations: dict[str, list[LLMMessage]] = {}
        self._watchdog_task: asyncio.Task | None = None
        self._patrol_task: asyncio.Task | None = None
        self._session_deadlines: dict[str, float] = {}  # session_id -> deadline timestamp
        # Output change tracking: session_id -> (output_hash, timestamp_of_last_change)
        self._session_output_hashes: dict[str, tuple[str, float]] = {}
        # Track consecutive summarization failures per conversation key
        self._summary_failures: dict[str, int] = {}
        # Proactive Signal notification tracking
        self._last_signal_sender: str = ""
        # session_id -> timestamp of last STALLED notification (rate-limit)
        self._stall_notification_ts: dict[str, float] = {}

        # Build tool context for handler dispatch
        self._tool_ctx = ToolContext(
            session=session_service,
            task=task_service,
            memory=memory_service,
            config=config,
            research=research_service,
            usage_repo=usage_repo,
            history_repo=history_repo,
            session_report_repo=session_report_repo,
            agent_event_repo=agent_event_repo,
            workspace_repo=workspace_repo,
            merge_record_repo=merge_record_repo,
            session_metric_repo=session_metric_repo,
            playbook_repo=playbook_repo,
            emit_event=self._emit_event,
            execute_tool=self._execute_tool,
            llm_config=self._llm_config,
            provider=self._provider,
            session_deadlines=self._session_deadlines,
            session_output_hashes=self._session_output_hashes,
            conversations=self._conversations,
        )

    # --- Late Binding ---

    def set_signal_service(self, signal_service) -> None:
        """Late-bind the signal service (avoids circular dependency)."""
        self._signal = signal_service
        self._tool_ctx.signal = signal_service

    # --- Watchdog ---

    def start_watchdog(
        self, check_interval: int = 30, stall_threshold: int = 600,
        idle_interval: int = 120,
    ) -> None:
        """Start background watchdog that monitors session health.

        Args:
            check_interval: Seconds between checks when sessions are running.
            stall_threshold: Seconds of unchanged output before emitting STALLED.
            idle_interval: Seconds between checks when no sessions are running.
        """
        if self._watchdog_task is not None:
            return
        self._watchdog_task = asyncio.ensure_future(
            self._watchdog_loop(check_interval, stall_threshold, idle_interval)
        )
        logger.info("Coordinator watchdog started (active=%ds, idle=%ds, stall=%ds)",
                     check_interval, idle_interval, stall_threshold)
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
        self, check_interval: int, stall_threshold: int, idle_interval: int
    ) -> None:
        """Periodically check session health and deadlines.

        Uses *check_interval* (fast) when sessions are running,
        *idle_interval* (slow) when none are active.
        """
        try:
            while True:
                has_running = await self._has_running_sessions()
                interval = check_interval if has_running else idle_interval
                await asyncio.sleep(interval)
                try:
                    await self._check_sessions(stall_threshold)
                    await self._check_deadlines()
                except Exception:
                    logger.warning("Watchdog check failed", exc_info=True)
        except asyncio.CancelledError:
            pass

    async def _has_running_sessions(self) -> bool:
        """Return True if any sessions are currently RUNNING."""
        sessions = await self._session.list_sessions()
        return any(s.lifecycle == SessionLifecycle.RUNNING for s in sessions)

    async def _check_sessions(self, stall_threshold: int) -> None:
        """Check running sessions for dead processes, stalls, and interactive prompts."""
        sessions = await self._session.list_sessions()
        running_ids = set()
        for session in sessions:
            if session.lifecycle != SessionLifecycle.RUNNING:
                continue
            running_ids.add(session.id)
            try:
                is_alive = await self._session.check_session_liveness(session.id)
                if not is_alive:
                    await self._emit_event(
                        session.id, session.task_id,
                        AgentEventType.ERROR,
                        "Session process is no longer running",
                    )
                    continue

                # Capture more context (15 lines) for smarter detection
                output = await self._session.get_session_output(session.id, lines=15)
                now = time.time()

                if not output or not output.strip():
                    # No output at all — check if unchanged long enough
                    prev = self._session_output_hashes.get(session.id)
                    if prev is None:
                        self._session_output_hashes[session.id] = ("", now)
                    elif now - prev[1] >= stall_threshold:
                        await self._emit_event(
                            session.id, session.task_id,
                            AgentEventType.STALLED,
                            f"No output detected (unchanged for {int(now - prev[1])}s)",
                        )
                    continue

                # Hash output and compare to previous
                output_hash = hashlib.md5(output.encode(), usedforsecurity=False).hexdigest()
                prev = self._session_output_hashes.get(session.id)

                if prev is None or prev[0] != output_hash:
                    # Output changed — update tracking
                    self._session_output_hashes[session.id] = (output_hash, now)
                    continue

                # Output unchanged — check how long
                unchanged_seconds = now - prev[1]

                # Check for interactive prompt patterns
                prompt_match = _detect_interactive_prompt(output)
                if prompt_match and unchanged_seconds >= 10:
                    auto_response, description = prompt_match
                    auto_responded = False

                    # Auto-respond if configured and autonomy allows
                    if (
                        auto_response
                        and self._config.coordinator.auto_respond_prompts
                        and self._config.coordinator.patrol_autonomy in ("nudge", "full")
                    ):
                        try:
                            await self._session.send_to_session(session.id, auto_response)
                            auto_responded = True
                            logger.info(
                                "Watchdog auto-responded to %s in session %s (response=%r)",
                                description, session.id[:8], auto_response.strip(),
                            )
                        except Exception:
                            logger.warning(
                                "Failed to auto-respond to session %s",
                                session.id, exc_info=True,
                            )

                    detail = f"Waiting for input: {description} (unchanged {int(unchanged_seconds)}s)"
                    if auto_responded:
                        detail += " [auto-responded]"
                    await self._emit_event(
                        session.id, session.task_id,
                        AgentEventType.WAITING_INPUT,
                        detail,
                    )
                    # Reset hash so we don't re-fire every cycle
                    self._session_output_hashes[session.id] = (output_hash, now)

                elif unchanged_seconds >= stall_threshold:
                    await self._emit_event(
                        session.id, session.task_id,
                        AgentEventType.STALLED,
                        f"Output unchanged for {int(unchanged_seconds)}s",
                    )
                    # Reset to avoid spamming
                    self._session_output_hashes[session.id] = (output_hash, now)

            except Exception:
                logger.debug("Watchdog check failed for session %s", session.id, exc_info=True)

        # Clean up hashes for sessions that are no longer running
        stale = set(self._session_output_hashes) - running_ids
        for sid in stale:
            del self._session_output_hashes[sid]

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
        """Summarize older messages if truncation would drop >10 messages.

        Tracks consecutive failures per conversation key. If failures exceed
        _MAX_SUMMARY_FAILURES, falls back to aggressive truncation and emits
        an event so the issue is visible.
        """
        if not self._conversation_summary_repo:
            return

        max_keep = 20 * 3  # max_exchanges * ~3 msgs per exchange
        if len(conversation) <= max_keep + 10:
            return

        # Count messages that would be dropped
        drop_count = len(conversation) - max_keep
        if drop_count <= 10:
            return

        # Check if summarization has been failing repeatedly
        failure_count = self._summary_failures.get(key, 0)
        if failure_count >= _MAX_SUMMARY_FAILURES:
            logger.warning(
                "Summarization for %s has failed %d times; skipping and truncating aggressively",
                key, failure_count,
            )
            # Emit event for visibility
            await self._emit_event(
                "", "",
                AgentEventType.ERROR,
                f"Conversation summarization failing for {key} ({failure_count} consecutive failures)",
            )
            # Reset counter to retry eventually
            self._summary_failures[key] = 0
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

            # Reset failure counter on success
            self._summary_failures.pop(key, None)
            logger.debug("Created conversation summary for %s (%d messages summarized)",
                         key, drop_count)
        except Exception:
            self._summary_failures[key] = failure_count + 1
            logger.debug(
                "Failed to create conversation summary (failure %d/%d)",
                failure_count + 1, _MAX_SUMMARY_FAILURES,
                exc_info=True,
            )

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
        # Track most recent Signal sender for proactive notifications
        if channel == "signal" and sender_id:
            self._last_signal_sender = sender_id

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
        """Execute a tool with retry on transient errors.

        Uses exponential backoff with jitter to avoid thundering herd.
        """
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                return await self._execute_tool(name, arguments)
            except _RETRYABLE_ERRORS as e:
                last_error = e
                if attempt < max_retries:
                    # Exponential backoff with jitter: base * 2^attempt + random(0, 1)
                    delay = (1 << attempt) + random.random()
                    await asyncio.sleep(delay)
                    logger.debug("Retrying tool %s (attempt %d/%d): %s",
                                 name, attempt + 1, max_retries, e)
        return {"error": f"Tool failed after {max_retries + 1} attempts: {last_error}"}

    async def _execute_tool(self, name: str, arguments: dict) -> Any:
        """Execute a coordinator tool call via the handler registry."""
        try:
            handlers = get_tool_handlers()
            handler = handlers.get(name)
            if handler is None:
                return {"error": f"Unknown tool: {name}"}
            return await handler(self._tool_ctx, arguments)
        except KeyError as e:
            logger.warning("Tool %s missing required argument: %s", name, e)
            return {"error": f"Missing required argument: {e}"}
        except ValueError as e:
            logger.warning("Tool %s received invalid argument: %s", name, e)
            return {"error": f"Invalid argument: {e}"}
        except Exception as e:
            logger.exception("Tool %s execution failed unexpectedly", name)
            return {"error": f"Tool execution failed: {str(e)}"}

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
        """Emit an agent event to MongoDB and send proactive Signal notifications."""
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

        # Proactive Signal notification for important events
        if event_type in (
            AgentEventType.COMPLETED,
            AgentEventType.ERROR,
            AgentEventType.STALLED,
        ):
            await self._maybe_notify_phone(session_id, event_type, detail)

    # Stall notification cooldown: max once per 5 minutes per session
    _STALL_COOLDOWN = 300

    async def _maybe_notify_phone(
        self,
        session_id: str,
        event_type: AgentEventType,
        detail: str,
    ) -> None:
        """Send a proactive Signal notification if we have a phone number."""
        if not self._signal:
            return

        # Resolve phone: explicit config > last Signal sender
        phone = (
            self._config.coordinator.patrol_notify_phone
            or self._last_signal_sender
        )
        if not phone:
            return

        # Rate-limit STALLED notifications (once per 5 min per session)
        if event_type == AgentEventType.STALLED:
            last_ts = self._stall_notification_ts.get(session_id, 0.0)
            if time.monotonic() - last_ts < self._STALL_COOLDOWN:
                return
            self._stall_notification_ts[session_id] = time.monotonic()

        # Build concise message
        label = event_type.value.upper()
        short_id = session_id[:12]
        # Truncate detail to keep SMS-friendly
        truncated = (detail[:120] + "...") if len(detail) > 120 else detail
        text = f"[{short_id}] {label}: {truncated}"

        try:
            await self._signal.send_notification(phone, text)
            logger.info(
                "Sent proactive notification for %s (%s) to %s",
                session_id, label, phone,
            )
        except Exception:
            logger.debug(
                "Failed to send proactive notification", exc_info=True,
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

        if autonomy == "observe":
            # Lightweight observe mode — only count, no expensive data gathering
            sessions = await self._session.list_sessions()
            running_count = sum(
                1 for s in sessions if s.lifecycle == SessionLifecycle.RUNNING
            )
            unacked_count = 0
            if self._agent_event_repo:
                try:
                    events = await self._agent_event_repo.list_unacknowledged(limit=1)
                    unacked_count = len(events)
                except Exception:
                    pass
            logger.info(
                "Patrol [observe]: %d running sessions, %d unacked events",
                running_count, unacked_count,
            )
            return

        # Gather system snapshot for nudge/full modes
        snapshot = await self._dashboard.load_snapshot()
        state_text = snapshot.summary_text()

        # Gather unacked events
        unacked_events: list[AgentEvent] = []
        if self._agent_event_repo:
            try:
                unacked_events = await self._agent_event_repo.list_unacknowledged(limit=20)
            except Exception:
                pass

        # Gather running session outputs (richer context)
        session_summaries: list[str] = []
        sessions = await self._session.list_sessions()
        now = time.time()
        for s in sessions:
            if s.lifecycle == SessionLifecycle.RUNNING:
                try:
                    output = await self._session.get_session_output(s.id, lines=20)
                    tail = (output or "").strip().splitlines()[-5:] if output else []
                    tail_text = "\n".join(f"    | {ln[:120]}" for ln in tail) if tail else "    (no output)"

                    # Determine output change status
                    prev = self._session_output_hashes.get(s.id)
                    if prev:
                        unchanged_secs = int(now - prev[1])
                        if unchanged_secs > 60:
                            status = f"unchanged for {unchanged_secs // 60}m{unchanged_secs % 60}s"
                        else:
                            status = "active"
                    else:
                        status = "active"

                    # Check for interactive prompt
                    prompt_match = _detect_interactive_prompt(output or "")
                    if prompt_match:
                        status = f"WAITING FOR INPUT: {prompt_match[1]}"

                    session_summaries.append(
                        f"  {s.id[:8]}... ({s.agent_backend}) [{status}]:\n{tail_text}"
                    )
                except Exception:
                    session_summaries.append(f"  {s.id[:8]}... ({s.agent_backend}): (could not read output)")

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
- If a session is waiting for interactive input (permission prompt, confirmation, etc.),
  use send_to_session to approve/proceed. Agents run in isolated worktrees so it's safe.
- If a session appears stuck in a loop (same error repeated), consider stopping and
  escalating to a higher-tier agent.
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
