"""Session detail screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Footer, RichLog, Static

from agentbenchplatform.ui.screens.base import BaseScreen


class SessionDetailScreen(BaseScreen):
    """Shows detailed info and live output for a session."""

    BINDINGS = [
        ("escape", "pop_screen", "Back"),
        ("q", "quit", "Quit"),
        ("f5", "refresh", "Refresh"),
    ]

    def __init__(self, session_id: str = "") -> None:
        super().__init__()
        self._session_id = session_id

    def compose(self) -> ComposeResult:
        yield Static(f"Session: {self._session_id}", id="session-title")
        yield Static("Loading...", id="session-info")
        yield RichLog(id="session-output", wrap=True, markup=False)
        yield Footer()

    async def on_mount(self) -> None:
        await self._load_data()
        self.set_interval(3.0, self._refresh_output)

    async def _load_data(self) -> None:
        if not self.has_context():
            return

        session = await self.ctx.session_service.get_session(self._session_id)
        if not session:
            self.query_one("#session-info", Static).update("Session not found")
            return

        alive = await self.ctx.session_service.check_session_liveness(self._session_id)

        lines = [
            f"Display: {session.display_name}",
            f"Kind: {session.kind.value}",
            f"Lifecycle: {session.lifecycle.value}",
            f"Agent: {session.agent_backend}",
            f"PID: {session.attachment.pid or 'N/A'} ({'alive' if alive else 'dead'})",
        ]
        if session.attachment.tmux_session:
            lines.append(
                f"tmux: {session.attachment.tmux_session}:{session.attachment.tmux_window}"
            )
        self.query_one("#session-info", Static).update("\n".join(lines))

        await self._refresh_output()

    async def _refresh_output(self) -> None:
        if not self.has_context():
            return
        try:
            output = await self.ctx.session_service.get_session_output(
                self._session_id, lines=50
            )
            log = self.query_one("#session-output", RichLog)
            log.clear()
            for line in output.splitlines():
                log.write(line)
        except Exception:
            pass

    def action_refresh(self) -> None:
        self.run_worker(self._load_data())

    def action_pop_screen(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()
