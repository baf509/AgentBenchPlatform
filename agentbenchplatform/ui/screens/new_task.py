"""New task screen: create a new task with title and description."""

from __future__ import annotations

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, Static


class NewTaskScreen(ModalScreen[bool]):
    """Modal screen to create a new task."""

    CSS = """
    NewTaskScreen {
        align: center middle;
    }
    #new-task-dialog {
        width: 70;
        height: auto;
        max-height: 80%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #new-task-dialog Label {
        margin: 1 0 0 0;
    }
    #new-task-dialog Input {
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
    #nt-status {
        height: auto;
        color: $error;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="new-task-dialog"):
            yield Static("New Task", classes="panel-title")
            yield Label("Title")
            yield Input(placeholder="Task title...", id="nt-title")
            yield Label("Description (optional)")
            yield Input(placeholder="Task description...", id="nt-description")
            yield Label("Workspace Path (optional)")
            yield Input(placeholder="/path/to/workspace...", id="nt-workspace")
            yield Static("", id="nt-status")
            with Horizontal(classes="btn-row"):
                yield Button("Create Task", variant="primary", id="nt-submit")
                yield Button("Cancel", variant="default", id="nt-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#nt-title", Input).focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "nt-cancel":
            self.dismiss(False)
            return

        if event.button.id == "nt-submit":
            await self._submit()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Allow Enter key to submit from any input field."""
        await self._submit()

    async def _submit(self) -> None:
        status = self.query_one("#nt-status", Static)
        title = self.query_one("#nt-title", Input).value.strip()
        description = self.query_one("#nt-description", Input).value.strip()
        workspace = self.query_one("#nt-workspace", Input).value.strip()

        if not title:
            status.update("Title is required.")
            return

        # Validate workspace path
        if workspace:
            workspace_path = Path(workspace).expanduser().resolve()
            if not workspace_path.exists():
                # Check if parent directory exists
                if not workspace_path.parent.exists():
                    status.update(f"Parent directory does not exist: {workspace_path.parent}")
                    return
                # Try to create the directory
                try:
                    workspace_path.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    status.update(f"Cannot create workspace directory: {e}")
                    return
            elif not workspace_path.is_dir():
                status.update(f"Workspace path is not a directory: {workspace}")
                return
            # Update workspace with resolved path
            workspace = str(workspace_path)

        if not hasattr(self.app, "ctx") or self.app.ctx is None:
            status.update("Application context not available.")
            return

        status.update("Creating task...")
        try:
            task = await self.app.ctx.task_service.create_task(
                title=title,
                description=description,
                workspace_path=workspace,
            )
            self.app.notify(f"Task created: {task.slug}")
            self.dismiss(True)
        except ValueError as e:
            status.update(f"Error: {e}")
        except Exception as e:
            status.update(f"Error: {e}")

    def action_cancel(self) -> None:
        self.dismiss(False)
