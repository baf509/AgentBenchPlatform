"""Coordinator service: meta-agent with system-wide visibility."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from agentbenchplatform.config import AppConfig
from agentbenchplatform.infra.db.coordinator_history import CoordinatorHistoryRepo
from agentbenchplatform.infra.db.usage import UsageRepo
from agentbenchplatform.infra.providers.registry import get_provider_with_fallback
from agentbenchplatform.models.memory import MemoryQuery, MemoryScope
from agentbenchplatform.models.provider import LLMConfig, LLMMessage
from agentbenchplatform.models.research import ResearchConfig
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
        "description": "Start a coding session. Choose agent tier based on task complexity: claude_code (senior/complex), opencode (mid/implementation), claude_local (junior/simple)",
        "parameters": {
            "type": "object",
            "properties": {
                "task_slug": {"type": "string", "description": "Task slug"},
                "agent": {
                    "type": "string",
                    "enum": ["claude_code", "claude_local", "opencode"],
                    "description": "Agent tier: claude_code (senior), opencode (mid), claude_local (junior). Choose the lowest tier capable of the work.",
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
    ) -> None:
        self._dashboard = dashboard_service
        self._session = session_service
        self._memory = memory_service
        self._task = task_service
        self._config = config
        self._research = research_service
        self._usage_repo = usage_repo
        self._history_repo = history_repo
        self._provider = get_provider_with_fallback(config, config.coordinator.provider)
        self._llm_config = LLMConfig(
            model=config.coordinator.model,
            max_tokens=4096,
            temperature=0.7,
            tools=TOOL_DEFINITIONS,
        )
        self._conversations: dict[str, list[LLMMessage]] = {}

    async def _get_conversation(self, channel: str, sender_id: str = "") -> list[LLMMessage]:
        """Get or create conversation history for a channel/sender.

        Loads from MongoDB on first access, then caches in memory.
        """
        key = f"{channel}:{sender_id}"
        if key not in self._conversations:
            if self._history_repo:
                try:
                    self._conversations[key] = await self._history_repo.load_conversation(
                        channel, sender_id
                    )
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

        # Build system prompt with live system state
        snapshot = await self._dashboard.load_snapshot()
        system_prompt = self._build_system_prompt(snapshot)

        # Add user message to history
        conversation.append(LLMMessage(role="user", content=user_message))

        # Build full message list
        messages = [
            LLMMessage(role="system", content=system_prompt),
            *conversation,
        ]

        # LLM completion with tool use
        max_tool_rounds = 10
        for _ in range(max_tool_rounds):
            response = await self._provider.complete(messages, self._llm_config)

            # Track token usage
            if self._usage_repo:
                try:
                    await self._usage_repo.insert(UsageEvent(
                        source="coordinator",
                        model=response.model or self._llm_config.model,
                        input_tokens=response.usage.get("input_tokens", 0),
                        output_tokens=response.usage.get("output_tokens", 0),
                        channel=channel,
                        timestamp=datetime.now(timezone.utc),
                    ))
                except Exception:
                    logger.debug("Failed to log coordinator usage", exc_info=True)

            # Budget guard: warn if coordinator is over-planning
            round_output = response.usage.get("output_tokens", 0)
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

            for tc in response.tool_calls:
                if on_progress:
                    on_progress(f"[tool] {tc.name}")
                result = await self._execute_tool(tc.name, tc.arguments)
                tool_msg = LLMMessage(
                    role="tool",
                    content=json.dumps(result, default=str),
                    tool_call_id=tc.id,
                    name=tc.name,
                )
                conversation.append(tool_msg)
                messages.append(tool_msg)

        await self._save_conversation(channel, sender_id)
        return response.content if response else "I couldn't complete the request."

    def _build_system_prompt(self, snapshot) -> str:
        """Build system prompt with live system state."""
        state_summary = snapshot.summary_text()

        return f"""You are the agentbench coordinator - a meta-agent with full visibility and control over all tasks, sessions, and agents in the system.

You can:
- Monitor: See all tasks, sessions, their statuses, recent outputs, and errors
- Manage: Start/stop/pause sessions, create tasks, assign work
- Advise: Answer questions about what agents are doing, summarize progress
- Delegate: Route user requests to the appropriate agent or action
- Remember: Access the full memory system (global + per-task)

Agent Tiers (use these when starting coding sessions):
- claude_code: Senior engineer. Use for architecture, complex refactors, multi-file changes,
  tasks requiring deep reasoning or subtle judgment. Highest capability, highest cost.
- opencode: Mid-level engineer (Kimi2.5). Use for well-scoped implementation tasks with clear
  requirements — adding endpoints, implementing features from specs, moderate refactors.
- claude_local: Junior engineer (Qwen3). Use for simple, well-defined work — boilerplate,
  renaming, formatting, straightforward tests, small bug fixes with obvious solutions.

When starting sessions, always choose the lowest tier capable of handling the work.
When decomposing tasks, classify briefly and assign — do not design the solution yourself.
Keep decomposition responses short (under 500 words). If a task can't be quickly classified,
send it to claude_code.

Review Policy:
- After a claude_local (junior) session completes, review its work using get_session_diff
  before recommending it for merge. Run tests if the workspace has them.
- If the work is incorrect or incomplete, note what went wrong and start a new session
  at a higher tier (opencode or claude_code) with specific guidance on what to fix.
- For opencode sessions, review is optional but recommended for complex changes.
- For claude_code sessions, trust the output — review only if the user asks.

Current System State:
{state_summary}

Use the available tools to inspect and manage the system. Be helpful, concise, and proactive about suggesting actions when appropriate."""

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
                return {"session_id": session.id, "status": session.lifecycle.value}

            elif name == "stop_session":
                session = await self._session.stop_session(arguments["session_id"])
                return {"stopped": session is not None}

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
                diff = await self._session.get_session_diff(
                    arguments["session_id"]
                )
                return {"diff": diff or "(no changes)"}

            elif name == "run_in_worktree":
                output = await self._session.run_in_worktree(
                    arguments["session_id"], arguments["command"]
                )
                return {"output": output}

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
                result = await self._execute_tool(tc.name, tc.arguments)
                messages.append(LLMMessage(
                    role="tool",
                    content=json.dumps(result, default=str),
                    tool_call_id=tc.id,
                    name=tc.name,
                ))

        return response.content if response else "I couldn't complete the request."
