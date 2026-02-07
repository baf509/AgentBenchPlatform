"""Tests for Provider models."""

from agentbenchplatform.models.provider import LLMConfig, LLMMessage, LLMResponse, ToolCall


class TestLLMMessage:
    def test_to_dict(self):
        msg = LLMMessage(role="user", content="hello")
        d = msg.to_dict()
        assert d == {"role": "user", "content": "hello"}

    def test_to_dict_with_tool_call_id(self):
        msg = LLMMessage(role="tool", content="result", tool_call_id="tc_1")
        d = msg.to_dict()
        assert d["tool_call_id"] == "tc_1"


class TestLLMResponse:
    def test_has_tool_calls(self):
        response = LLMResponse(
            content="",
            tool_calls=[ToolCall(id="1", name="test", arguments={})],
        )
        assert response.has_tool_calls

    def test_no_tool_calls(self):
        response = LLMResponse(content="hello")
        assert not response.has_tool_calls


class TestLLMConfig:
    def test_defaults(self):
        config = LLMConfig()
        assert config.max_tokens == 4096
        assert config.temperature == 0.7
