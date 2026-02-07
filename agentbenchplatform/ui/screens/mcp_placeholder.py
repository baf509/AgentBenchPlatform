"""MCP servers placeholder screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Footer, Static

from agentbenchplatform.ui.screens.base import BaseScreen


class McpPlaceholderScreen(BaseScreen):
    """Placeholder screen for future MCP server management."""

    BINDINGS = [
        ("escape", "pop_screen", "Back"),
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("MCP Servers", id="mcp-title")
        yield Static(
            "Coming soon — MCP server management will be available here.",
            id="mcp-info",
        )
        yield Footer()

    def action_pop_screen(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()
