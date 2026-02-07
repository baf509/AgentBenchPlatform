"""Task detail screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Footer, Static

from agentbenchplatform.ui.screens.base import BaseScreen


class TaskDetailScreen(BaseScreen):
    """Shows detailed info about a specific task."""

    BINDINGS = [
        ("escape", "pop_screen", "Back"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, task_slug: str = "") -> None:
        super().__init__()
        self._task_slug = task_slug

    def compose(self) -> ComposeResult:
        yield Static(f"Task: {self._task_slug}", id="task-title")
        yield Static("Loading...", id="task-info")
        yield Footer()

    async def on_mount(self) -> None:
        if not self.has_context():
            return

        task = await self.ctx.task_service.get_task(self._task_slug)
        if not task:
            self.query_one("#task-info", Static).update(f"Task not found: {self._task_slug}")
            return

        sessions = await self.ctx.session_service.list_sessions(task_id=task.id)

        lines = [
            f"Title: {task.title}",
            f"Status: {task.status.value}",
            f"Description: {task.description or '(none)'}",
            f"Workspace: {task.workspace_path or '(none)'}",
            f"Tags: {', '.join(task.tags) or '(none)'}",
            f"Created: {task.created_at.isoformat()}",
            "",
            f"Sessions ({len(sessions)}):",
        ]
        for s in sessions:
            lines.append(f"  {s.id} ({s.kind.value}) [{s.lifecycle.value}] {s.display_name}")

        self.query_one("#task-info", Static).update("\n".join(lines))

    def action_pop_screen(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()
