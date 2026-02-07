"""Asyncio Unix socket JSON-RPC client."""

from __future__ import annotations

import asyncio
import itertools
import logging
from typing import Any

from agentbenchplatform.infra.rpc.protocol import (
    JsonRpcRequest,
    JsonRpcResponse,
    decode,
    encode,
)

logger = logging.getLogger(__name__)


class RpcClient:
    """Asyncio Unix domain socket JSON-RPC 2.0 client."""

    def __init__(self, socket_path: str) -> None:
        self._socket_path = socket_path
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._id_counter = itertools.count(1)
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        """Connect to the server's Unix socket."""
        self._reader, self._writer = await asyncio.open_unix_connection(
            self._socket_path
        )
        logger.debug("Connected to RPC server at %s", self._socket_path)

    async def close(self) -> None:
        """Close the connection."""
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None
        logger.debug("RPC client disconnected")

    async def _ensure_connected(self) -> None:
        """Reconnect if not connected."""
        if not self.connected:
            await self.connect()

    async def call(self, method: str, **params: Any) -> Any:
        """Send a JSON-RPC request and return the result.

        Raises RuntimeError on RPC errors. Auto-reconnects once on connection failure.
        """
        async with self._lock:
            try:
                return await self._call_inner(method, params)
            except (ConnectionError, OSError, BrokenPipeError):
                # Retry once with reconnect
                logger.debug("Connection lost, reconnecting...")
                await self.close()
                await self.connect()
                return await self._call_inner(method, params)

    async def _call_inner(self, method: str, params: dict) -> Any:
        """Send request and read response."""
        await self._ensure_connected()
        assert self._reader is not None
        assert self._writer is not None

        req_id = next(self._id_counter)
        request = JsonRpcRequest(method=method, params=params, id=req_id)

        self._writer.write(encode(request))
        await self._writer.drain()

        line = await self._reader.readline()
        if not line:
            raise ConnectionError("Server closed connection")

        msg = decode(line)
        if not isinstance(msg, JsonRpcResponse):
            raise RuntimeError(f"Expected response, got {type(msg).__name__}")

        if msg.is_error:
            error = msg.error or {}
            raise RuntimeError(
                f"RPC error {error.get('code', '?')}: {error.get('message', 'Unknown error')}"
            )

        return msg.result

    async def call_streaming(
        self,
        method: str,
        on_notification: Any = None,
        **params: Any,
    ) -> Any:
        """Send a request that may produce notifications before the final response.

        For coordinator.message, the server returns progress items in the result
        rather than streaming separate notifications, so this is sugar that
        calls the method and then invokes on_notification for each progress item.
        """
        result = await self.call(method, **params)

        # If the result has progress items, invoke callback for each
        if isinstance(result, dict) and "progress" in result and on_notification:
            for item in result["progress"]:
                on_notification(item)

        return result
