"""Tests for agent backends."""

import pytest

from agentbenchplatform.infra.agents.claude_code import ClaudeCodeBackend
from agentbenchplatform.infra.agents.opencode import OpenCodeBackend
from agentbenchplatform.infra.agents.opencode_local import OpenCodeLocalBackend
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


class TestOpenCodeLocalBackend:
    def test_start_command_default_model(self):
        backend = OpenCodeLocalBackend()
        cmd = backend.start_command(StartParams(prompt="fix typo"))
        assert cmd.program == "opencode"
        assert "--model" in cmd.args
        assert "llama.cpp/step3p5-flash" in cmd.args
        assert "--prompt" in cmd.args

    def test_start_command_custom_model(self):
        backend = OpenCodeLocalBackend(model="llama.cpp/qwen3-8b")
        cmd = backend.start_command(StartParams())
        assert "llama.cpp/qwen3-8b" in cmd.args

    def test_start_command_params_model_overrides(self):
        backend = OpenCodeLocalBackend(model="llama.cpp/default")
        cmd = backend.start_command(StartParams(model="llama.cpp/override"))
        assert "llama.cpp/override" in cmd.args
        assert "llama.cpp/default" not in cmd.args

    def test_resume_command(self):
        backend = OpenCodeLocalBackend()
        cmd = backend.resume_command("sess789", StartParams())
        assert "--session" in cmd.args
        assert "sess789" in cmd.args
        assert "--model" in cmd.args

    def test_matches_process(self):
        backend = OpenCodeLocalBackend()
        assert backend.matches_process("opencode --model llama.cpp/step3p5-flash --session abc")
        assert not backend.matches_process("opencode --model anthropic/claude --session abc")
        assert not backend.matches_process("claude --session abc")

    def test_start_with_workspace(self):
        backend = OpenCodeLocalBackend()
        cmd = backend.start_command(StartParams(workspace_path="/tmp/work"))
        assert cmd.cwd == "/tmp/work"


class TestRegistry:
    def test_get_claude_code(self):
        backend = get_backend(AgentBackendType.CLAUDE_CODE)
        assert isinstance(backend, ClaudeCodeBackend)

    def test_get_opencode(self):
        backend = get_backend(AgentBackendType.OPENCODE)
        assert isinstance(backend, OpenCodeBackend)

    def test_get_opencode_local(self):
        backend = get_backend(AgentBackendType.OPENCODE_LOCAL)
        assert isinstance(backend, OpenCodeLocalBackend)

    def test_get_opencode_local_with_model(self):
        backend = get_backend(AgentBackendType.OPENCODE_LOCAL, model="llama.cpp/custom")
        assert isinstance(backend, OpenCodeLocalBackend)
        cmd = backend.start_command(StartParams())
        assert "llama.cpp/custom" in cmd.args

    def test_get_by_string(self):
        backend = get_backend("claude_code")
        assert isinstance(backend, ClaudeCodeBackend)

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            get_backend("nonexistent")
