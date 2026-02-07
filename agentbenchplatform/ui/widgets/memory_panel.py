"""Memory panel widget."""

from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.widgets import RichLog, Static

from agentbenchplatform.models.memory import MemoryEntry

logger = logging.getLogger(__name__)


class MemoryPanel(Static):
    """Panel showing shared memories for the selected task."""

    def __init__(self) -> None:
        super().__init__()
        self._entries: list[MemoryEntry] = []

    def compose(self) -> ComposeResult:
        yield Static("Shared Memory", classes="panel-title")
        yield RichLog(id="memory-list", wrap=True, markup=False)

    def update_memories(self, entries: list[MemoryEntry]) -> None:
        self._entries = entries
        try:
            log = self.query_one("#memory-list", RichLog)
            log.clear()
            if not entries:
                log.write("[No memories]")
                return
            for entry in entries:
                emb_icon = "+" if entry.embedding else "-"
                log.write(f"[{entry.key}] [{emb_icon}] {entry.content[:120]}")
        except Exception:
            logger.debug("Could not update memory panel", exc_info=True)
