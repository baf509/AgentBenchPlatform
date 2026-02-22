#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[x]${NC} $*"; }

# -----------------------------------------------------------
# 1. Check prerequisites
# -----------------------------------------------------------
info "Checking prerequisites..."

if ! command -v python3 &>/dev/null; then
    error "python3 not found."
    exit 1
fi

info "Prerequisites OK"

# -----------------------------------------------------------
# 2. Check shared infrastructure MongoDB is running
# -----------------------------------------------------------
info "Checking shared infrastructure MongoDB..."

if ! mongosh --port 27017 --quiet --eval "rs.status().ok" &>/dev/null 2>&1; then
    error "Shared MongoDB is not running on port 27017."
    echo ""
    echo "  Start the shared infrastructure first:"
    echo "    cd /home/ben/Dev/infrastructure && docker compose up -d"
    echo ""
    exit 1
fi

info "Shared MongoDB is ready"

# -----------------------------------------------------------
# 3. Set up Python venv if needed
# -----------------------------------------------------------
if [ ! -d ".venv" ]; then
    info "Creating Python virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

if ! command -v agentbenchplatform &>/dev/null; then
    info "Installing agentbenchplatform..."
    pip install -e ".[dev]" --quiet
fi

# -----------------------------------------------------------
# 4. Initialize config if needed
# -----------------------------------------------------------
CONFIG_PATH="$HOME/.config/agentbenchplatform/config.toml"
if [ ! -f "$CONFIG_PATH" ]; then
    info "Creating default config at $CONFIG_PATH..."
    agentbenchplatform config init
fi

# -----------------------------------------------------------
# 5. Run migrations (create indexes)
# -----------------------------------------------------------
info "Running database migrations..."
python -c "
import asyncio
from agentbenchplatform.context import AppContext

async def migrate():
    ctx = AppContext()
    await ctx.initialize()
    await ctx.close()
    print('  Indexes created successfully')

asyncio.run(migrate())
"

# -----------------------------------------------------------
# 6. Install systemd user service (optional)
# -----------------------------------------------------------
SYSTEMD_DIR="$HOME/.config/systemd/user"
if [ ! -f "$SYSTEMD_DIR/agentbenchplatform.service" ]; then
    info "Installing systemd user service..."
    mkdir -p "$SYSTEMD_DIR"
    cp "$SCRIPT_DIR/agentbenchplatform.service" "$SYSTEMD_DIR/"
    systemctl --user daemon-reload 2>/dev/null || true
    info "  Enable with: systemctl --user enable --now agentbenchplatform"
fi

# -----------------------------------------------------------
# Done
# -----------------------------------------------------------
echo ""
info "========================================="
info "  AgentBenchPlatform is ready!"
info "========================================="
echo ""
echo "  Shared infra: /home/ben/Dev/infrastructure (mongod, mongot, llamacpp, embeddings)"
echo "  MongoDB:  mongodb://localhost:27017/?directConnection=true&replicaSet=rs0"
echo "  Embeddings: http://localhost:8001 (voyage-4-nano, 1024-dim)"
echo "  llama.cpp:  http://localhost:8080"
echo ""
echo "  Quick start:"
echo "    source .venv/bin/activate"
echo "    agentbenchplatform server start --foreground  # start server"
echo "    # In another terminal:"
echo "    agentbenchplatform server status              # check server"
echo "    agentbenchplatform task create \"my first task\""
echo "    agentbenchplatform dashboard                  # TUI (requires server)"
echo ""
echo "  Or use systemd for persistent server:"
echo "    systemctl --user enable --now agentbenchplatform"
echo ""
echo "  Set API keys for full features:"
echo "    export OPENROUTER_API_KEY=sk-or-..."
echo "    export ANTHROPIC_API_KEY=sk-ant-..."
echo "    export BRAVE_SEARCH_API_KEY=BSA..."
echo ""
