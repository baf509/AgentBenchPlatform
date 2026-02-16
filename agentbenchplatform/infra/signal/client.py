"""JSON-RPC + SSE client for signal-cli."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from agentbenchplatform.infra.signal.daemon import SignalDaemon

logger = logging.getLogger(__name__)


@dataclass
class SignalMessage:
    """An inbound Signal message."""

    sender: str
    text: str
    timestamp: int = 0
    group_id: str = ""
    attachments: list[dict] | None = None


class SignalClient:
    """Client for the signal-cli HTTP/JSON-RPC API.

    Receive messages from daemon stdout (JSON lines).
    Send messages via JSON-RPC send method.
    """

    def __init__(
        self,
        http_url: str = "http://127.0.0.1:8080",
        account: str = "",
        daemon: "SignalDaemon | None" = None,
    ) -> None:
        self._http_url = http_url.rstrip("/")
        self._account = account
        self._daemon = daemon
        self._client = httpx.AsyncClient(base_url=self._http_url, timeout=30.0)

    async def receive_events(self):
        """Read messages from the daemon's stdout JSON lines.

        The signal-cli daemon in --http mode auto-receives and prints
        envelope JSON objects to stdout.
        """
        if not self._daemon:
            logger.error("No daemon attached, cannot receive messages")
            return

        async for line in self._daemon.read_stdout_lines():
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("Non-JSON stdout line: %s", line[:200])
                continue

            logger.debug("Daemon stdout: %s", line[:500])

            envelope = data.get("envelope", {})
            data_msg = envelope.get("dataMessage")
            if not data_msg:
                continue

            text = data_msg.get("message", "")
            if not text:
                continue

            sender = envelope.get("sourceNumber") or envelope.get("source", "")
            logger.info("Received message from %s: %s", sender, text[:100])
            yield SignalMessage(
                sender=sender,
                text=text,
                timestamp=data_msg.get("timestamp", 0),
                group_id=data_msg.get("groupInfo", {}).get("groupId", ""),
                attachments=data_msg.get("attachments"),
            )

    async def send_message(self, recipient: str, text: str) -> bool:
        """Send a text message via signal-cli JSON-RPC."""
        payload = {
            "jsonrpc": "2.0",
            "method": "send",
            "id": 1,
            "params": {
                "account": self._account,
                "recipient": [recipient],
                "message": text,
            },
        }

        try:
            response = await self._client.post("/api/v1/rpc", json=payload)
            response.raise_for_status()
            result = response.json()
            if "error" in result:
                logger.error("Signal send failed: %s", result["error"])
                return False
            return True
        except httpx.HTTPError as e:
            logger.error("Signal send HTTP error: %s", e)
            return False

    async def send_message_chunked(
        self, recipient: str, text: str, max_chunk: int = 2000
    ) -> bool:
        """Send a long message in chunks."""
        if len(text) <= max_chunk:
            return await self.send_message(recipient, text)

        chunks = []
        while text:
            if len(text) <= max_chunk:
                chunks.append(text)
                break
            # Find a good break point
            break_at = text.rfind("\n", 0, max_chunk)
            if break_at == -1:
                break_at = max_chunk
            chunks.append(text[:break_at])
            text = text[break_at:].lstrip("\n")

        for i, chunk in enumerate(chunks):
            prefix = f"[{i + 1}/{len(chunks)}] " if len(chunks) > 1 else ""
            success = await self.send_message(recipient, prefix + chunk)
            if not success:
                return False
        return True
