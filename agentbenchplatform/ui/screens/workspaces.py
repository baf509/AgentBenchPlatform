"""Workspaces browser screen."""

from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.widgets import Footer, Static, Tree

from agentbenchplatform.ui.screens.base import BaseScreen
from agentbenchplatform.ui.screens.confirm_dialog import ConfirmDialog

logger = logging.getLogger(__name__)


class WorkspacesScreen(BaseScreen):
    """Browse tasks grouped by workspace path."""

    BINDINGS = [
        ("escape", "pop_screen", "Back"),
        ("q", "quit", "Quit"),
        ("f5", "refresh", "Refresh"),
        ("a", "add_workspace", "Add"),
        ("delete", "delete_workspace", "Delete"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("Workspaces", id="workspaces-title")
        yield Tree("Workspaces", id="workspaces-tree")
        yield Footer()

    async def on_mount(self) -> None:
        await self._refresh()

    async def _refresh(self) -> None:
        if not self.has_context():
            return

        try:
            workspaces = await self.ctx.dashboard_service.load_workspaces()
            tree = self.query_one("#workspaces-tree", Tree)
            tree.clear()

            if not workspaces:
                tree.root.add_leaf("[No workspaces]")
                tree.root.expand()
                return

            for ws in workspaces:
                if ws.standalone:
                    label = ws.display_name or ws.workspace_path
                    if ws.display_name and ws.display_name != ws.workspace_path:
                        ws_label = f"{label} ({ws.workspace_path})"
                    else:
                        ws_label = ws.workspace_path
                else:
                    path_label = ws.workspace_path or "(no workspace)"
                    task_count = len(ws.tasks)
                    session_count = sum(ts.total_count for ts in ws.tasks)
                    ws_label = (
                        f"{path_label} "
                        f"[{task_count} task{'s' if task_count != 1 else ''}, "
                        f"{session_count} session{'s' if session_count != 1 else ''}]"
                    )

                ws_node = tree.root.add(ws_label, expand=True)
                ws_node.data = {
                    "type": "workspace",
                    "path": ws.workspace_path,
                    "standalone": ws.standalone,
                    "workspace_id": ws.workspace_id,
                }

                for ts in ws.tasks:
                    task = ts.task
                    running = ts.running_count
                    status = task.status.value
                    task_label = f"{task.slug} [{status}]"
                    if running:
                        task_label += f" ({running} running)"
                    task_node = ws_node.add_leaf(task_label)
                    task_node.data = {
                        "type": "task",
                        "slug": task.slug,
                        "id": task.id,
                    }

            tree.root.expand()
        except Exception:
            logger.exception("Could not refresh workspaces")

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Push TaskDetailScreen when a task node is selected."""
        data = event.node.data
        if not data or data.get("type") != "task":
            return

        slug = data.get("slug", "")
        if slug:
            from agentbenchplatform.ui.screens.task_detail import TaskDetailScreen

            self.app.push_screen(TaskDetailScreen(task_slug=slug))

    def action_add_workspace(self) -> None:
        from agentbenchplatform.ui.screens.add_workspace import AddWorkspaceScreen

        def _on_dismiss(result: bool | None) -> None:
            if result:
                self.run_worker(self._refresh())

        self.app.push_screen(AddWorkspaceScreen(), callback=_on_dismiss)

    def action_delete_workspace(self) -> None:
        tree = self.query_one("#workspaces-tree", Tree)
        node = tree.cursor_node
        if node is None or not node.data or node.data.get("type") != "workspace":
            self.app.notify("Select a workspace node to delete.", severity="warning")
            return
        if not node.data.get("standalone"):
            self.app.notify(
                "Only standalone workspaces can be deleted. "
                "Task-derived workspaces are managed through tasks.",
                severity="warning",
            )
            return
        self.app.push_screen(
            ConfirmDialog("Delete this workspace?"),
            callback=lambda confirmed: (
                self.run_worker(self._delete_workspace()) if confirmed else None
            ),
        )

    async def _delete_workspace(self) -> None:
        if not self.has_context():
            return

        tree = self.query_one("#workspaces-tree", Tree)
        node = tree.cursor_node
        if node is None or not node.data:
            return

        workspace_id = node.data.get("workspace_id")
        if not workspace_id:
            return

        deleted = await self.ctx.workspace_repo.delete(workspace_id)
        if deleted:
            self.app.notify("Workspace removed.")
            await self._refresh()
        else:
            self.app.notify("Could not delete workspace.", severity="error")

    def action_refresh(self) -> None:
        self.run_worker(self._refresh())

    def action_pop_screen(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()
