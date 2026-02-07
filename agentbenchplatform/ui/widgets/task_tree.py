"""Task tree widget."""

from __future__ import annotations

from textual.widgets import Tree

from agentbenchplatform.services.dashboard_service import DashboardSnapshot


class TaskTree(Tree):
    """Tree widget showing tasks and their sessions."""

    def __init__(self) -> None:
        super().__init__("Tasks", id="task-tree")

    def update_from_snapshot(self, snapshot: DashboardSnapshot) -> None:
        """Rebuild tree from a dashboard snapshot."""
        self.clear()

        for ts in snapshot.tasks:
            task = ts.task
            status = task.status.value
            running = ts.running_count
            total = ts.total_count

            label = f"{task.slug} [{status}] ({running}/{total})"
            task_node = self.root.add(label, expand=True)
            task_node.data = {"type": "task", "slug": task.slug, "id": task.id}

            for session in ts.sessions:
                lc = session.lifecycle.value
                kind = session.kind.value
                icon = self._lifecycle_icon(lc)
                sess_label = f"{icon} {session.display_name} ({kind}) [{lc}]"
                sess_node = task_node.add_leaf(sess_label)
                sess_node.data = {"type": "session", "id": session.id}

        self.root.expand()

    @staticmethod
    def _lifecycle_icon(lifecycle: str) -> str:
        icons = {
            "running": "●",
            "paused": "◐",
            "pending": "○",
            "completed": "✓",
            "failed": "✗",
            "archived": "▪",
        }
        return icons.get(lifecycle, "?")
