# AgentBenchPlatform

A platform for orchestrating multiple AI coding agents in parallel. Create tasks, spin up isolated agent sessions — each in its own git worktree and tmux pane — and let several agents work on the same codebase simultaneously. A persistent background server keeps everything running (Signal messenger, coordinator, sessions) even when the dashboard isn't open.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Clients                               │
│  ┌─────────┐  ┌───────────┐  ┌────────┐  ┌──────────┐ │
│  │   CLI   │  │ Dashboard │  │ Signal │  │  Other   │ │
│  │  (abp)  │  │   (TUI)   │  │  Phone │  │ Clients  │ │
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

**Server** runs persistently via systemd. It owns MongoDB connections, signal-cli, the coordinator agent, all sessions, and shared memory. Closing the dashboard or CLI has no effect on running agents or incoming Signal messages.

**Clients** (CLI, TUI dashboard, Signal) connect to the server over a Unix domain socket using JSON-RPC 2.0. The `RemoteContext` class provides the same interface as `AppContext`, so client code doesn't know or care whether it's local or remote.

---

## Setup

### Prerequisites

| Dependency | Purpose | Install |
|------------|---------|---------|
| Python 3.12+ | Runtime | `apt install python3.12` / `brew install python@3.12` |
| Docker | MongoDB backend | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop) |
| tmux | Session panes | `apt install tmux` / `brew install tmux` |
| Claude Code CLI | Primary coding agent | `npm install -g @anthropic-ai/claude-code` |
| OpenCode CLI | Optional agent | [github.com/opencode-ai/opencode](https://github.com/opencode-ai/opencode) |
| Java 21+ | Signal integration (optional) | `apt install openjdk-21-jre-headless` |
| signal-cli | Signal integration (optional) | See [Signal Integration](#signal-integration) |

### Install

```bash
git clone <repo-url> && cd AgentBenchPlatform
./scripts/start.sh
```

`start.sh` handles everything: starts MongoDB via Docker, creates a virtualenv, installs the package, runs migrations, creates a default config at `~/.config/agentbenchplatform/config.toml`, and installs a systemd user service.

```bash
source .venv/bin/activate
```

### API Keys

```bash
# Required — powers the coordinator and research agents
export ANTHROPIC_API_KEY=sk-ant-...

# Required for research web search
export BRAVE_SEARCH_API_KEY=BSA...

# Optional — use OpenRouter as an alternative LLM provider
export OPENROUTER_API_KEY=sk-or-...
```

For persistent keys, add them to `~/.config/agentbenchplatform/env`:

```bash
mkdir -p ~/.config/agentbenchplatform
cat > ~/.config/agentbenchplatform/env << 'EOF'
ANTHROPIC_API_KEY=sk-ant-...
BRAVE_SEARCH_API_KEY=BSA...
EOF
```

The systemd service automatically loads this file.

### Start the Server

```bash
# Option 1: systemd (recommended — survives terminal close, auto-restarts)
systemctl --user enable --now agentbenchplatform

# Option 2: foreground (for debugging)
abp server start --foreground
```

### Verify

```bash
abp server status
abp config show
abp task list
```

`abp` is the short alias for `agentbenchplatform`.

### Stopping

```bash
# Stop the server
systemctl --user stop agentbenchplatform

# Stop MongoDB (data persists)
docker compose down

# Stop MongoDB and delete all data
docker compose down -v
```

---

## Getting Started

The core loop is: **create a task → start sessions → review their work → merge it in**.

### Create a task

A task is a unit of work tied to a project directory:

```bash
abp task create "add user auth" \
  --workspace ~/projects/myapp \
  --description "JWT-based login and signup endpoints" \
  --tags backend,auth
```

The `--workspace` flag points at the git repo the agents will work in. Each session gets its own git worktree branched from `HEAD`.

### Start a session

```bash
abp session start add-user-auth \
  --agent claude_code \
  --prompt "Implement JWT login and signup in src/auth/. Use bcrypt for passwords."
```

This:
1. Creates a git branch `session/claude_code-<id>` and a worktree
2. Opens a tmux pane and launches Claude Code inside the worktree
3. Tracks the process (PID, lifecycle state) in MongoDB

### Watch it work

```bash
abp session attach <session-id>    # drops into the tmux pane (Ctrl-b d to detach)
abp session list                    # see all sessions
abp dashboard                      # full TUI dashboard
```

### Start more sessions in parallel

Each session gets its own worktree and branch — start as many as you want:

```bash
abp session start add-user-auth \
  --agent claude_code \
  --prompt "Write integration tests for the auth endpoints."
```

### When sessions finish

```bash
abp session archive <session-id>   # removes worktree, keeps branch
```

Review and merge:

```bash
cd ~/projects/myapp
git log session/claude_code-a3f9b2c1 --oneline
git merge session/claude_code-a3f9b2c1
git branch -d session/claude_code-a3f9b2c1
```

---

## Example End-to-End Workflow

```bash
# Create the task
abp task create "full-text search" \
  --workspace ~/projects/myapp \
  --description "Add full-text search for users and posts" \
  --tags feature,search

# Run research first
abp research start full-text-search \
  --query "full-text search implementation in Node.js with PostgreSQL"

# Check findings
abp research results full-text-search

# Session 1: implement the feature
abp session start full-text-search \
  --agent claude_code \
  --prompt "Implement full-text search. Check shared memory for research findings."

# Session 2: write tests (parallel, separate worktree)
abp session start full-text-search \
  --agent claude_code \
  --prompt "Write tests for the search feature."

# Drop a note in shared memory so both agents stay aligned
abp memory store \
  --task full-text-search \
  --key "search-decision" \
  --content "Using PostgreSQL tsvector. Index on users.name and posts.body."

# Watch the dashboard
abp dashboard

# Archive sessions, review, merge
abp session archive <session-1-id>
abp session archive <session-2-id>
cd ~/projects/myapp
git merge session/claude_code-abc12345
git merge session/claude_code-def67890
abp task archive full-text-search
```

---

## Commands

### Server

```bash
abp server start [--foreground]    # start the background server
abp server stop                    # stop the server
abp server status                  # check if server is running
```

### Tasks

```bash
abp task create "title" [--workspace PATH] [--description TEXT] [--tags a,b,c]
abp task list [--all] [--archived]
abp task show <slug>
abp task archive <slug>
abp task delete <slug>
```

### Sessions

```bash
abp session start <task-slug> --agent claude_code --prompt "..."
abp session list [--task <slug>]
abp session status <session-id>
abp session attach <session-id>
abp session stop <session-id>
abp session pause <session-id>
abp session resume <session-id>
abp session archive <session-id>
```

### Research

```bash
abp research start <task-slug> --query "..." [--breadth 4] [--depth 3]
abp research status <session-id>
abp research results <task-slug>
```

### Shared Memory

```bash
abp memory store --task <slug> --key "name" --content "..."
abp memory search --query "..." [--task <slug>] [--limit 5]
abp memory list [--task <slug>]
abp memory delete <memory-id>
```

### Coordinator

The coordinator is a meta-agent with tool access to the whole system — it can list tasks, start sessions, search memory, and more.

```bash
abp coordinator ask "what's running right now?"
abp coordinator ask "summarize progress on full-text-search"
abp coordinator chat    # interactive session
```

### Config

```bash
abp config init                                      # create default config
abp config show                                      # show current config
abp config set general.default_agent claude_code     # set a value
abp config set coordinator.model claude-sonnet-4-20250514
```

### Dashboard

```bash
abp dashboard
```

| Key | Action |
|-----|--------|
| `t` | New task |
| `s` | New session |
| `a` | Attach to tmux pane |
| `x` | Stop session |
| `p` | Pause / resume |
| `d` | Detail view |
| `r` | Research monitor |
| `c` | Coordinator chat |
| `w` | Workspaces |
| `m` | Memory browser |
| `b` | File browser |
| `u` | Usage monitor |
| `q` | Quit |

---

## Signal Integration

Text the coordinator from your phone via [signal-cli](https://github.com/AsamK/signal-cli). Messages are processed by the server even when the dashboard is closed.

### Prerequisites

```bash
sudo apt install openjdk-21-jre-headless
```

Install signal-cli:

```bash
VERSION=$(curl -Ls -o /dev/null -w %{url_effective} \
  https://github.com/AsamK/signal-cli/releases/latest | sed -e 's/^.*\/v//')
curl -L -O "https://github.com/AsamK/signal-cli/releases/download/v${VERSION}/signal-cli-${VERSION}.tar.gz"
sudo tar xf "signal-cli-${VERSION}.tar.gz" -C /opt
sudo ln -sf "/opt/signal-cli-${VERSION}/bin/signal-cli" /usr/local/bin/
```

### Register a dedicated number

Use a dedicated phone number (e.g. Google Voice), not your personal Signal account.

```bash
# Get a captcha token from https://signalcaptchas.org/registration/generate.html
signal-cli -a +1YOURNUMBER register --captcha "CAPTCHA_TOKEN"

# Verify immediately (session expires in ~2 minutes)
signal-cli -a +1YOURNUMBER verify CODE
```

### Configure

```bash
abp config set signal.enabled true
abp config set signal.account "+1YOURNUMBER"
abp config set signal.allowed_senders '["+1SENDERPHONENUMBER"]'
```

If port 8080 is in use (e.g. by llama.cpp):

```bash
abp config set signal.http_url 'http://127.0.0.1:8081'
```

### Troubleshooting

- **`Failed to initialize HTTP Server`** — port conflict. Check with `ss -tlnp | grep 8080` and change `signal.http_url`.
- **Messages not arriving** — run `abp signal status` and verify `daemon_running`, `daemon_healthy`, and `listening` are all true.
- **`Rejected message from unauthorized sender`** — add the sender to `allowed_senders` or set `dm_policy` to `open`.

---

## Server/Client RPC API

The server exposes ~40 methods over JSON-RPC 2.0 on a Unix domain socket:

| Namespace | Methods |
|-----------|---------|
| `server` | `ping`, `status` |
| `task` | `list`, `get`, `get_by_id`, `create`, `archive`, `delete` |
| `session` | `list`, `get`, `start_coding`, `stop`, `pause`, `resume`, `archive`, `get_output`, `send_to`, `check_liveness`, `get_diff`, `run_in_worktree` |
| `dashboard` | `snapshot`, `workspaces` |
| `coordinator` | `message`, `ask` |
| `memory` | `list`, `search`, `store` |
| `usage` | `aggregate_recent`, `aggregate_totals`, `list_recent` |
| `workspace` | `find_by_path`, `insert`, `delete` |
| `signal` | `start`, `stop`, `status`, `pair_sender` |
| `coordinator_history` | `list_conversations`, `load_conversation` |

**Socket location:** `$XDG_RUNTIME_DIR/agentbenchplatform.sock` (typically `/run/user/1000/agentbenchplatform.sock`)

Example request:

```json
{"jsonrpc": "2.0", "id": 1, "method": "task.list", "params": {"show_all": false}}
```

---

## Configuration Reference

Config file: `~/.config/agentbenchplatform/config.toml`

| Section | Key | Default | Description |
|---------|-----|---------|-------------|
| `general` | `workspace_root` | `~/agentbench-workspaces` | Default worktree parent |
| `general` | `default_agent` | `claude_code` | Default agent backend |
| `mongodb` | `uri` | `mongodb://localhost:27017/?directConnection=true` | MongoDB connection |
| `mongodb` | `database` | `agentbenchplatform` | Database name |
| `providers.anthropic` | `api_key_env` | `ANTHROPIC_API_KEY` | Env var for API key |
| `providers.openrouter` | `api_key_env` | `OPENROUTER_API_KEY` | Env var for API key |
| `embeddings` | `provider` | `llamacpp` | Embedding provider |
| `embeddings` | `dimensions` | `768` | Vector dimensions |
| `coordinator` | `provider` | `anthropic` | LLM provider for coordinator |
| `coordinator` | `model` | `claude-sonnet-4-20250514` | Model for coordinator |
| `research` | `default_breadth` | `4` | Search breadth |
| `research` | `default_depth` | `3` | Recursion depth |
| `signal` | `enabled` | `false` | Enable Signal integration |
| `signal` | `dm_policy` | `allowlist` | `allowlist` or `open` |
| `tmux` | `session_prefix` | `ab` | tmux session name prefix |
| `server` | `socket_path` | auto | Unix socket path |
| `server` | `pid_file` | auto | PID file path |

Environment variables `MONGODB_URI` and `AGENTBENCH_DB` override the `[mongodb]` section.

---

## Project Structure

```
agentbenchplatform/
  cli.py                    # CLI entry point (Click)
  config.py                 # TOML config + env overlay
  context.py                # AppContext — dependency injection container
  remote_context.py         # RemoteContext — RPC client proxy (same interface)
  models/                   # Frozen dataclasses, no IO
    task.py                 # Task, TaskStatus
    session.py              # Session, SessionKind, SessionLifecycle
    memory.py               # MemoryEntry, MemoryScope, MemoryQuery
    usage.py                # UsageEvent
    agent.py                # AgentBackendType, AgentConfig
    provider.py             # LLMMessage, LLMConfig, ProviderType
    research.py             # ResearchConfig, Learning, ResearchReport
    workspace.py            # Workspace
  services/                 # Business logic layer
    task_service.py         # Task CRUD + lifecycle
    session_service.py      # Session lifecycle (worktree, tmux, process)
    coordinator_service.py  # Meta-agent with system-wide tool access
    memory_service.py       # Store/search with auto-embedding
    research_service.py     # Recursive depth-first research loop
    dashboard_service.py    # Snapshot aggregation for TUI
    embedding_service.py    # Text embeddings via llama.cpp
    signal_service.py       # Signal messenger bridge
    routing.py              # Agent tier routing
  infra/                    # IO and external integrations
    git.py                  # Git worktree create/remove
    subprocess_mgr.py       # tmux + process management
    agents/                 # Agent backends (claude_code, opencode, claude_local)
    db/                     # MongoDB repos (Motor async), migrations
    providers/              # LLM providers (anthropic, openrouter, llamacpp)
    rpc/                    # JSON-RPC 2.0 server + client
      protocol.py           # Message framing (request/response/notification)
      server.py             # Unix socket server
      client.py             # Unix socket client
      methods.py            # Method registry (~40 RPC methods)
      serialization.py      # Model <-> JSON conversion
    search/                 # Web search (Brave)
    signal/                 # signal-cli daemon + HTTP client
  commands/                 # CLI handlers (thin, delegate to services via RPC)
    server_cmd.py           # server start/stop/status
    task_cmd.py             # task CRUD
    session_cmd.py          # session lifecycle
    coordinator_cmd.py      # coordinator ask/chat
    memory_cmd.py           # memory store/search
    research_cmd.py         # research start/status/results
    signal_cmd.py           # signal daemon management
    config_cmd.py           # config init/show/set
    dashboard_cmd.py        # dashboard launcher
    _helpers.py             # get_remote_context() helper
  ui/                       # Textual TUI
    app.py                  # Main app (connects via RemoteContext)
    screens/                # 15 screens (dashboard, chat, research, etc.)
    widgets/                # Reusable widgets (task tree, log viewer, etc.)
    styles/                 # TCSS stylesheets
scripts/
  start.sh                  # Full setup script
  stop.sh                   # Shutdown script
  agentbenchplatform.service # systemd user service unit
docker-compose.yml           # MongoDB Atlas Local (with vector search)
pyproject.toml               # Package metadata and dependencies
```

## Tech Stack

- **Python 3.12+**, asyncio throughout
- **Click** (CLI), **Textual** (TUI)
- **MongoDB** + **Motor** (async) for storage, vector search via `$vectorSearch`
- **httpx** for HTTP calls (OpenRouter, llama.cpp, signal-cli)
- **anthropic** SDK for Anthropic provider
- **JSON-RPC 2.0** over Unix domain socket for server/client IPC

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
systemctl --user restart agentbenchplatform        # restart
systemctl --user stop agentbenchplatform           # stop

# Manual
abp server start --foreground   # run in current terminal
abp server stop                 # stop via PID file
abp server status               # check status
```
