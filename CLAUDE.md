# CLAUDE.md

This file provides guidance to Claude Code when working with code in this codebase.

## Tech Stack

- **Python 3.12+**, asyncio throughout
- **Click** (CLI), **Textual** (TUI)
- **MongoDB** + **Motor** (async) for storage, vector search via `$vectorSearch`
- **httpx** for HTTP calls (OpenRouter, llama.cpp, signal-cli)
- **anthropic** SDK for Anthropic provider
- **JSON-RPC 2.0** over Unix domain socket for server/client IPC
- **tmux** + **git worktree** for session isolation

## Common Development Commands

```bash
# Install dependencies
source .venv/bin/activate  # or: python -m venv .venv && pip install -e .
pip install -e ".[dev]"

# Run tests
pytest
pytest -v
pytest tests/test_models/

# Lint
ruff check .

# Start the server (foreground, debug)
abp server start --foreground

# Start the TUI dashboard
abp dashboard

# CLI examples
abp task create "my task" --workspace ~/projects/myapp --description "desc"
abp session start my-task --agent claude_code --prompt "implement feature X"
abp memory store --task my-task --key "decision" --content "Using PostgreSQL"
```

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Clients                               │
│  ┌─────────┐  ┌───────────┐  ┌────────┐  ┌──────────┐ │
│  │   CLI   │  │ Dashboard │  │ Signal │  │  Other   │ │
│  │  (abp)  │  │   (TUI)   │  │  Phone │  │  Clients  │ │
│  └────┬────┘  └─────┬─────┘  └───┬────┘  └────┬─────┘ │
│       │             │             │             │        │
│       └─────────────┴──────┬──────┴─────────────┘        │
│                            │                             │
│                   Unix Domain Socket                     │
│                    (JSON-RPC 2.0)                        │
│                            │                             │
├────────────────────────────┼─────────────────────────────┤
│                            │                             │
│                    ┌───────┴───────┐                     │
│                    │  RPC Server   │                     │
│                    └───────┬───────┘                     │
│                            │                             │
│              ┌─────────────┼─────────────┐               │
│              │         AppContext         │               │
│              │  (dependency injection)   │               │
│              └─────────────┬─────────────┘               │
│                            │                             │
│     ┌──────────┬───────────┼───────────┬──────────┐     │
│     │          │           │           │          │     │
│  ┌──┴───┐ ┌───┴────┐ ┌────┴────┐ ┌────┴───┐ ┌───┴──┐ │
│  │Tasks │ │Sessions│ │Coordin- │ │Research│ │Memory│ │
│  │      │ │        │ │  ator   │ │        │ │      │ │
│  └──┬───┘ └───┬────┘ └────┬────┘ └────┬───┘ └───┬──┘ │
│     │         │            │           │         │     │
│     └─────────┴────────────┼───────────┴─────────┘     │
│                            │                             │
│     ┌──────────┬───────────┼───────────┬──────────┐     │
│     │          │           │           │          │     │
│  ┌──┴───┐ ┌───┴────┐ ┌────┴────┐ ┌────┴───┐ ┌───┴──┐ │
│  │Mongo │ │  tmux  │ │  LLM   │ │ Brave  │ │signal│ │
│  │  DB  │ │worktree│ │Providers│ │ Search │ │ -cli │ │
│  └──────┘ └────────┘ └─────────┘ └────────┘ └──────┘ │
│                                                         │
│                  Background Server                       │
│              (systemd user service)                      │
└─────────────────────────────────────────────────────────┘
```

- **Server** runs persistently via systemd. Owns MongoDB connections, signal-cli, coordinator agent, all sessions, and shared memory. Closing dashboard/CLI doesn't affect running agents or Signal messages.
- **Clients** (CLI, TUI, Signal) connect to server over Unix domain socket using JSON-RPC 2.0. `RemoteContext` class provides same interface as `AppContext`, so client code is unaware of local vs remote.

## Important Conventions/Patterns

- **Async/await throughout**: All service methods are async; use `await` properly
- **Dependency injection**: `AppContext` centralizes service instances (tasks, sessions, memory, etc.). Services receive context in constructor and access dependencies via `self.ctx`.
- **Models**: Pydantic-like frozen dataclasses (no IO logic). IO handled by services/infra.
- **Services**: Business logic layer. Each service manages one domain (tasks, sessions, memory, research, coordinator, etc.).
- **Infra layer**: External integrations (git, tmux, MongoDB, LLM providers, signal-cli, search). Services call infra, never the other way around.
- **Commands**: CLI handlers are thin; delegate to services via RPC. Some commands (e.g., `dashboard`) launch UI directly.
- **RPC boundary**: JSON-RPC 2.0 server exposes ~40 methods. All data crosses boundary as JSON; no direct object sharing.
- **Git worktree + tmux**: Each session gets isolated worktree (branch from HEAD) + tmux pane. `infra/subprocess_mgr.py` manages lifecycle.
- **Config**: TOML config (`~/.config/agentbenchplatform/config.toml`) + env overlay. Access via `config.py` singleton.
- **Embeddings**: Vector search uses MongoDB `$vectorSearch` with dimensions from config (default 768).
- **Signal integration**: Optional. signal-cli daemon runs externally; server talks to it via HTTP. Requires Java 21+.

## References

- **README.md**: Complete setup, usage, architecture, commands, configuration
- **pyproject.toml**: Dependencies, scripts, pytest/ruff config
- **agentbenchplatform/cli.py**: CLI structure, command registration
- **agentbenchplatform/context.py**: `AppContext` and dependency injection
- **agentbenchplatform/infra/rpc/**: JSON-RPC server/client implementation
- **agentbenchplatform/services/**: Business logic services
- **agentbenchplatform/infra/**: External integrations (db, git, agents, providers, signal, search)
- **agentbenchplatform/ui/**: Textual TUI dashboard
- **commands/**: CLI command handlers
- **tests/**: Test suite structure
- **docker-compose.yml**: MongoDB with vector search enabled
- **scripts/start.sh**: Automated setup script

## Running Tests

```bash
source .venv/bin/activate
pytest              # all tests
pytest -v           # verbose
pytest tests/test_models/  # specific directory
```

## Managing the Server

```bash
# systemd (recommended)
systemctl --user enable --now agentbenchplatform   # start + enable on boot
systemctl --user status agentbenchplatform         # check status
journalctl --user -u agentbenchplatform -f         # tail logs
# restart/stop as needed

