"""Signal service: bridges Signal messaging to the coordinator agent."""

from __future__ import annotations

import asyncio
import logging

from agentbenchplatform.config import SignalConfig
from agentbenchplatform.infra.signal.client import SignalClient
from agentbenchplatform.infra.signal.daemon import SignalDaemon
from agentbenchplatform.infra.signal.handler import SignalMessageHandler
from agentbenchplatform.infra.whisper_client import WhisperClient
from agentbenchplatform.services.coordinator_service import CoordinatorService

logger = logging.getLogger(__name__)


class SignalService:
    """Bridges Signal messaging to the coordinator agent."""

    def __init__(
        self,
        coordinator: CoordinatorService,
        config: SignalConfig,
    ) -> None:
        self._coordinator = coordinator
        self._config = config
        self._daemon = SignalDaemon(
            account=config.account,
            http_url=config.http_url,
        )
        self._client = SignalClient(
            http_url=config.http_url,
            account=config.account,
            daemon=self._daemon,
        )
        self._whisper = WhisperClient(base_url=config.whisper_url)
        self._handler = SignalMessageHandler(
            coordinator=coordinator,
            allowed_senders=config.allowed_senders,
            dm_policy=config.dm_policy,
            whisper_client=self._whisper,
        )
        self._listen_task: asyncio.Task | None = None

    @property
    def is_running(self) -> bool:
        return self._daemon.is_running

    async def start(self) -> None:
        """Start signal-cli daemon and begin listening for messages."""
        if not self._config.enabled:
            logger.info("Signal integration is disabled")
            return

        await self._daemon.start()
        self._listen_task = asyncio.create_task(self._listen_loop())
        logger.info("Signal service started")

    async def stop(self) -> None:
        """Stop signal-cli daemon and listener."""
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        await self._daemon.stop()
        logger.info("Signal service stopped")

    async def _listen_loop(self) -> None:
        """SSE event loop: receive messages, route to coordinator."""
        while True:
            try:
                async for message in self._client.receive_events():
                    response = await self._handler.handle_message(message)
                    if response:
                        await self._client.send_message_chunked(
                            message.sender, response
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in Signal listen loop, reconnecting in 5s...")
                await asyncio.sleep(5)

    async def send_notification(self, recipient: str, text: str) -> bool:
        """Proactive notification (e.g., agent finished, error occurred)."""
        return await self._client.send_message_chunked(recipient, text)

    async def pair_sender(self, phone: str) -> None:
        """Add a phone number to the allowed senders list."""
        self._handler.add_allowed_sender(phone)
        logger.info("Paired sender: %s", phone)

    async def status(self) -> dict:
        """Get Signal service status."""
        daemon_healthy = await self._daemon.health_check()
        return {
            "enabled": self._config.enabled,
            "daemon_running": self._daemon.is_running,
            "daemon_healthy": daemon_healthy,
            "account": self._config.account,
            "listening": self._listen_task is not None and not self._listen_task.done(),
        }
