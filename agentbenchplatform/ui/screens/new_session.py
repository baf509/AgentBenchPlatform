"""New session screen: pick a task, agent, and prompt to start a coding session."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, Select, Static


class NewSessionScreen(ModalScreen[bool]):
    """Modal screen to start a new coding agent session."""

    CSS = """
    NewSessionScreen {
        align: center middle;
    }
    #new-session-dialog {
        width: 70;
        height: auto;
        max-height: 80%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #new-session-dialog Label {
        margin: 1 0 0 0;
    }
    #new-session-dialog Input {
        margin: 0 0 1 0;
    }
    #new-session-dialog Select {
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
    #ns-status {
        height: auto;
        color: $error;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "submit", "Submit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._tasks: list[tuple[str, str]] = []  # (slug, title)

    def compose(self) -> ComposeResult:
        with Vertical(id="new-session-dialog"):
            yield Static("New Coding Session", classes="panel-title")
            yield Label("Task")
            yield Select([], id="ns-task-select", prompt="Select a task...")
            yield Label("Agent Backend")
            yield Select(
                [
                    ("Claude Code", "claude_code"),
                    ("OpenCode", "opencode"),
                    ("OpenCode Local (llama.cpp)", "opencode_local"),
                ],
                id="ns-agent-select",
                value="claude_code",
            )
            yield Label("Prompt (optional)")
            yield Input(placeholder="Initial prompt for the agent...", id="ns-prompt")
            yield Static("", id="ns-status")
            with Horizontal(classes="btn-row"):
                yield Button("Start Session", variant="primary", id="ns-submit")
                yield Button("Cancel", variant="default", id="ns-cancel")
        yield Footer()

    async def on_mount(self) -> None:
        """Load tasks into the select widget."""
        if not hasattr(self.app, "ctx") or self.app.ctx is None:
            return

        tasks = await self.app.ctx.task_service.list_tasks()
        options = [(f"{t.slug} - {t.title}", t.slug) for t in tasks]
        self._tasks = [(t.slug, t.title) for t in tasks]

        select = self.query_one("#ns-task-select", Select)
        select.set_options(options)

        if not options:
            self.query_one("#ns-status", Static).update(
                "No tasks found. Create a task first (t)."
            )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ns-cancel":
            self.dismiss(False)
            return

        if event.button.id == "ns-submit":
            await self._submit()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Allow Enter key in the prompt field to submit the form."""
        await self._submit()

    def action_submit(self) -> None:
        """Ctrl+S submits from anywhere in the dialog."""
        self.run_worker(self._submit())

    async def _submit(self) -> None:
        status = self.query_one("#ns-status", Static)
        task_select = self.query_one("#ns-task-select", Select)
        agent_select = self.query_one("#ns-agent-select", Select)
        prompt_input = self.query_one("#ns-prompt", Input)

        task_slug = task_select.value
        if task_slug is Select.BLANK:
            status.update("Please select a task.")
            return

        agent_type = agent_select.value
        prompt = prompt_input.value.strip()

        if not hasattr(self.app, "ctx") or self.app.ctx is None:
            status.update("Application context not available.")
            return

        ctx = self.app.ctx

        # Resolve task
        task = await ctx.task_service.get_task(str(task_slug))
        if not task:
            status.update(f"Task not found: {task_slug}")
            return

        status.update("Starting session...")
        try:
            session = await ctx.session_service.start_coding_session(
                task_id=task.id,
                agent_type=str(agent_type),
                prompt=prompt,
                workspace_path=task.workspace_path,
            )
            self.app.notify(
                f"Session started: {session.display_name} [{session.lifecycle.value}]"
            )
            self.dismiss(True)
        except Exception as e:
            status.update(f"Error: {e}")

    def action_cancel(self) -> None:
        self.dismiss(False)
