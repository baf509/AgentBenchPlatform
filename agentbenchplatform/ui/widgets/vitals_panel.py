"""Vitals panel widget - compact system overview for the dashboard."""

from __future__ import annotations

from datetime import datetime, timezone

from textual.widgets import Static

from agentbenchplatform.models.session import SessionLifecycle
from agentbenchplatform.services.dashboard_service import DashboardSnapshot


class VitalsPanel(Static):
    """Renders a compact system vitals summary. No IO - pure rendering."""

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)

    def update_vitals(
        self,
        snapshot: DashboardSnapshot | None,
        usage_totals: dict | None,
        last_coordinator_dt: datetime | None,
    ) -> None:
        """Re-render vitals text from pre-fetched data."""
        lines: list[str] = []

        # --- Sessions ---
        if snapshot:
            running = snapshot.total_running
            total = snapshot.total_sessions
            paused = sum(
                1
                for ts in snapshot.tasks
                for s in ts.sessions
                if s.lifecycle == SessionLifecycle.PAUSED
            )
            parts = []
            if running:
                parts.append(f"{running} running")
            if paused:
                parts.append(f"{paused} paused")
            parts.append(f"{total} total")
            lines.append(f"Sessions: {'  '.join(parts)}")

        # --- Tokens ---
        if usage_totals:
            lines.append("")
            lines.append("Tokens (6h):")
            for key, vals in sorted(usage_totals.items()):
                source, _, model = key.partition(":")
                inp = f"{vals['input_tokens']:,}"
                out = f"{vals['output_tokens']:,}"
                lines.append(f"  {source:<14}{model:<18}{inp} in  {out} out")
        elif usage_totals is not None:
            # Empty dict means query ran but no data
            lines.append("")
            lines.append("No token usage recorded")

        # --- Research ---
        if snapshot:
            for ts in snapshot.tasks:
                for s in ts.sessions:
                    if s.research_progress:
                        rp = s.research_progress
                        lines.append("")
                        lines.append(
                            f"Research: depth {rp.current_depth}/{rp.max_depth}, "
                            f"{rp.queries_completed} queries, "
                            f"{rp.learnings_count} learnings"
                        )
                        break  # show first active research only
                else:
                    continue
                break

        # --- Last coordinator ---
        if last_coordinator_dt:
            delta = datetime.now(timezone.utc) - last_coordinator_dt
            minutes = int(delta.total_seconds() / 60)
            if minutes < 1:
                ago = "just now"
            elif minutes < 60:
                ago = f"{minutes}m ago"
            else:
                hours = minutes // 60
                ago = f"{hours}h ago"
            lines.append("")
            lines.append(f"Last coordinator: {ago}")

        # --- Footer hints ---
        lines.append("")
        lines.append("[c] coordinator chat  [u] full usage")

        self.update("\n".join(lines))
