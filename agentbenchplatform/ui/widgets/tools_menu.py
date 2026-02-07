"""Tools menu widget for the dashboard."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option


class ToolsMenu(Vertical):
    """Menu widget showing navigable list of tools/screens."""

    class Selected(Message):
        """Emitted when a menu item is selected."""

        def __init__(self, key: str) -> None:
            super().__init__()
            self.key = key

    MENU_ITEMS = [
        ("workspaces", "\\[w] Workspaces"),
        ("research", "\\[r] Research Monitor"),
        ("coordinator", "\\[c] Coordinator Chat"),
        ("memory", "\\[m] Shared Memory"),
        ("file_browser", "\\[b] Browse Files"),
        ("usage", "\\[u] Usage Monitor"),
        ("db_explorer", "\\[n] DB Explorer"),
        ("mcp", "\\[i] MCP Servers (Coming Soon)"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("Tools", classes="panel-title")
        option_list = OptionList(
            *[Option(label, id=key) for key, label in self.MENU_ITEMS],
            id="tools-menu",
        )
        yield option_list

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """Forward selection as a ToolsMenu.Selected message."""
        option_id = event.option.id
        if option_id:
            self.post_message(self.Selected(option_id))
