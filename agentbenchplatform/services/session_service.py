"""Session business logic: subprocess start/stop/pause/resume."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from agentbenchplatform.config import AppConfig
from agentbenchplatform.infra import git as git_ops
from agentbenchplatform.infra.agents.registry import get_backend
from agentbenchplatform.infra.db.sessions import SessionRepo
from agentbenchplatform.infra.db.tasks import TaskRepo
from agentbenchplatform.infra.subprocess_mgr import SubprocessManager
from agentbenchplatform.models.agent import AgentBackendType, StartParams
from agentbenchplatform.models.session import Session, SessionKind, SessionLifecycle

if TYPE_CHECKING:
    from agentbenchplatform.services.memory_service import MemoryService

logger = logging.getLogger(__name__)


class SessionService:
    """Business logic for session management."""

    def __init__(
        self,
        session_repo: SessionRepo,
        config: AppConfig,
        task_repo: TaskRepo | None = None,
        memory_service: MemoryService | None = None,
    ) -> None:
        self._repo = session_repo
        self._config = config
        self._task_repo = task_repo
        self._memory_service = memory_service
        self._subprocess_mgr = SubprocessManager(
            tmux_enabled=config.tmux.enabled,
            session_prefix=config.tmux.session_prefix,
        )

    async def start_coding_session(
        self,
        task_id: str,
        agent_type: str = "",
        prompt: str = "",
        model: str = "",
        workspace_path: str = "",
        task_tags: tuple[str, ...] = (),
        task_complexity: str = "",
    ) -> Session:
        """Start a new coding agent session."""
        if not agent_type:
            from agentbenchplatform.services.routing import recommend_agent

            agent_type = recommend_agent(
                prompt=prompt, tags=task_tags, complexity=task_complexity,
            )
        backend_type = AgentBackendType(agent_type or self._config.default_agent)
        # Pass opencode_model from config for the local backend
        llamacpp_cfg = self._config.providers.get("llamacpp")
        backend_kwargs = {}
        if llamacpp_cfg and llamacpp_cfg.opencode_model:
            backend_kwargs["model"] = llamacpp_cfg.opencode_model
        backend = get_backend(backend_type, **backend_kwargs)

        thread_id = str(uuid.uuid4())
        short_id = thread_id[:8]
        display_name = f"{backend_type.value}-{short_id}"

        # Try to create a git worktree for isolation
        worktree_path = ""
        effective_workspace = workspace_path
        if workspace_path:
            try:
                if await git_ops.is_git_repo(workspace_path):
                    branch = f"session/{display_name}"
                    worktree_path = await git_ops.create_worktree(
                        workspace_path, short_id, branch,
                    )
                    effective_workspace = worktree_path
            except Exception:
                logger.warning(
                    "Failed to create worktree for session %s, using main workspace",
                    short_id, exc_info=True,
                )
                worktree_path = ""

        # Fetch memory context and prepend to prompt
        effective_prompt = prompt
        if self._memory_service:
            try:
                # Note: session not created yet, so we can't pass session_id
                # Just fetch task-scoped memories for now
                memories = await self._memory_service.get_task_memories(task_id)
                if memories:
                    memory_context = self._format_memory_context(memories)
                    effective_prompt = f"{memory_context}\n\n{prompt}" if prompt else memory_context
                    logger.debug(
                        "Added %d task memories to session %s context",
                        len(memories), short_id
                    )
            except Exception:
                logger.warning(
                    "Failed to load memory context for session %s",
                    short_id, exc_info=True
                )

        params = StartParams(
            prompt=effective_prompt,
            model=model,
            workspace_path=effective_workspace,
            session_id=thread_id,
        )
        command = backend.start_command(params)

        # Create session record
        session = Session(
            task_id=task_id,
            kind=SessionKind.CODING_AGENT,
            lifecycle=SessionLifecycle.PENDING,
            agent_backend=backend_type.value,
            display_name=display_name,
            agent_thread_id=thread_id,
            worktree_path=worktree_path,
        )
        session = await self._repo.insert(session)

        # Spawn subprocess
        result = await self._subprocess_mgr.spawn(
            command=command,
            session_name=session.id or short_id,
            window_name=backend_type.value,
        )

        if result.success:
            session = await self._repo.update_attachment(
                session.id, result.attachment.to_doc()
            )
            session = await self._repo.update_lifecycle(
                session.id, SessionLifecycle.RUNNING
            )
            logger.info(
                "Started coding session %s (pid=%s, worktree=%s)",
                session.id, result.attachment.pid, worktree_path or "none",
            )
        else:
            await self._repo.update_lifecycle(session.id, SessionLifecycle.FAILED)
            logger.error("Failed to start session %s: %s", session.id, result.error)
            # Clean up worktree on spawn failure
            if worktree_path:
                await self._cleanup_worktree_path(workspace_path, worktree_path)

        return session

    async def stop_session(self, session_id: str) -> Session | None:
        """Stop a running session."""
        session = await self._repo.find_by_id(session_id)
        if not session:
            return None

        if session.lifecycle.is_terminal:
            logger.warning("Session %s already in terminal state", session_id)
            return session

        await self._subprocess_mgr.stop(session.attachment)
        await self._cleanup_worktree(session)
        return await self._repo.update_lifecycle(session_id, SessionLifecycle.COMPLETED)

    async def pause_session(self, session_id: str) -> Session | None:
        """Pause a running session (SIGSTOP)."""
        session = await self._repo.find_by_id(session_id)
        if not session or session.lifecycle != SessionLifecycle.RUNNING:
            return session

        success = await self._subprocess_mgr.pause(session.attachment)
        if success:
            return await self._repo.update_lifecycle(session_id, SessionLifecycle.PAUSED)
        return session

    async def resume_session(self, session_id: str) -> Session | None:
        """Resume a paused session (SIGCONT)."""
        session = await self._repo.find_by_id(session_id)
        if not session or session.lifecycle != SessionLifecycle.PAUSED:
            return session

        success = await self._subprocess_mgr.resume(session.attachment)
        if success:
            return await self._repo.update_lifecycle(session_id, SessionLifecycle.RUNNING)
        return session

    async def archive_session(self, session_id: str) -> Session | None:
        """Archive a completed/failed session."""
        session = await self._repo.find_by_id(session_id)
        if not session:
            return None

        if session.lifecycle == SessionLifecycle.RUNNING:
            await self._subprocess_mgr.stop(session.attachment)

        await self._cleanup_worktree(session)
        return await self._repo.update_lifecycle(session_id, SessionLifecycle.ARCHIVED)

    def _format_memory_context(self, memories: list) -> str:
        """Format memories as context for agent prompt."""
        if not memories:
            return ""

        lines = ["# Shared Memory Context", ""]
        lines.append("The following information has been stored from previous work:")
        lines.append("")

        for mem in memories[:10]:  # Limit to 10 most recent
            lines.append(f"## {mem.key}")
            lines.append(mem.content[:500])  # Truncate long content
            lines.append("")

        lines.append("Use this context to inform your work.")
        return "\n".join(lines)

    async def _cleanup_worktree(self, session: Session) -> None:
        """Remove a session's worktree if one exists."""
        if not session.worktree_path:
            return
        if not self._task_repo:
            logger.warning("Cannot clean up worktree: no task_repo configured")
            return
        task = await self._task_repo.find_by_id(session.task_id)
        if not task:
            logger.warning("Cannot clean up worktree: task %s not found", session.task_id)
            return
        await self._cleanup_worktree_path(task.workspace_path, session.worktree_path)

    async def _cleanup_worktree_path(self, workspace_path: str, worktree_path: str) -> None:
        """Remove a worktree directory given the main repo and worktree paths."""
        try:
            await git_ops.remove_worktree(workspace_path, worktree_path)
        except Exception:
            logger.warning("Error removing worktree %s", worktree_path, exc_info=True)

    async def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID."""
        return await self._repo.find_by_id(session_id)

    async def list_sessions(
        self, task_id: str = "", lifecycle: SessionLifecycle | None = None
    ) -> list[Session]:
        """List sessions, optionally by task."""
        if task_id:
            return await self._repo.list_by_task(task_id, lifecycle)
        return await self._repo.list_all(lifecycle)

    async def get_session_output(
        self, session_id: str, lines: int = 100
    ) -> str:
        """Capture recent output from a session's tmux pane."""
        session = await self._repo.find_by_id(session_id)
        if not session:
            return ""

        att = session.attachment
        if att.tmux_session and att.tmux_window:
            return await self._subprocess_mgr.capture_output(
                att.tmux_session, att.tmux_window, lines
            )
        return ""

    async def send_to_session(self, session_id: str, text: str) -> bool:
        """Send text to a session's tmux pane."""
        session = await self._repo.find_by_id(session_id)
        if not session:
            return False

        att = session.attachment
        if att.tmux_session and att.tmux_window:
            return await self._subprocess_mgr.send_keys(
                att.tmux_session, att.tmux_window, text
            )
        return False

    async def get_session_diff(self, session_id: str) -> str:
        """Get git diff for a session's worktree."""
        session = await self._repo.find_by_id(session_id)
        if not session or not session.worktree_path:
            return ""
        return await git_ops.get_diff(session.worktree_path)

    async def run_in_worktree(self, session_id: str, command: str) -> str:
        """Run a command in a session's worktree. Returns stdout+stderr, truncated."""
        import asyncio as _asyncio
        import shlex

        session = await self._repo.find_by_id(session_id)
        if not session or not session.worktree_path:
            return "Session not found or has no worktree"

        try:
            args = shlex.split(command)
        except ValueError as e:
            return f"Invalid command syntax: {e}"

        try:
            proc = await _asyncio.create_subprocess_exec(
                *args,
                cwd=session.worktree_path,
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.STDOUT,
            )
            stdout, _ = await _asyncio.wait_for(proc.communicate(), timeout=60)
            text = stdout.decode(errors="replace") if stdout else ""
            return text[:10_000]
        except _asyncio.TimeoutError:
            proc.kill()
            return "Command timed out after 60s"
        except Exception as e:
            return f"Command failed: {e}"

    async def check_session_liveness(self, session_id: str) -> bool:
        """Check if a session's process is still alive."""
        session = await self._repo.find_by_id(session_id)
        if not session or not session.attachment.pid:
            return False
        return SubprocessManager.is_pid_alive(session.attachment.pid)
