"""Header bar widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static


class HeaderBar(Static):
    """Top header bar showing app name and status summary."""

    def __init__(self, running: int = 0, total: int = 0, **kwargs) -> None:
        super().__init__(**kwargs)
        self._running = running
        self._total = total

    def compose(self) -> ComposeResult:
        yield Static(self._render_text(), id="header-text")

    def _render_text(self) -> str:
        return (
            f"  agentbench"
            f"{'':>40}"
            f"[{self._running}/{self._total} sessions running]"
        )

    def update_counts(self, running: int, total: int) -> None:
        self._running = running
        self._total = total
        try:
            self.query_one("#header-text", Static).update(self._render_text())
        except Exception:
            pass
