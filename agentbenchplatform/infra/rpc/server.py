"""Asyncio Unix socket JSON-RPC server."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

from agentbenchplatform.infra.rpc.methods import MethodRegistry
from agentbenchplatform.infra.rpc.protocol import (
    INTERNAL_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
    decode,
    encode,
    make_error,
)

if TYPE_CHECKING:
    from agentbenchplatform.context import AppContext

logger = logging.getLogger(__name__)


class RpcServer:
    """Asyncio Unix domain socket JSON-RPC 2.0 server."""

    def __init__(self, ctx: AppContext, socket_path: str) -> None:
        self._ctx = ctx
        self._socket_path = socket_path
        self._registry = MethodRegistry(ctx)
        self._server: asyncio.Server | None = None

    @property
    def socket_path(self) -> str:
        return self._socket_path

    async def start(self) -> None:
        """Start listening on the Unix socket."""
        # Remove stale socket file
        try:
            os.unlink(self._socket_path)
        except FileNotFoundError:
            pass

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=self._socket_path,
        )
        # Make socket accessible to the user only
        os.chmod(self._socket_path, 0o600)
        logger.info("RPC server listening on %s", self._socket_path)

    async def stop(self) -> None:
        """Stop the server and clean up the socket file."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        try:
            os.unlink(self._socket_path)
        except FileNotFoundError:
            pass
        logger.info("RPC server stopped")

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single client connection: read JSON lines, dispatch, write responses."""
        peer = writer.get_extra_info("peername") or "unix"
        logger.debug("Client connected: %s", peer)

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break  # Client disconnected

                try:
                    msg = decode(line)
                except Exception:
                    resp = make_error(0, PARSE_ERROR, "Parse error")
                    writer.write(encode(resp))
                    await writer.drain()
                    continue

                if isinstance(msg, JsonRpcNotification):
                    # Notifications don't get responses
                    continue

                if not isinstance(msg, JsonRpcRequest):
                    resp = make_error(0, INVALID_REQUEST, "Invalid request")
                    writer.write(encode(resp))
                    await writer.drain()
                    continue

                # Dispatch the method
                if not self._registry.has_method(msg.method):
                    resp = make_error(msg.id, METHOD_NOT_FOUND, f"Method not found: {msg.method}")
                    writer.write(encode(resp))
                    await writer.drain()
                    continue

                try:
                    result = await self._registry.dispatch(msg.method, msg.params)
                    resp = JsonRpcResponse(id=msg.id, result=result)
                except Exception as e:
                    logger.exception("Error dispatching %s", msg.method)
                    resp = make_error(msg.id, INTERNAL_ERROR, str(e))

                writer.write(encode(resp))
                await writer.drain()

        except asyncio.CancelledError:
            pass
        except ConnectionResetError:
            logger.debug("Client disconnected: %s", peer)
        except Exception:
            logger.exception("Error handling client %s", peer)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.debug("Client disconnected: %s", peer)
