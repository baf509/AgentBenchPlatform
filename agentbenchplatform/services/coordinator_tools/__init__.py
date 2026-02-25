"""Coordinator tool handler registry.

Each tool handler is a simple async function with signature:

    async def handle(ctx: ToolContext, arguments: dict) -> Any

The registry maps tool names to handler functions, replacing the
monolithic if/elif chain in CoordinatorService._execute_tool().
"""

from __future__ import annotations

from agentbenchplatform.services.coordinator_tools.registry import get_tool_handlers

__all__ = ["get_tool_handlers"]
