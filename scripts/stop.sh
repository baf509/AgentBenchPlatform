#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }

PURGE=false
if [[ "${1:-}" == "--purge" ]]; then
    PURGE=true
fi

info "Stopping MongoDB..."
if $PURGE; then
    warn "Purging all data volumes..."
    docker compose down -v
else
    docker compose down
fi

if $PURGE; then
    info "Done. Data volumes deleted."
else
    info "Done. Data volumes preserved."
fi
echo "  Restart with: ./scripts/start.sh"
