"""CLI handler for launching the TUI dashboard."""

from __future__ import annotations

import click


@click.command("dashboard")
def dashboard_command():
    """Launch the TUI dashboard."""
    from agentbenchplatform.ui.app import AgentBenchApp

    app = AgentBenchApp()
    app.run()
