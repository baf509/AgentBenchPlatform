"""File browser screen for browsing the filesystem."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.widgets import DirectoryTree, Footer, Static

from agentbenchplatform.ui.screens.base import BaseScreen


class FileBrowserScreen(BaseScreen):
    """Browse the filesystem using a directory tree."""

    BINDINGS = [
        ("escape", "pop_screen", "Back"),
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("Selected: (none)", id="file-browser-path")
        yield DirectoryTree(str(Path.home()), id="file-browser-tree")
        yield Footer()

    def on_directory_tree_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        """Update the path display when a directory is selected."""
        path_display = self.query_one("#file-browser-path", Static)
        path_display.update(f"Selected: {event.path}")

    def action_pop_screen(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()
