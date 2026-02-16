"""Simple confirmation dialog screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmDialog(ModalScreen[bool]):
    """Modal dialog that asks the user to confirm a destructive action."""

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
    }
    #confirm-container {
        width: 50;
        height: auto;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    #confirm-label {
        width: 100%;
        margin-bottom: 1;
    }
    #confirm-buttons {
        width: 100%;
    }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Center(id="confirm-container"):
            yield Label(self._message, id="confirm-label")
            with Center(id="confirm-buttons"):
                yield Button("Confirm", variant="error", id="confirm-yes")
                yield Button("Cancel", variant="default", id="confirm-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")
