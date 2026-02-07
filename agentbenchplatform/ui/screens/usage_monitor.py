"""Usage monitor screen — token tracking for coordinator and research."""

from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.widgets import Footer, RichLog, Static

from agentbenchplatform.models.session import SessionKind
from agentbenchplatform.ui.screens.base import BaseScreen

logger = logging.getLogger(__name__)


class UsageMonitorScreen(BaseScreen):
    """Monitor token usage across coordinator and research agents."""

    BINDINGS = [
        ("escape", "pop_screen", "Back"),
        ("q", "quit", "Quit"),
        ("f5", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("Usage Monitor", id="usage-title")
        yield RichLog(id="usage-log", wrap=True, markup=False)
        yield Footer()

    async def on_mount(self) -> None:
        await self._refresh()
        self.set_interval(5.0, self._refresh)

    async def _refresh(self) -> None:
        if not self.has_context():
            return

        try:
            log = self.query_one("#usage-log", RichLog)
            log.clear()

            usage_repo = self.ctx.usage_repo
            totals = await usage_repo.aggregate_totals()
            recent = await usage_repo.list_recent(limit=20)

            # --- Summary ---
            log.write("=== Token Usage Summary ===")
            log.write("")
            if not totals:
                log.write("  No usage data yet.")
            else:
                for key, data in sorted(totals.items()):
                    source, model = key.split(":", 1) if ":" in key else (key, "?")
                    total = data["input_tokens"] + data["output_tokens"]
                    log.write(
                        f"  {source:12s} {model:30s}  "
                        f"in={data['input_tokens']:>8,}  "
                        f"out={data['output_tokens']:>8,}  "
                        f"total={total:>9,}  "
                        f"calls={data['count']}"
                    )

            # --- Delegation stats ---
            log.write("")
            log.write("=== Delegation Stats ===")
            log.write("")
            sessions = await self.ctx.session_service.list_sessions()
            coding = [s for s in sessions if s.kind == SessionKind.CODING_AGENT]
            backend_counts: dict[str, int] = {}
            for s in coding:
                backend_counts[s.agent_backend] = backend_counts.get(s.agent_backend, 0) + 1
            if backend_counts:
                for backend, count in sorted(backend_counts.items()):
                    log.write(f"  {backend:20s} {count} session(s)")
            else:
                log.write("  No coding sessions yet.")

            # --- Recent events ---
            log.write("")
            log.write("=== Recent Events (last 20) ===")
            log.write("")
            if not recent:
                log.write("  No events yet.")
            else:
                for ev in recent:
                    ts = ev.timestamp.strftime("%H:%M:%S")
                    total = ev.input_tokens + ev.output_tokens
                    ch = f" [{ev.channel}]" if ev.channel else ""
                    log.write(
                        f"  {ts}  {ev.source:12s}{ch}  "
                        f"{ev.model:30s}  "
                        f"in={ev.input_tokens:>6,}  out={ev.output_tokens:>6,}  "
                        f"total={total:>7,}"
                    )

        except Exception:
            logger.debug("Could not refresh usage monitor", exc_info=True)

    def action_refresh(self) -> None:
        self.run_worker(self._refresh())

    def action_pop_screen(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()
