"""CLI handlers for config commands."""

from __future__ import annotations

import click

from agentbenchplatform.config import DEFAULT_CONFIG_PATH, init_config, load_config


@click.group("config")
def config_group():
    """Manage configuration."""
    pass


@config_group.command("init")
def config_init():
    """Create default configuration file."""
    path = init_config()
    click.echo(f"Configuration created at: {path}")


@config_group.command("show")
def config_show():
    """Show current configuration."""
    config = load_config()
    click.echo(f"Config file: {config.config_path}")
    click.echo(f"  Workspace root: {config.workspace_root}")
    click.echo(f"  Default agent: {config.default_agent}")
    click.echo(f"  MongoDB: {config.mongodb.uri}/{config.mongodb.database}")
    click.echo(f"  Embeddings: {config.embeddings.provider} ({config.embeddings.base_url})")
    click.echo(f"  Coordinator: {config.coordinator.provider}/{config.coordinator.model}")
    click.echo(f"  Research: {config.research.default_provider}, search={config.research.default_search}")
    click.echo(f"  Signal: {'enabled' if config.signal.enabled else 'disabled'}")
    click.echo(f"  tmux: {'enabled' if config.tmux.enabled else 'disabled'} (prefix={config.tmux.session_prefix})")
    click.echo(f"  Server socket: {config.server.resolved_socket_path}")
    click.echo(f"  Server PID file: {config.server.resolved_pid_file}")

    click.echo("\n  Providers:")
    for name, prov in config.providers.items():
        has_key = "configured" if prov.api_key else "not set"
        click.echo(f"    {name}: model={prov.default_model}, key={has_key}")


@config_group.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str):
    """Set a configuration value.

    Modifies the TOML config file. Key uses dot notation, e.g.:
    general.default_agent, mongodb.uri, signal.enabled
    """
    import tomli_w

    path = DEFAULT_CONFIG_PATH
    if not path.exists():
        click.echo("No config file found. Run 'agentbenchplatform config init' first.", err=True)
        return

    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    with open(path, "rb") as f:
        data = tomllib.load(f)

    # Navigate dot-separated key
    parts = key.split(".")
    target = data
    for part in parts[:-1]:
        if part not in target:
            target[part] = {}
        target = target[part]

    # Type coercion
    import json

    final_key = parts[-1]
    if value.lower() in ("true", "false"):
        target[final_key] = value.lower() == "true"
    elif value.isdigit():
        target[final_key] = int(value)
    elif value.startswith("[") or value.startswith("{"):
        try:
            target[final_key] = json.loads(value)
        except json.JSONDecodeError:
            target[final_key] = value
    else:
        target[final_key] = value

    with open(path, "wb") as f:
        tomli_w.dump(data, f)

    click.echo(f"Set {key} = {value}")
