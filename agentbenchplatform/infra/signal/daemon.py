"""signal-cli daemon lifecycle management."""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)


class SignalDaemon:
    """Manages the signal-cli daemon process.

    Spawns signal-cli in daemon mode with HTTP API enabled,
    monitors health, and handles shutdown.
    """

    def __init__(
        self,
        account: str,
        http_url: str = "http://127.0.0.1:8080",
    ) -> None:
        self._account = account
        self._http_url = http_url
        self._process: asyncio.subprocess.Process | None = None
        self._http_client = httpx.AsyncClient(base_url=http_url, timeout=10.0)

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self) -> None:
        """Start the signal-cli daemon."""
        if self.is_running:
            logger.info("signal-cli daemon already running")
            return

        # Parse host:port from URL
        from urllib.parse import urlparse

        parsed = urlparse(self._http_url)
        host = parsed.hostname or "127.0.0.1"
        port = str(parsed.port or 8080)

        cmd = [
            "signal-cli",
            "--account", self._account,
            "-o", "json",
            "daemon",
            "--http", f"{host}:{port}",
        ]

        logger.info("Starting signal-cli daemon: %s", " ".join(cmd))
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Wait for daemon to become healthy with exponential backoff
        await self._wait_for_health()

    async def _wait_for_health(self, max_retries: int = 10) -> None:
        """Wait for the daemon HTTP API to become available."""
        delay = 1.0
        for i in range(max_retries):
            if not self.is_running:
                stderr_output = ""
                if self._process and self._process.stderr:
                    stderr_bytes = await self._process.stderr.read()
                    stderr_output = stderr_bytes.decode(errors="replace").strip()
                msg = "signal-cli daemon exited unexpectedly"
                if stderr_output:
                    msg += f":\n{stderr_output}"
                raise RuntimeError(msg)

            try:
                # signal-cli 0.13+ uses JSON-RPC; health check via listAccounts
                payload = {
                    "jsonrpc": "2.0",
                    "method": "listAccounts",
                    "id": 0,
                }
                response = await self._http_client.post("/api/v1/rpc", json=payload)
                if response.status_code == 200:
                    logger.info("signal-cli daemon is healthy")
                    return
            except (httpx.ConnectError, httpx.ReadError):
                pass

            logger.debug("Waiting for signal-cli daemon (attempt %d/%d)...", i + 1, max_retries)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)

        raise RuntimeError("signal-cli daemon did not become healthy in time")

    async def stop(self) -> None:
        """Stop the signal-cli daemon gracefully."""
        if not self.is_running or self._process is None:
            return

        logger.info("Stopping signal-cli daemon...")
        self._process.terminate()

        try:
            await asyncio.wait_for(self._process.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("signal-cli daemon did not stop gracefully, killing...")
            self._process.kill()
            await self._process.wait()

        self._process = None
        logger.info("signal-cli daemon stopped")

    async def read_stdout_lines(self):
        """Async generator yielding lines from the daemon's stdout."""
        if not self._process or not self._process.stdout:
            return
        while True:
            line = await self._process.stdout.readline()
            if not line:
                break
            yield line.decode(errors="replace").strip()

    async def health_check(self) -> bool:
        """Check if the daemon is healthy."""
        if not self.is_running:
            return False
        try:
            payload = {
                "jsonrpc": "2.0",
                "method": "listAccounts",
                "id": 0,
            }
            response = await self._http_client.post("/api/v1/rpc", json=payload)
            return response.status_code == 200
        except (httpx.ConnectError, httpx.ReadError):
            return False
