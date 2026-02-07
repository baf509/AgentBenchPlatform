"""Coordinator chat screen."""

from __future__ import annotations

import random

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Footer, Input, RichLog, Static
from textual.worker import Worker, WorkerState

from agentbenchplatform.ui.screens.base import BaseScreen

_THINKING_QUIPS = [
    "Checking with the devs...",
    "I'm going to need you to come in on Saturday...",
    "Syncing up with the team...",
    "Per my last email...",
    "Let me loop in the stakeholders...",
    "Circling back on this...",
    "Moving this to the top of the backlog...",
    "Putting out fires...",
    "Reading the sprint retro notes...",
    "Running it up the flagpole...",
    "Aligning on deliverables...",
    "Triaging the situation...",
    "Consulting the burndown chart...",
    "Did you file a ticket for that?",
    "That's a great question for standup...",
]


class CoordinatorChatScreen(BaseScreen):
    """Interactive chat with the coordinator agent."""

    CSS = """
    #chat-title {
        dock: top;
        height: 1;
        text-style: bold;
        background: $accent;
        padding: 0 1;
    }
    #coordinator-log {
        height: 1fr;
    }
    #coordinator-input {
        dock: bottom;
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        ("escape", "pop_screen", "Back"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._thinking = False
        self._quip_timer = None

    def compose(self) -> ComposeResult:
        yield Static("Coordinator Chat", id="chat-title")
        yield RichLog(id="coordinator-log", wrap=True, markup=True)
        yield Input(placeholder="Ask the coordinator...", id="coordinator-input")
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one("#coordinator-log", RichLog)
        log.write("Coordinator ready. Ask me anything about the system.")
        log.write("I can check task status, manage sessions, search memories, and more.")
        log.write("")
        self.query_one("#coordinator-input", Input).focus()
        if self.has_context():
            self.run_worker(self._load_history(), name="load_history", exclusive=False)

    async def _load_history(self) -> list[dict]:
        """Load conversation history from MongoDB."""
        repo = self.ctx.coordinator_history_repo
        messages = await repo.load_conversation("tui", "")
        return [m.to_dict() for m in messages]

    def _on_history_loaded(self, event: Worker.StateChanged) -> None:
        """Render loaded history into the chat log."""
        if event.worker.name != "load_history":
            return
        if event.state != WorkerState.SUCCESS:
            return
        messages = event.worker.result
        if not messages:
            return
        log = self.query_one("#coordinator-log", RichLog)
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if not content:
                continue
            if role == "user":
                log.write(f"You: {content}")
            elif role == "assistant":
                log.write(f"Coordinator: {content}")
            # Skip tool messages in the replay
        log.write("")

    def _start_thinking(self) -> None:
        self._thinking = True
        self._write_quip()
        self._quip_timer = self.set_interval(3.0, self._cycle_quip)

    def _stop_thinking(self) -> None:
        self._thinking = False
        if self._quip_timer:
            self._quip_timer.stop()
            self._quip_timer = None
        # Remove the current quip line from the log
        self._pop_last_line()

    def _write_quip(self) -> None:
        quip = random.choice(_THINKING_QUIPS)
        log = self.query_one("#coordinator-log", RichLog)
        log.write(Text(f"  {quip}", style="dim italic"))

    def _cycle_quip(self) -> None:
        if not self._thinking:
            return
        self._pop_last_line()
        self._write_quip()

    def _pop_last_line(self) -> None:
        """Remove the last line from the RichLog."""
        log = self.query_one("#coordinator-log", RichLog)
        if log.lines:
            log.lines.pop()
            log.refresh()

    def _on_progress(self, text: str) -> None:
        """Handle progress updates from the coordinator during tool-call rounds."""
        if not self._thinking:
            return
        log = self.query_one("#coordinator-log", RichLog)
        # Remove the current quip line before writing progress
        self._pop_last_line()
        if text.startswith("[tool]"):
            tool_name = text[len("[tool] "):]
            log.write(Text(f"  >> {tool_name}", style="dim cyan"))
        else:
            log.write(Text(f"  {text}", style="dim"))
        # Put a new quip back at the bottom
        self._write_quip()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        message = event.value.strip()
        if not message:
            return

        if self._thinking:
            return

        input_widget = self.query_one("#coordinator-input", Input)
        input_widget.value = ""

        log = self.query_one("#coordinator-log", RichLog)
        log.write(f"You: {message}")

        if not self.has_context():
            log.write("Error: Application context not available")
            return

        self._start_thinking()
        input_widget.disabled = True

        self.run_worker(
            self._send_message(message),
            name="coordinator_msg",
            exclusive=True,
        )

    async def _send_message(self, message: str) -> str:
        """Call coordinator service (runs in a worker)."""
        return await self.ctx.coordinator_service.handle_message(
            user_message=message,
            channel="tui",
            on_progress=self._on_progress,
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.name == "load_history":
            self._on_history_loaded(event)
            return
        if event.worker.name != "coordinator_msg":
            return

        log = self.query_one("#coordinator-log", RichLog)
        input_widget = self.query_one("#coordinator-input", Input)

        if event.state == WorkerState.SUCCESS:
            self._stop_thinking()
            log.write(f"Coordinator: {event.worker.result}")
            log.write("")
            input_widget.disabled = False
            input_widget.focus()

        elif event.state == WorkerState.ERROR:
            self._stop_thinking()
            log.write(f"Error: {event.worker.error}")
            log.write("")
            input_widget.disabled = False
            input_widget.focus()

    def action_pop_screen(self) -> None:
        self._stop_thinking()
        self.app.pop_screen()
