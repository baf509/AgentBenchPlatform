"""Main Textual TUI application - connects to server via RemoteContext."""

from __future__ import annotations

from pathlib import Path

from textual.app import App

from agentbenchplatform.ui.screens.dashboard import DashboardScreen

CSS_PATH = Path(__file__).parent / "styles" / "agentbenchplatform.tcss"


class AgentBenchApp(App):
    """agentbenchplatform TUI application."""

    TITLE = "agentbenchplatform"
    CSS_PATH = str(CSS_PATH)

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.ctx = None  # RemoteContext, set in on_mount

    async def on_mount(self) -> None:
        """Connect to server via RemoteContext and show dashboard."""
        from agentbenchplatform.remote_context import RemoteContext
        from agentbenchplatform.commands._helpers import get_socket_path

        socket_path = get_socket_path()
        self.ctx = RemoteContext(socket_path)
        try:
            await self.ctx.initialize()
        except Exception as e:
            self.ctx = None
            self.notify(
                f"Server not running. Start with: agentbenchplatform server start\n({e})",
                severity="error",
            )

        self.push_screen(DashboardScreen())

    async def on_unmount(self) -> None:
        """Close RemoteContext on exit."""
        if self.ctx:
            await self.ctx.close()

    def action_quit(self) -> None:
        self.exit()
