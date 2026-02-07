"""Base screen with common utilities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.screen import Screen

if TYPE_CHECKING:
    from agentbenchplatform.context import AppContext
    from agentbenchplatform.ui.app import AgentBenchApp


class BaseScreen(Screen):
    """Base screen with common utilities for context management."""

    @property
    def ctx(self) -> AppContext | None:
        """Get the application context safely.

        Returns:
            AppContext if available, None otherwise.
        """
        if hasattr(self.app, "ctx"):
            app: AgentBenchApp = self.app  # type: ignore
            return app.ctx
        return None

    def has_context(self) -> bool:
        """Check if application context is available.

        Returns:
            True if context is available, False otherwise.
        """
        return self.ctx is not None
