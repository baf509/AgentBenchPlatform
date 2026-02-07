# agentbenchplatform

Agent workbench platform with persistent server/client architecture for orchestrating multiple AI agents.

## Tech Stack
- Python 3.12+, asyncio throughout
- Click (CLI), Textual (TUI)
- MongoDB + Motor (async) for storage, vector search via $vectorSearch
- httpx for HTTP calls (OpenRouter, llama.cpp, signal-cli)
- anthropic SDK for Anthropic provider
- JSON-RPC 2.0 over Unix domain socket for server/client IPC

## Project Layout
- `agentbenchplatform/models/` - Frozen dataclasses, no IO
- `agentbenchplatform/services/` - Business logic layer
- `agentbenchplatform/infra/` - IO / external integrations (DB, agents, providers, signal, search, RPC)
- `agentbenchplatform/infra/rpc/` - JSON-RPC server, client, protocol, method registry
- `agentbenchplatform/commands/` - CLI handlers (thin, delegate to services via RPC)
- `agentbenchplatform/ui/` - Textual TUI
- `agentbenchplatform/context.py` - AppContext (server-side dependency injection)
- `agentbenchplatform/remote_context.py` - RemoteContext (client-side RPC proxy)

## Conventions
- All async where possible
- Domain models are frozen dataclasses with enum status fields
- Services depend on repos/providers via constructor injection
- CLI commands are thin wrappers that delegate to services via RemoteContext (RPC)
- Server owns all state; clients connect via Unix socket
- CLI alias: `abp`
