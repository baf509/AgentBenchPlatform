"""Watchdog behavior tests for CoordinatorService."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agentbenchplatform.config import AppConfig, ProviderConfig
from agentbenchplatform.models.agent_event import AgentEventType
from agentbenchplatform.models.session import Session, SessionKind, SessionLifecycle
from agentbenchplatform.services import coordinator_service as coordinator_service_module
from agentbenchplatform.services.coordinator_service import CoordinatorService


@pytest.fixture
def config() -> AppConfig:
    cfg = AppConfig(
        providers={"anthropic": ProviderConfig(api_key_env="ANTHROPIC_API_KEY")},
    )
    cfg.coordinator.auto_respond_prompts = False
    return cfg


@pytest.fixture
def service(config, monkeypatch) -> CoordinatorService:
    monkeypatch.setattr(
        coordinator_service_module,
        "get_provider_with_fallback",
        lambda config, primary: object(),
    )
    return CoordinatorService(
        dashboard_service=AsyncMock(),
        session_service=AsyncMock(),
        memory_service=AsyncMock(),
        task_service=AsyncMock(),
        config=config,
    )


def _running_session(session_id: str = "sess-1") -> Session:
    return Session(
        id=session_id,
        task_id="task-1",
        kind=SessionKind.CODING_AGENT,
        lifecycle=SessionLifecycle.RUNNING,
    )


def _fake_monotonic(values: list[float]):
    seq = iter(values)
    last = values[-1]

    def _next() -> float:
        nonlocal last
        try:
            last = next(seq)
        except StopIteration:
            pass
        return last

    return _next


class TestCoordinatorWatchdog:
    @pytest.mark.asyncio
    async def test_stalled_notified_once_until_output_changes(self, service, monkeypatch):
        session = _running_session()
        service._session.list_sessions.return_value = [session]
        service._session.check_session_liveness.return_value = True
        service._session.get_session_output.side_effect = [
            "same output",
            "same output",
            "same output",
            "changed output",
            "changed output",
        ]
        emit_event = AsyncMock()
        service._emit_event = emit_event

        monkeypatch.setattr(
            coordinator_service_module.time,
            "monotonic",
            _fake_monotonic([0.0, 11.0, 22.0, 30.0, 41.0]),
        )

        for _ in range(5):
            await service._check_sessions(stall_threshold=10)

        assert emit_event.await_count == 2
        assert emit_event.await_args_list[0].args[2] == AgentEventType.STALLED
        assert emit_event.await_args_list[1].args[2] == AgentEventType.STALLED
        assert emit_event.await_args_list[0].args[3] == "Output unchanged for 11s"
        assert emit_event.await_args_list[1].args[3] == "Output unchanged for 11s"

    @pytest.mark.asyncio
    async def test_waiting_input_notified_once_until_output_changes(self, service, monkeypatch):
        session = _running_session()
        service._session.list_sessions.return_value = [session]
        service._session.check_session_liveness.return_value = True
        service._session.get_session_output.side_effect = [
            "Continue? (y/n)",
            "Continue? (y/n)",
            "Continue? (y/n)",
            "Overwrite file? (y/n)",
            "Overwrite file? (y/n)",
        ]
        emit_event = AsyncMock()
        service._emit_event = emit_event

        monkeypatch.setattr(
            coordinator_service_module.time,
            "monotonic",
            _fake_monotonic([0.0, 11.0, 22.0, 30.0, 41.0]),
        )

        for _ in range(5):
            await service._check_sessions(stall_threshold=60)

        assert emit_event.await_count == 2
        assert emit_event.await_args_list[0].args[2] == AgentEventType.WAITING_INPUT
        assert emit_event.await_args_list[1].args[2] == AgentEventType.WAITING_INPUT
        assert emit_event.await_args_list[0].args[3] == (
            "Waiting for input: yes/no confirmation (unchanged 11s)"
        )
        assert emit_event.await_args_list[1].args[3] == (
            "Waiting for input: yes/no confirmation (unchanged 11s)"
        )
