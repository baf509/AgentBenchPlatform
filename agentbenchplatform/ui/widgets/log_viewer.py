"""Log viewer widget for tmux pane output."""

from __future__ import annotations

from textual.widgets import RichLog


class LogViewer(RichLog):
    """Shows captured output from a session's tmux pane."""

    def __init__(self) -> None:
        super().__init__(id="log-viewer", wrap=True, highlight=True, markup=False)

    def update_output(self, output: str) -> None:
        """Replace content with new output."""
        self.clear()
        if output:
            for line in output.splitlines():
                self.write(line)
        else:
            self.write("[No output captured]")
