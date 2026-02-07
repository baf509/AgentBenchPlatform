"""Tests for agent backends."""

import pytest

from agentbenchplatform.infra.agents.claude_code import ClaudeCodeBackend
from agentbenchplatform.infra.agents.opencode import OpenCodeBackend
from agentbenchplatform.infra.agents.registry import get_backend
from agentbenchplatform.models.agent import AgentBackendType, StartParams


class TestClaudeCodeBackend:
    def test_start_command_basic(self):
        backend = ClaudeCodeBackend()
        cmd = backend.start_command(StartParams(prompt="fix the bug"))
        assert cmd.program == "claude"
        assert "fix the bug" in cmd.args

    def test_start_command_with_session(self):
        backend = ClaudeCodeBackend()
        cmd = backend.start_command(StartParams(session_id="abc123"))
        assert "--session-id" in cmd.args
        assert "abc123" in cmd.args

    def test_start_command_with_model(self):
        backend = ClaudeCodeBackend()
        cmd = backend.start_command(StartParams(model="opus"))
        assert "--model" in cmd.args
        assert "opus" in cmd.args

    def test_resume_command(self):
        backend = ClaudeCodeBackend()
        cmd = backend.resume_command("sess123", StartParams())
        assert cmd.program == "claude"
        assert "--resume" in cmd.args
        assert "sess123" in cmd.args

    def test_matches_process(self):
        backend = ClaudeCodeBackend()
        assert backend.matches_process("claude --session-id abc")
        assert not backend.matches_process("python main.py")

    def test_start_with_workspace(self):
        backend = ClaudeCodeBackend()
        cmd = backend.start_command(StartParams(workspace_path="/tmp/work"))
        assert cmd.cwd == "/tmp/work"


class TestOpenCodeBackend:
    def test_start_command(self):
        backend = OpenCodeBackend()
        cmd = backend.start_command(StartParams(prompt="do stuff"))
        assert cmd.program == "opencode"
        assert "--prompt" in cmd.args

    def test_resume_command(self):
        backend = OpenCodeBackend()
        cmd = backend.resume_command("sess456", StartParams())
        assert "--session" in cmd.args
        assert "sess456" in cmd.args

    def test_matches_process(self):
        backend = OpenCodeBackend()
        assert backend.matches_process("opencode --session abc")
        assert not backend.matches_process("claude --session abc")


class TestRegistry:
    def test_get_claude_code(self):
        backend = get_backend(AgentBackendType.CLAUDE_CODE)
        assert isinstance(backend, ClaudeCodeBackend)

    def test_get_opencode(self):
        backend = get_backend(AgentBackendType.OPENCODE)
        assert isinstance(backend, OpenCodeBackend)

    def test_get_by_string(self):
        backend = get_backend("claude_code")
        assert isinstance(backend, ClaudeCodeBackend)

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            get_backend("nonexistent")
