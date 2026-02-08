"""Main dashboard screen."""

from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Footer, Static, Tree

from agentbenchplatform.ui.screens.base import BaseScreen
from agentbenchplatform.ui.widgets.header_bar import HeaderBar
from agentbenchplatform.ui.widgets.log_viewer import LogViewer
from agentbenchplatform.ui.widgets.task_tree import TaskTree
from agentbenchplatform.ui.widgets.tools_menu import ToolsMenu
from agentbenchplatform.ui.widgets.vitals_panel import VitalsPanel

logger = logging.getLogger(__name__)


class DashboardScreen(BaseScreen):
    """Main dashboard screen composing all widgets."""

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("t", "new_task", "New Task"),
        ("s", "new_session", "New Session"),
        ("a", "attach_session", "Attach"),
        ("x", "stop_session", "Stop"),
        ("p", "pause_resume", "Pause/Resume"),
        ("delete", "delete", "Delete"),
        ("d", "open_detail", "Detail"),
        ("r", "research", "Research"),
        ("c", "coordinator", "Coordinator"),
        ("w", "workspaces", "Workspaces"),
        ("m", "memory", "Memory"),
        ("b", "file_browser", "Browse"),
        ("u", "usage", "Usage"),
        ("n", "db_explorer", "DB Explorer"),
        ("i", "mcp", "MCP"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._selected_session_id: str = ""
        self._selected_task_id: str = ""
        self._selected_tmux_target: str = ""  # cached for synchronous attach
        self._last_snapshot = None  # cached for vitals refresh

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="header-bar")

        with Container(id="main-container"):
            with Vertical(id="task-tree-panel"):
                yield Static("Tasks", classes="panel-title")
                yield TaskTree()

            with Vertical(id="detail-panel"):
                yield Static("Session Detail", classes="panel-title")
                yield Static("Select a task or session", id="session-detail")
                yield LogViewer()

            with Vertical(id="tools-panel"):
                yield ToolsMenu()

            with Vertical(id="coordinator-panel"):
                yield Static("System Vitals", classes="panel-title")
                yield VitalsPanel(id="vitals-text")

        yield Footer()

    def on_mount(self) -> None:
        """Start periodic refresh."""
        self.set_interval(2.0, self._refresh_snapshot)
        self.set_interval(5.0, self._refresh_vitals)

    async def _refresh_snapshot(self) -> None:
        """Refresh dashboard data from services."""
        app = self.app
        if not hasattr(app, "ctx") or app.ctx is None:
            detail = self.query_one("#session-detail", Static)
            detail.update(
                "Not connected to MongoDB.\n\n"
                "Check that MongoDB is running and restart the dashboard."
            )
            return

        try:
            snapshot = await app.ctx.dashboard_service.load_snapshot()
            self._last_snapshot = snapshot

            # Update task tree
            tree = self.query_one(TaskTree)
            tree.update_from_snapshot(snapshot)

            # Update header
            header = self.query_one(HeaderBar)
            header.update_counts(snapshot.total_running, snapshot.total_sessions)

            # Update log viewer if a session is selected
            await self._refresh_log_viewer()

        except Exception:
            logger.exception("Error refreshing dashboard snapshot")
            detail = self.query_one("#session-detail", Static)
            detail.update("Error loading dashboard data. Check logs for details.")

    async def _refresh_log_viewer(self) -> None:
        """Refresh log viewer with output from the selected session."""
        if not self._selected_session_id:
            return
        if not self.has_context():
            return

        try:
            output = await self.ctx.session_service.get_session_output(
                self._selected_session_id,
                lines=50,
            )
            viewer = self.query_one(LogViewer)
            viewer.update_output(output)
        except Exception:
            logger.debug("Could not refresh log viewer", exc_info=True)

    async def _refresh_vitals(self) -> None:
        """Refresh the vitals panel (runs on 5s interval)."""
        app = self.app
        if not hasattr(app, "ctx") or app.ctx is None:
            return

        try:
            usage_totals = await app.ctx.usage_repo.aggregate_recent(hours=6)

            last_coordinator_dt = None
            convos = await app.ctx.coordinator_history_repo.list_conversations()
            if convos:
                updated_at = convos[0].get("updated_at")
                if isinstance(updated_at, str):
                    from datetime import datetime

                    try:
                        last_coordinator_dt = datetime.fromisoformat(updated_at)
                    except ValueError:
                        last_coordinator_dt = None
                else:
                    last_coordinator_dt = updated_at

            vitals = self.query_one("#vitals-text", VitalsPanel)
            vitals.update_vitals(self._last_snapshot, usage_totals, last_coordinator_dt)
        except Exception:
            logger.debug("Error refreshing vitals", exc_info=True)

    # --- Tree node selection ---

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle selection of a task or session in the tree."""
        node = event.node
        data = node.data
        if not data:
            return

        if data.get("type") == "task":
            self._selected_task_id = data.get("id", "")
            self._selected_session_id = ""
            self._selected_tmux_target = ""
            self.run_worker(self._show_task_detail(data.get("slug", ""), data.get("id", "")))

        elif data.get("type") == "session":
            self._selected_session_id = data.get("id", "")
            self.run_worker(self._show_session_detail(data.get("id", "")))

    async def _show_task_detail(self, slug: str, task_id: str) -> None:
        """Update the detail panel with task info."""
        detail = self.query_one("#session-detail", Static)

        if not self.has_context():
            return

        task = await self.ctx.task_service.get_task(slug)
        if not task:
            detail.update(f"Task not found: {slug}")
            return

        sessions = await self.ctx.session_service.list_sessions(task_id=task_id)

        lines = [
            f"Task: {task.title}",
            f"  Slug: {task.slug}",
            f"  Status: {task.status.value}",
        ]
        if task.description:
            lines.append(f"  Description: {task.description}")
        if task.workspace_path:
            lines.append(f"  Workspace: {task.workspace_path}")
        if task.tags:
            lines.append(f"  Tags: {', '.join(task.tags)}")
        lines.append(f"  Sessions: {len(sessions)}")
        for s in sessions:
            icon = "\u25cf" if s.lifecycle.value == "running" else "\u25cb"
            lines.append(f"    {icon} {s.display_name} [{s.lifecycle.value}]")

        lines.append("")
        lines.append("Actions: [s] New Session  [Del] Delete  [d] Full Detail")

        detail.update("\n".join(lines))

        # Clear log viewer when switching to task view
        viewer = self.query_one(LogViewer)
        viewer.update_output("")

    async def _show_session_detail(self, session_id: str) -> None:
        """Update the detail panel and log viewer with session info."""
        detail = self.query_one("#session-detail", Static)

        if not self.has_context():
            return

        session = await self.ctx.session_service.get_session(session_id)
        if not session:
            detail.update(f"Session not found: {session_id}")
            return

        self._selected_task_id = session.task_id
        alive = await self.ctx.session_service.check_session_liveness(session_id)

        # Cache tmux target for synchronous attach
        att = session.attachment
        if att.tmux_session:
            self._selected_tmux_target = f"{att.tmux_session}:{att.tmux_window}"
        else:
            self._selected_tmux_target = ""

        lines = [
            f"Session: {session.display_name}",
            f"  Kind: {session.kind.value}",
            f"  Lifecycle: {session.lifecycle.value}",
            f"  Agent: {session.agent_backend}",
            f"  PID: {session.attachment.pid or 'N/A'} ({'alive' if alive else 'dead'})",
        ]
        if session.attachment.tmux_session:
            lines.append(
                f"  tmux: {session.attachment.tmux_session}:{session.attachment.tmux_window}"
            )
        if session.research_progress:
            rp = session.research_progress
            lines.append(
                f"  Research: depth {rp.current_depth}/{rp.max_depth}, "
                f"{rp.queries_completed} queries, {rp.learnings_count} learnings"
            )

        # Show available actions
        lines.append("")
        actions = []
        if session.attachment.tmux_session:
            actions.append("[a] Attach tmux")
        if not session.lifecycle.is_terminal:
            actions.append("[x] Stop")
            if session.lifecycle.value == "running":
                actions.append("[p] Pause")
            elif session.lifecycle.value == "paused":
                actions.append("[p] Resume")
        actions.append("[Del] Delete")
        actions.append("[d] Full Detail")
        lines.append("Actions: " + "  ".join(actions))

        detail.update("\n".join(lines))

        # Load session output into log viewer
        await self._refresh_log_viewer()

    # --- Session actions ---

    async def action_attach_session(self) -> None:
        """Attach to the selected session's tmux pane.

        Suspends the TUI and drops into the tmux pane.
        Detach with ctrl+b d to return to the dashboard.
        """
        import asyncio
        import os
        import subprocess

        if not self._selected_session_id:
            self.notify("Select a session first", severity="warning")
            return

        if not self._selected_tmux_target:
            self.notify("Session has no tmux attachment", severity="warning")
            return

        # Check if the tmux session still exists
        tmux_session = self._selected_tmux_target.split(":")[0]
        check = await asyncio.create_subprocess_exec(
            "tmux",
            "has-session",
            "-t",
            tmux_session,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await check.wait()
        if check.returncode != 0:
            self.notify(
                f"tmux session no longer exists: {tmux_session}",
                severity="error",
            )
            return

        # Use switch-client when already inside tmux, attach-session otherwise
        inside_tmux = bool(os.environ.get("TMUX"))

        if inside_tmux:
            # switch-client works from within tmux without nesting issues
            subprocess.call(["tmux", "switch-client", "-t", self._selected_tmux_target])
        else:
            # Suspend TUI, attach to tmux (blocking), then resume TUI
            with self.app.suspend():
                subprocess.call(["tmux", "attach-session", "-t", self._selected_tmux_target])

    def action_stop_session(self) -> None:
        """Stop the selected session."""
        if not self._selected_session_id:
            self.notify("Select a session first", severity="warning")
            return
        self.run_worker(self._stop_session())

    async def _stop_session(self) -> None:
        if not self.has_context():
            return

        try:
            session = await self.ctx.session_service.stop_session(self._selected_session_id)
        except Exception as e:
            self.notify(f"Error stopping session: {e}", severity="error")
            return

        if session:
            self.notify(f"Stopped: {session.display_name}")
            # Clear selection so periodic refresh doesn't try to
            # capture output from the now-killed tmux pane
            self._selected_session_id = ""
            self._selected_tmux_target = ""
            detail = self.query_one("#session-detail", Static)
            detail.update(
                f"Session stopped: {session.display_name}\n"
                f"  Final state: {session.lifecycle.value}\n\n"
                "Select another session or create a new one."
            )
            viewer = self.query_one(LogViewer)
            viewer.update_output("")
        else:
            self.notify("Session not found", severity="error")

    def action_pause_resume(self) -> None:
        """Pause or resume the selected session."""
        if not self._selected_session_id:
            self.notify("Select a session first", severity="warning")
            return
        self.run_worker(self._pause_resume())

    async def _pause_resume(self) -> None:
        if not self.has_context():
            return

        try:
            session = await self.ctx.session_service.get_session(self._selected_session_id)
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")
            return

        if not session:
            self.notify("Session not found", severity="error")
            return

        try:
            if session.lifecycle.value == "running":
                result = await self.ctx.session_service.pause_session(self._selected_session_id)
                if result:
                    self.notify(f"Paused: {result.display_name}")
            elif session.lifecycle.value == "paused":
                result = await self.ctx.session_service.resume_session(self._selected_session_id)
                if result:
                    self.notify(f"Resumed: {result.display_name}")
            else:
                self.notify(
                    f"Cannot pause/resume: session is {session.lifecycle.value}",
                    severity="warning",
                )
                return
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")
            return

        await self._show_session_detail(self._selected_session_id)

    def action_delete(self) -> None:
        """Delete the selected task or archive the selected session."""
        if self._selected_session_id:
            self.run_worker(self._archive_session())
        elif self._selected_task_id:
            self.run_worker(self._delete_task())
        else:
            self.notify("Select a task or session first", severity="warning")

    async def _archive_session(self) -> None:
        if not self.has_context():
            return

        try:
            session = await self.ctx.session_service.archive_session(self._selected_session_id)
        except Exception as e:
            self.notify(f"Error archiving session: {e}", severity="error")
            return

        if session:
            self.notify(f"Archived: {session.display_name}")
            self._selected_session_id = ""
            self._selected_tmux_target = ""
            detail = self.query_one("#session-detail", Static)
            detail.update("Session archived. Select another session or create a new one.")
            viewer = self.query_one(LogViewer)
            viewer.update_output("")
        else:
            self.notify("Session not found", severity="error")

    async def _delete_task(self) -> None:
        if not self.has_context():
            return

        try:
            task = await self.ctx.task_service.get_task_by_id(self._selected_task_id)
            if not task:
                self.notify("Task not found", severity="error")
                return

            result = await self.ctx.task_service.delete_task(task.slug)
        except Exception as e:
            self.notify(f"Error deleting task: {e}", severity="error")
            return

        if result:
            self.notify(f"Deleted: {result.title}")
            self._selected_task_id = ""
            self._selected_session_id = ""
            self._selected_tmux_target = ""
            detail = self.query_one("#session-detail", Static)
            detail.update("Task deleted. Select another task or create a new one.")
            viewer = self.query_one(LogViewer)
            viewer.update_output("")
        else:
            self.notify("Failed to delete task", severity="error")

    def action_open_detail(self) -> None:
        """Open full detail screen for the selected session or task."""
        if self._selected_session_id:
            from agentbenchplatform.ui.screens.session_detail import SessionDetailScreen

            self.app.push_screen(SessionDetailScreen(session_id=self._selected_session_id))
        elif self._selected_task_id:
            from agentbenchplatform.ui.screens.task_detail import TaskDetailScreen

            # Find the slug for the task ID
            self.run_worker(self._open_task_detail())
        else:
            self.notify("Select a task or session first", severity="warning")

    async def _open_task_detail(self) -> None:
        if not self.has_context():
            return

        task = await self.ctx.task_service.get_task_by_id(self._selected_task_id)
        if task:
            from agentbenchplatform.ui.screens.task_detail import TaskDetailScreen

            self.app.push_screen(TaskDetailScreen(task_slug=task.slug))
        else:
            self.notify("Task not found", severity="error")

    # --- Navigation actions ---

    def action_quit(self) -> None:
        self.app.exit()

    def action_new_session(self) -> None:
        """Open the new session dialog."""
        from agentbenchplatform.ui.screens.new_session import NewSessionScreen

        def on_dismiss(result: bool) -> None:
            if result:
                self.run_worker(self._refresh_snapshot())

        self.app.push_screen(NewSessionScreen(), callback=on_dismiss)

    def action_new_task(self) -> None:
        """Open the new task dialog."""
        from agentbenchplatform.ui.screens.new_task import NewTaskScreen

        def on_dismiss(result: bool) -> None:
            if result:
                self.run_worker(self._refresh_snapshot())

        self.app.push_screen(NewTaskScreen(), callback=on_dismiss)

    def action_coordinator(self) -> None:
        from agentbenchplatform.ui.screens.coordinator_chat import CoordinatorChatScreen

        self.app.push_screen(CoordinatorChatScreen())

    def action_research(self) -> None:
        from agentbenchplatform.ui.screens.research_monitor import ResearchMonitorScreen

        self.app.push_screen(ResearchMonitorScreen())

    def action_workspaces(self) -> None:
        from agentbenchplatform.ui.screens.workspaces import WorkspacesScreen

        self.app.push_screen(WorkspacesScreen())

    def action_memory(self) -> None:
        from agentbenchplatform.ui.screens.memory_browser import MemoryBrowserScreen

        self.app.push_screen(MemoryBrowserScreen())

    def action_file_browser(self) -> None:
        from agentbenchplatform.ui.screens.file_browser import FileBrowserScreen

        self.app.push_screen(FileBrowserScreen())

    def action_usage(self) -> None:
        from agentbenchplatform.ui.screens.usage_monitor import UsageMonitorScreen

        self.app.push_screen(UsageMonitorScreen())

    def action_db_explorer(self) -> None:
        from agentbenchplatform.ui.screens.db_explorer import DatabaseExplorerScreen

        self.app.push_screen(DatabaseExplorerScreen())

    def action_mcp(self) -> None:
        from agentbenchplatform.ui.screens.mcp_placeholder import McpPlaceholderScreen

        self.app.push_screen(McpPlaceholderScreen())

    def on_tools_menu_selected(self, event: ToolsMenu.Selected) -> None:
        """Handle selection from the tools menu widget."""
        actions = {
            "workspaces": self.action_workspaces,
            "memory": self.action_memory,
            "research": self.action_research,
            "coordinator": self.action_coordinator,
            "file_browser": self.action_file_browser,
            "usage": self.action_usage,
            "db_explorer": self.action_db_explorer,
            "mcp": self.action_mcp,
        }
        handler = actions.get(event.key)
        if handler:
            handler()
