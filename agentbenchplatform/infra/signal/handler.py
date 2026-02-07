"""Inbound message routing to coordinator."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentbenchplatform.infra.signal.client import SignalMessage

if TYPE_CHECKING:
    from agentbenchplatform.services.coordinator_service import CoordinatorService

logger = logging.getLogger(__name__)


class SignalMessageHandler:
    """Routes inbound Signal messages to the coordinator.

    Validates senders against allowlist before processing.
    """

    def __init__(
        self,
        coordinator: CoordinatorService,
        allowed_senders: list[str] | None = None,
        dm_policy: str = "allowlist",
    ) -> None:
        self._coordinator = coordinator
        self._allowed_senders = set(allowed_senders or [])
        self._dm_policy = dm_policy

    def is_allowed_sender(self, sender: str) -> bool:
        """Check if a sender is allowed to interact."""
        if self._dm_policy == "open":
            return True
        if self._dm_policy == "allowlist":
            return sender in self._allowed_senders
        return False

    def add_allowed_sender(self, sender: str) -> None:
        """Add a sender to the allowlist (pair mode)."""
        self._allowed_senders.add(sender)
        logger.info("Added allowed sender: %s", sender)

    async def handle_message(self, message: SignalMessage) -> str | None:
        """Process an inbound message.

        Returns the coordinator's response text, or None if sender not allowed.
        """
        if not self.is_allowed_sender(message.sender):
            logger.warning("Rejected message from unauthorized sender: %s", message.sender)
            return None

        logger.info("Processing Signal message from %s: %s", message.sender, message.text[:100])

        try:
            response = await self._coordinator.handle_message(
                user_message=message.text,
                channel="signal",
                sender_id=message.sender,
            )
            return response
        except Exception:
            logger.exception("Error handling Signal message")
            return "Sorry, an error occurred while processing your message."
