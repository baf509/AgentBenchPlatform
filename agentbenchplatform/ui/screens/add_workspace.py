"""Add workspace screen: register a project directory as a standalone workspace."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, Static


class AddWorkspaceScreen(ModalScreen[bool]):
    """Modal screen to add a standalone workspace."""

    CSS = """
    AddWorkspaceScreen {
        align: center middle;
    }
    #add-ws-dialog {
        width: 70;
        height: auto;
        max-height: 80%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #add-ws-dialog Label {
        margin: 1 0 0 0;
    }
    #add-ws-dialog Input {
        margin: 0 0 1 0;
    }
    .btn-row {
        height: 3;
        margin-top: 1;
        align: center middle;
    }
    .btn-row Button {
        margin: 0 1;
    }
    #aw-status {
        height: auto;
        color: $error;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="add-ws-dialog"):
            yield Static("Add Workspace", classes="panel-title")
            yield Label("Path")
            yield Input(placeholder="/path/to/project...", id="aw-path")
            yield Label("Display Name (optional)")
            yield Input(placeholder="Defaults to directory name", id="aw-name")
            yield Static("", id="aw-status")
            with Horizontal(classes="btn-row"):
                yield Button("Add Workspace", variant="primary", id="aw-submit")
                yield Button("Cancel", variant="default", id="aw-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#aw-path", Input).focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "aw-cancel":
            self.dismiss(False)
            return

        if event.button.id == "aw-submit":
            await self._submit()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        await self._submit()

    async def _submit(self) -> None:
        status = self.query_one("#aw-status", Static)
        raw_path = self.query_one("#aw-path", Input).value.strip()
        name = self.query_one("#aw-name", Input).value.strip()

        if not raw_path:
            status.update("Path is required.")
            return

        resolved = Path(raw_path).expanduser().resolve()
        if not resolved.exists():
            status.update(f"Path does not exist: {resolved}")
            return
        if not resolved.is_dir():
            status.update(f"Path is not a directory: {resolved}")
            return

        abs_path = str(resolved)

        if not hasattr(self.app, "ctx") or self.app.ctx is None:
            status.update("Application context not available.")
            return

        workspace_repo = self.app.ctx.workspace_repo

        # Check for duplicate
        existing = await workspace_repo.find_by_path(abs_path)
        if existing:
            status.update(f"Workspace already registered: {abs_path}")
            return

        status.update("Adding workspace...")
        try:
            from agentbenchplatform.models.workspace import Workspace

            ws = Workspace(path=abs_path, name=name)
            await workspace_repo.insert(ws)
            self.app.notify(f"Workspace added: {resolved.name}")
            self.dismiss(True)
        except Exception as e:
            status.update(f"Error: {e}")

    def action_cancel(self) -> None:
        self.dismiss(False)
