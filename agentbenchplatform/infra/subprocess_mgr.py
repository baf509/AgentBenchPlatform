"""Subprocess manager: tmux spawning + PID monitoring."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from dataclasses import dataclass

from agentbenchplatform.models.agent import CommandSpec
from agentbenchplatform.models.session import SessionAttachment

logger = logging.getLogger(__name__)


@dataclass
class SpawnResult:
    """Result of spawning a subprocess."""

    attachment: SessionAttachment
    success: bool
    error: str = ""


class SubprocessManager:
    """Manages agent subprocesses via tmux or direct PTY."""

    def __init__(self, tmux_enabled: bool = True, session_prefix: str = "ab") -> None:
        self.tmux_enabled = tmux_enabled
        self.session_prefix = session_prefix

    async def spawn(
        self,
        command: CommandSpec,
        session_name: str,
        window_name: str = "main",
    ) -> SpawnResult:
        """Spawn a subprocess, preferring tmux if enabled."""
        if self.tmux_enabled:
            return await self._spawn_tmux(command, session_name, window_name)
        return await self._spawn_direct(command, session_name)

    async def _spawn_tmux(
        self,
        command: CommandSpec,
        session_name: str,
        window_name: str,
    ) -> SpawnResult:
        """Spawn in a tmux session."""
        full_session = f"{self.session_prefix}-{session_name}"
        cmd_str = command.full_command

        # Check if tmux session exists
        check = await asyncio.create_subprocess_exec(
            "tmux",
            "has-session",
            "-t",
            full_session,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await check.wait()

        if check.returncode != 0:
            # Create new tmux session
            create_args = [
                "tmux",
                "new-session",
                "-d",
                "-s",
                full_session,
                "-n",
                window_name,
            ]
            # Pass environment variables to tmux
            if command.env:
                for key, value in command.env.items():
                    create_args.extend(["-e", f"{key}={value}"])
            if command.cwd:
                create_args.extend(["-c", command.cwd])
            create_args.append(cmd_str)

            proc = await asyncio.create_subprocess_exec(
                *create_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                return SpawnResult(
                    attachment=SessionAttachment(),
                    success=False,
                    error=f"tmux new-session failed: {stderr.decode()}",
                )
        else:
            # Create new window in existing session
            create_args = [
                "tmux",
                "new-window",
                "-t",
                full_session,
                "-n",
                window_name,
            ]
            # Pass environment variables to tmux
            if command.env:
                for key, value in command.env.items():
                    create_args.extend(["-e", f"{key}={value}"])
            if command.cwd:
                create_args.extend(["-c", command.cwd])
            create_args.append(cmd_str)

            proc = await asyncio.create_subprocess_exec(
                *create_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                return SpawnResult(
                    attachment=SessionAttachment(),
                    success=False,
                    error=f"tmux new-window failed: {stderr.decode()}",
                )

        # Keep the pane alive after the process exits so users can
        # reattach to see final output
        await asyncio.create_subprocess_exec(
            "tmux", "set-option", "-t", f"{full_session}:{window_name}",
            "remain-on-exit", "on",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        # Use Ctrl-] as prefix so TUI apps (opencode, etc.) that
        # capture Ctrl-b don't block tmux detach
        await asyncio.create_subprocess_exec(
            "tmux", "set-option", "-t", full_session,
            "prefix", "C-]",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        # Get pane ID and PID
        pane_id = await self._get_pane_id(full_session, window_name)
        pid = await self._get_pane_pid(full_session, window_name)

        return SpawnResult(
            attachment=SessionAttachment(
                pid=pid,
                tmux_session=full_session,
                tmux_window=window_name,
                tmux_pane_id=pane_id,
            ),
            success=True,
        )

    async def _spawn_direct(self, command: CommandSpec, session_name: str) -> SpawnResult:
        """Spawn as a direct subprocess with PTY."""
        try:
            env = os.environ.copy()
            if command.env:
                env.update(command.env)

            proc = await asyncio.create_subprocess_exec(
                command.program,
                *command.args,
                cwd=command.cwd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            return SpawnResult(
                attachment=SessionAttachment(pid=proc.pid),
                success=True,
            )
        except Exception as e:
            return SpawnResult(
                attachment=SessionAttachment(),
                success=False,
                error=str(e),
            )

    async def _get_pane_id(self, session: str, window: str) -> str:
        """Get the tmux pane ID."""
        proc = await asyncio.create_subprocess_exec(
            "tmux",
            "list-panes",
            "-t",
            f"{session}:{window}",
            "-F",
            "#{pane_id}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        panes = stdout.decode().strip().splitlines()
        return panes[0] if panes else ""

    async def _get_pane_pid(self, session: str, window: str) -> int | None:
        """Get the PID of the process running in the tmux pane."""
        proc = await asyncio.create_subprocess_exec(
            "tmux",
            "list-panes",
            "-t",
            f"{session}:{window}",
            "-F",
            "#{pane_pid}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().strip().splitlines()
        if lines and lines[0].isdigit():
            return int(lines[0])
        return None

    async def capture_output(self, tmux_session: str, tmux_window: str, lines: int = 100) -> str:
        """Capture recent output from a tmux pane."""
        proc = await asyncio.create_subprocess_exec(
            "tmux",
            "capture-pane",
            "-t",
            f"{tmux_session}:{tmux_window}",
            "-p",
            "-S",
            f"-{lines}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode()

    async def send_keys(self, tmux_session: str, tmux_window: str, text: str) -> bool:
        """Send text to a tmux pane."""
        proc = await asyncio.create_subprocess_exec(
            "tmux",
            "send-keys",
            "-t",
            f"{tmux_session}:{tmux_window}",
            text,
            "Enter",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0

    @staticmethod
    def is_pid_alive(pid: int) -> bool:
        """Check if a process is alive."""
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    @staticmethod
    async def send_signal(pid: int, sig: signal.Signals) -> bool:
        """Send a signal to a process."""
        try:
            os.kill(pid, sig)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    async def stop(self, attachment: SessionAttachment) -> bool:
        """Stop a session's subprocess."""
        if attachment.pid and self.is_pid_alive(attachment.pid):
            await self.send_signal(attachment.pid, signal.SIGTERM)

        if attachment.tmux_session and attachment.tmux_window:
            proc = await asyncio.create_subprocess_exec(
                "tmux",
                "kill-window",
                "-t",
                f"{attachment.tmux_session}:{attachment.tmux_window}",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()

        return True

    async def pause(self, attachment: SessionAttachment) -> bool:
        """Pause (SIGSTOP) a session's subprocess."""
        if attachment.pid and self.is_pid_alive(attachment.pid):
            return await self.send_signal(attachment.pid, signal.SIGSTOP)
        return False

    async def resume(self, attachment: SessionAttachment) -> bool:
        """Resume (SIGCONT) a paused subprocess."""
        if attachment.pid and self.is_pid_alive(attachment.pid):
            return await self.send_signal(attachment.pid, signal.SIGCONT)
        return False
