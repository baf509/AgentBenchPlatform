"""Inbound message routing to coordinator."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from agentbenchplatform.infra.signal.client import SignalMessage

if TYPE_CHECKING:
    from agentbenchplatform.infra.whisper_client import WhisperClient
    from agentbenchplatform.services.coordinator_service import CoordinatorService

logger = logging.getLogger(__name__)

# signal-cli stores received attachments here by default
SIGNAL_ATTACHMENTS_DIR = Path.home() / ".local" / "share" / "signal-cli" / "attachments"


class SignalMessageHandler:
    """Routes inbound Signal messages to the coordinator.

    Validates senders against allowlist before processing.
    """

    def __init__(
        self,
        coordinator: CoordinatorService,
        allowed_senders: list[str] | None = None,
        dm_policy: str = "allowlist",
        whisper_client: WhisperClient | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._allowed_senders = set(allowed_senders or [])
        self._dm_policy = dm_policy
        self._whisper = whisper_client

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

    async def _transcribe_attachments(self, message: SignalMessage) -> str | None:
        """Transcribe audio attachments from a Signal message.

        Returns transcribed text or None if no audio attachments found.
        """
        if not self._whisper or not message.attachments:
            return None

        transcriptions = []
        for attachment in message.attachments:
            content_type = attachment.get("contentType", "")
            if not content_type.startswith("audio/"):
                continue

            attachment_id = attachment.get("id")
            if not attachment_id:
                logger.warning("Audio attachment has no id, skipping")
                continue

            attachment_path = SIGNAL_ATTACHMENTS_DIR / attachment_id
            if not attachment_path.exists():
                logger.warning("Attachment file not found: %s", attachment_path)
                continue

            try:
                text = await self._whisper.transcribe(attachment_path)
                if text:
                    transcriptions.append(text)
                    logger.info("Transcribed voice note (%s): %s", attachment_id, text[:100])
            except Exception:
                logger.exception("Failed to transcribe attachment %s", attachment_id)

        return " ".join(transcriptions) if transcriptions else None

    async def handle_message(self, message: SignalMessage) -> str | None:
        """Process an inbound message.

        Returns the coordinator's response text, or None if sender not allowed.
        """
        if not self.is_allowed_sender(message.sender):
            logger.warning("Rejected message from unauthorized sender: %s", message.sender)
            return None

        # Transcribe any audio attachments (voice notes)
        transcription = await self._transcribe_attachments(message)
        text = message.text
        if transcription:
            prefix = "[Voice note] " + transcription
            text = prefix if not text else prefix + "\n" + text

        if not text:
            logger.debug("Skipping message with no text and no transcribable attachments")
            return None

        logger.info("Processing Signal message from %s: %s", message.sender, text[:100])

        try:
            response = await self._coordinator.handle_message(
                user_message=text,
                channel="signal",
                sender_id=message.sender,
            )
            return response
        except Exception:
            logger.exception("Error handling Signal message")
            return "Sorry, an error occurred while processing your message."
