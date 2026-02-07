"""Memory browser screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Footer, Input, RichLog, Static

from agentbenchplatform.models.memory import MemoryQuery
from agentbenchplatform.ui.screens.base import BaseScreen


class MemoryBrowserScreen(BaseScreen):
    """Browse and search shared memories."""

    BINDINGS = [
        ("escape", "pop_screen", "Back"),
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("Memory Browser", id="memory-title")
        yield Input(placeholder="Search memories...", id="memory-search")
        yield RichLog(id="memory-results", wrap=True, markup=False)
        yield Footer()

    async def on_mount(self) -> None:
        await self._load_all()
        self.query_one("#memory-search", Input).focus()

    async def _load_all(self) -> None:
        if not self.has_context():
            return
        try:
            memories = await self.ctx.memory_service.list_memories()
            log = self.query_one("#memory-results", RichLog)
            log.clear()
            if not memories:
                log.write("[No memories stored]")
                return
            for m in memories:
                emb = "+" if m.embedding else "-"
                log.write(f"[{m.key}] ({m.scope.value}) [{emb}emb] {m.content[:150]}")
        except Exception:
            pass

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if not self.has_context():
            return
        query_text = event.value.strip()
        if not query_text:
            await self._load_all()
            return

        try:
            query = MemoryQuery(query_text=query_text, limit=20)
            results = await self.ctx.memory_service.search(query)
            log = self.query_one("#memory-results", RichLog)
            log.clear()
            if not results:
                log.write("[No results]")
                return
            log.write(f"Search results for: {query_text}")
            log.write("")
            for m in results:
                log.write(f"[{m.key}] ({m.scope.value}) {m.content[:150]}")
        except Exception:
            pass

    def action_pop_screen(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()
