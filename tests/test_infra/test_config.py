"""Tests for config loading."""

from pathlib import Path

from agentbenchplatform.config import AppConfig, load_config, init_config


class TestConfig:
    def test_load_defaults(self):
        """Loading with no file should return defaults."""
        config = load_config(Path("/nonexistent/config.toml"))
        assert config.mongodb.uri == "mongodb://localhost:27017/?directConnection=true&replicaSet=rs0"
        assert config.mongodb.database == "agentbenchplatform"
        assert config.default_agent == "claude_code"
        assert config.tmux.enabled is True

    def test_resolved_workspace_root(self):
        config = AppConfig(workspace_root="~/test-workspaces")
        assert str(config.resolved_workspace_root).startswith("/")
        assert "~" not in str(config.resolved_workspace_root)

    def test_init_config(self, tmp_path):
        path = tmp_path / "config.toml"
        result = init_config(path)
        assert result == path
        assert path.exists()
        # Should be loadable
        config = load_config(path)
        assert config.mongodb.database == "agentbenchplatform"
