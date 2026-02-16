"""Tests for Agent models."""

from agentbenchplatform.models.agent import AgentBackendType, CommandSpec, StartParams


class TestCommandSpec:
    def test_full_command(self):
        spec = CommandSpec(program="claude", args=("--model", "sonnet", "do stuff"))
        assert spec.full_command == "claude --model sonnet 'do stuff'"

    def test_full_command_no_args(self):
        spec = CommandSpec(program="claude")
        assert spec.full_command == "claude"


class TestStartParams:
    def test_defaults(self):
        params = StartParams()
        assert params.prompt == ""
        assert params.model == ""
        assert params.workspace_path == ""


class TestAgentBackendType:
    def test_values(self):
        assert AgentBackendType.CLAUDE_CODE.value == "claude_code"
        assert AgentBackendType.OPENCODE.value == "opencode"
        assert AgentBackendType.OPENCODE_LOCAL.value == "opencode_local"
