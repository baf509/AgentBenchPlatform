"""Dashboard service: snapshot builder for TUI."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agentbenchplatform.infra.db.sessions import SessionRepo
from agentbenchplatform.infra.db.tasks import TaskRepo
from agentbenchplatform.infra.db.workspaces import WorkspaceRepo
from agentbenchplatform.models.session import Session, SessionLifecycle
from agentbenchplatform.models.task import Task, TaskStatus

logger = logging.getLogger(__name__)


@dataclass
class TaskSnapshot:
    """Snapshot of a task with its sessions."""

    task: Task
    sessions: list[Session] = field(default_factory=list)

    @property
    def running_count(self) -> int:
        return sum(1 for s in self.sessions if s.lifecycle == SessionLifecycle.RUNNING)

    @property
    def total_count(self) -> int:
        return len(self.sessions)


@dataclass
class DashboardSnapshot:
    """Complete snapshot of the system state for dashboard rendering."""

    tasks: list[TaskSnapshot] = field(default_factory=list)
    total_running: int = 0
    total_sessions: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def active_task_count(self) -> int:
        return sum(1 for t in self.tasks if t.task.status == TaskStatus.ACTIVE)

    def summary_text(self) -> str:
        """Generate a text summary for the coordinator."""
        lines = [f"System snapshot at {self.timestamp.isoformat()}:"]
        lines.append(
            f"  {self.active_task_count} active tasks, "
            f"{self.total_running}/{self.total_sessions} sessions running"
        )
        for ts in self.tasks:
            status_icon = "●" if ts.running_count > 0 else "○"
            lines.append(
                f"  {status_icon} {ts.task.slug} [{ts.task.status.value}] "
                f"- {ts.running_count}/{ts.total_count} sessions running"
            )
            for s in ts.sessions:
                kind = s.kind.value
                lc = s.lifecycle.value
                lines.append(f"    - {s.display_name} ({kind}) [{lc}]")
                if s.research_progress:
                    rp = s.research_progress
                    lines.append(
                        f"      Progress: depth {rp.current_depth}/{rp.max_depth}, "
                        f"{rp.queries_completed} queries, "
                        f"{rp.learnings_count} learnings"
                    )
        return "\n".join(lines)


@dataclass
class WorkspaceSnapshot:
    """Snapshot of a workspace (grouped by workspace_path)."""

    workspace_path: str  # empty string = "no workspace"
    tasks: list[TaskSnapshot] = field(default_factory=list)
    standalone: bool = False  # True if from WorkspaceRepo (not task-derived)
    workspace_id: str | None = None  # MongoDB id for standalone workspaces
    display_name: str = ""  # custom display name for standalone workspaces


class DashboardService:
    """Builds snapshots of the system state for dashboard rendering."""

    def __init__(
        self,
        task_repo: TaskRepo,
        session_repo: SessionRepo,
        workspace_repo: WorkspaceRepo | None = None,
    ) -> None:
        self._task_repo = task_repo
        self._session_repo = session_repo
        self._workspace_repo = workspace_repo
        self._snapshot_cache: DashboardSnapshot | None = None
        self._snapshot_cache_time: datetime | None = None
        self._cache_ttl_seconds = 5

    async def load_snapshot(self) -> DashboardSnapshot:
        """Build a complete system snapshot.

        Uses a 5-second TTL cache to avoid rebuilding on every coordinator message.
        """
        now = datetime.now(timezone.utc)

        # Return cached snapshot if still fresh
        if self._snapshot_cache and self._snapshot_cache_time:
            age_seconds = (now - self._snapshot_cache_time).total_seconds()
            if age_seconds < self._cache_ttl_seconds:
                return self._snapshot_cache

        # Rebuild snapshot
        tasks = await self._task_repo.list_tasks(include_archived=False)

        # Parallelize session fetches to avoid N+1 queries
        session_fetch_tasks = [
            self._session_repo.list_by_task(task.id) for task in tasks
        ]
        all_sessions = await asyncio.gather(*session_fetch_tasks)

        total_running = 0
        total_sessions = 0
        task_snapshots = []

        for task, sessions in zip(tasks, all_sessions):
            ts = TaskSnapshot(task=task, sessions=sessions)
            task_snapshots.append(ts)
            total_running += ts.running_count
            total_sessions += ts.total_count

        snapshot = DashboardSnapshot(
            tasks=task_snapshots,
            total_running=total_running,
            total_sessions=total_sessions,
        )

        # Cache the snapshot
        self._snapshot_cache = snapshot
        self._snapshot_cache_time = now

        return snapshot

    async def load_workspaces(self) -> list[WorkspaceSnapshot]:
        """Build workspace snapshots grouped by workspace_path.

        Merges task-derived workspaces with standalone workspaces from the
        workspace repo. Standalone workspaces whose path already appears in
        task-derived groups are skipped (tasks already cover them).
        """
        tasks = await self._task_repo.list_tasks(include_archived=False)

        groups: dict[str, list[Task]] = {}
        for task in tasks:
            key = task.workspace_path or ""
            groups.setdefault(key, []).append(task)

        # Parallelize session fetches to avoid N+1 queries
        all_session_tasks = [
            self._session_repo.list_by_task(task.id) for task in tasks
        ]
        all_sessions_list = await asyncio.gather(*all_session_tasks)

        # Build a task_id -> sessions mapping
        sessions_by_task_id = {
            task.id: sessions for task, sessions in zip(tasks, all_sessions_list)
        }

        workspaces = []
        seen_paths: set[str] = set()
        for path, group_tasks in sorted(groups.items()):
            task_snapshots = []
            for task in group_tasks:
                sessions = sessions_by_task_id.get(task.id, [])
                task_snapshots.append(TaskSnapshot(task=task, sessions=sessions))
            workspaces.append(
                WorkspaceSnapshot(workspace_path=path, tasks=task_snapshots)
            )
            if path:
                seen_paths.add(path)

        # Merge standalone workspaces from the workspace repo
        if self._workspace_repo:
            standalone = await self._workspace_repo.list_all()
            for ws in standalone:
                if ws.path in seen_paths:
                    continue
                workspaces.append(
                    WorkspaceSnapshot(
                        workspace_path=ws.path,
                        standalone=True,
                        workspace_id=ws.id,
                        display_name=ws.display_name,
                    )
                )

        return workspaces