# Manual
abp server start --foreground   # run in current terminal
abp server stop                 # stop via PID file
abp server status               # check status
```

## Notes

- The server manages agent sessions in isolated tmux + git worktree environments
- Vector search uses MongoDB's `$vectorSearch` with embeddings stored in `Memory`
- Signal integration enables SMS-based agent control
- LLM provider selection is configurable per agent run
- CLI and TUI communicate with server via JSON-RPC over Unix socket
- Use `abp --help` for CLI command reference

## Development Workflow

1. Make changes to code
2. Run tests: `pytest`
3. Lint: `ruff check .`
4. Start server: `abp server start --foreground` to test manually
5. Use CLI/TUI to interact with the system
- Commit changes with clear, descriptive messages

## Important Files

- `abp/server.py` - Main server implementation
- `abp/cli.py` - CLI entry point and commands
- `abp/models.py` - Data models (Task, Session, Memory)
- `abp/agent_worker.py` - Agent worker implementation
- `abp/llm_providers.py` - LLM provider abstractions

## Configuration

- `.env` - Environment variables (MongoDB URI, API keys)
- `pyproject.toml` - Project dependencies and metadata
- `abp/keybindings.json` - CLI keybindings (customizable)

This document will be updated as the codebase evolves. For questions not covered here, refer to the README.md or ask in the repository's issue tracker.

---

Last updated: 2026-02-14
Next review: 2026-02-28 (or when architecture changes)
```

I've updated the CLAUDE.md file with the revised architecture diagram and conventions. The file is ready for use by future Claude Code instances.

Now, let me address the user's request about reviewing the **Coordinator function** within this project. I need to explore the codebase to find the coordinator-related code and provide enhancement suggestions.

Let me start by searching for coordinator-related files and code.
