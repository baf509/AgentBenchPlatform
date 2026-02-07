"""Research progress widget."""

from __future__ import annotations

from textual.widgets import Static

from agentbenchplatform.models.session import ResearchProgress


class ResearchProgressWidget(Static):
    """Shows progress for a research session."""

    def __init__(self) -> None:
        super().__init__("No research in progress")

    def update_progress(self, progress: ResearchProgress | None) -> None:
        if not progress:
            self.update("No research in progress")
            return

        pct = 0
        if progress.max_depth > 0:
            pct = int(progress.current_depth / progress.max_depth * 100)

        bar_width = 20
        filled = int(bar_width * pct / 100)
        bar = "█" * filled + "░" * (bar_width - filled)

        lines = [
            f"Research Progress [{bar}] {pct}%",
            f"  Depth: {progress.current_depth}/{progress.max_depth}",
            f"  Queries: {progress.queries_completed}",
            f"  Learnings: {progress.learnings_count}",
        ]
        self.update("\n".join(lines))
