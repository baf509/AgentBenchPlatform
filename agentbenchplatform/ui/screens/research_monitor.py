"""Research monitor screen."""

from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.widgets import Footer, RichLog, Static

from agentbenchplatform.models.session import SessionKind, SessionLifecycle
from agentbenchplatform.ui.screens.base import BaseScreen

logger = logging.getLogger(__name__)


class ResearchMonitorScreen(BaseScreen):
    """Monitor active research sessions."""

    BINDINGS = [
        ("escape", "pop_screen", "Back"),
        ("q", "quit", "Quit"),
        ("f5", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("Research Monitor", id="research-title")
        yield RichLog(id="research-log", wrap=True, markup=False)
        yield Footer()

    async def on_mount(self) -> None:
        await self._refresh()
        self.set_interval(3.0, self._refresh)

    async def _refresh(self) -> None:
        if not self.has_context():
            return

        try:
            sessions = await self.ctx.session_service.list_sessions()
            research_sessions = [
                s for s in sessions if s.kind == SessionKind.RESEARCH_AGENT
            ]

            log = self.query_one("#research-log", RichLog)
            log.clear()

            if not research_sessions:
                log.write("[No research sessions]")
                return

            for s in research_sessions:
                icon = "●" if s.lifecycle == SessionLifecycle.RUNNING else "○"
                log.write(f"{icon} {s.display_name} [{s.lifecycle.value}]")

                if s.research_progress:
                    rp = s.research_progress
                    pct = 0
                    if rp.max_depth > 0:
                        pct = int(rp.current_depth / rp.max_depth * 100)
                    bar_w = 20
                    filled = int(bar_w * pct / 100)
                    bar = "█" * filled + "░" * (bar_w - filled)
                    log.write(f"  [{bar}] {pct}%")
                    log.write(
                        f"  Depth: {rp.current_depth}/{rp.max_depth}, "
                        f"Queries: {rp.queries_completed}, "
                        f"Learnings: {rp.learnings_count}"
                    )
                log.write("")
        except Exception:
            logger.debug("Could not refresh research monitor", exc_info=True)

    def action_refresh(self) -> None:
        self.run_worker(self._refresh())

    def action_pop_screen(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()
