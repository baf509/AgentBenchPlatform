"""Agent status widget showing detail about a selected session."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static

from agentbenchplatform.models.session import Session


class AgentStatus(Static):
    """Shows detailed status for a selected session."""

    def __init__(self) -> None:
        super().__init__("Select a session to view details")
        self._session: Session | None = None

    def update_session(self, session: Session | None) -> None:
        self._session = session
        if not session:
            self.update("Select a session to view details")
            return

        lines = [
            f"Session: {session.display_name}",
            f"  Kind: {session.kind.value}",
            f"  Lifecycle: {session.lifecycle.value}",
            f"  Agent: {session.agent_backend}",
            f"  Thread: {session.agent_thread_id[:12]}..." if session.agent_thread_id else "",
        ]

        att = session.attachment
        if att.pid:
            lines.append(f"  PID: {att.pid}")
        if att.tmux_session:
            lines.append(f"  tmux: {att.tmux_session}:{att.tmux_window}")

        if session.research_progress:
            rp = session.research_progress
            lines.append(
                f"  Research: depth {rp.current_depth}/{rp.max_depth}, "
                f"{rp.queries_completed} queries, {rp.learnings_count} learnings"
            )

        self.update("\n".join(line for line in lines if line))
